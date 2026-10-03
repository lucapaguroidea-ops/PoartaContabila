"""Operator routes (ARCHITECTURE §10): register tenants, upload witnesses, ingest, answer.

Bearer ``GRAPHUSERTOKEN_OPERATOR`` (old name ``OPERATOR_TOKEN``). It must differ from the
agent token: the agent imports, a person answers questions. Unset, equal to the agent token,
or no runtime → 503.

WP-38: ``GRAPHUSERTOKEN_CLAUDE_SYSBUILDER`` is the build agent's token (Claude, acting for the
owner): the same routes, **synthetic tenants only**. Every request must resolve to a tenant
marked ``data_class: synthetic`` (by the path's ``cui``, the ``cui`` query, the job's or the
batch's tenant), else 403; a tenant is never registered or turned into client data with it;
the model-call and answer logs show it only synthetic tenants' rows; its answers are logged
as ``claude-sysbuilder``. A route that names no tenant and is not listed is refused (default
deny). A sysbuilder token equal to another token is ignored.
"""

from __future__ import annotations

import base64
import binascii
import hmac
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from poarta_contabila.answers import OPERATOR_NAME_MAX
from poarta_contabila.codit import Codit, CoditError, CoditInput
from poarta_contabila.extract.statement import StatementMeta
from poarta_contabila.registry import ExportKind, Product, Tenant
from poarta_contabila.rules import ExplainedRule, RuleBody
from poarta_contabila.runtime import IngestRefused, Runtime
from poarta_contabila.sinks.exports import ExportError
from poarta_contabila.types import Cui, Period, Slug

_RAW = Body(..., media_type="application/octet-stream")


class DecontUpload(BaseModel):
    filename: str
    period: Period
    file_b64: str
    tenant_on_doc: bool = False  # the operator states the tenant is on the report (fail closed)


class StatementUpload(BaseModel):
    """The bank's PDF, its header, and the movement tables if already read (EXTRACT.md);
    without tables the statement reader (Document AI) reads them."""

    meta: StatementMeta
    tables: list[dict[str, Any]] | None = None
    pdf_b64: str
    strong: bool = False
    """Gemini reads with its strong tier first (00_LAW §8 A4); synthetic tenants only."""


class RuleRequest(RuleBody):
    cui: Cui
    rule_id: Slug


SYSBUILDER = "claude-sysbuilder"
_TENANTLESS = {
    "/model-roles",
    "/model-calls",
    "/model-keys",
    "/answers",
    "/rules",
}  # filtered or body-checked


class ReadingChoiceBody(BaseModel):
    choice: Literal["wait", "reserve"]


class RoleChoiceBody(BaseModel):
    choice: Literal["wait", "pause", "allow_synthetic"]
    until: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class SkipBody(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


def _builder(request: Request) -> bool:
    return getattr(request.state, "principal", None) == SYSBUILDER


def _synthetic_only(rt: Runtime, request: Request) -> None:
    """The build agent's scope (WP-38): this request's tenant must be synthetic."""
    params, query = request.path_params, request.query_params
    if "cui" in params:
        cui = params["cui"]
        existing = rt.registry.tenant(cui)
        if request.method == "PUT" and request.url.path == f"/tenants/{cui}" and existing is None:
            return  # a new tenant: the route checks it is synthetic
    elif "cui" in query:
        cui = query["cui"]
    elif "job_id" in params:
        try:
            cui = rt.jobs.get(params["job_id"]).tenant.cui
        except KeyError:
            raise HTTPException(404, "unknown job") from None
    elif "batch_id" in params:
        cui = rt.batch_tenant(params["batch_id"])
        if cui is None:
            raise HTTPException(404, f"unknown batch {params['batch_id']}")
    elif request.url.path in _TENANTLESS:
        return
    elif request.url.path.startswith("/model-roles/") and request.url.path.endswith("/compare"):
        return  # WP-59: synthetic tenants' questions only
    else:
        raise HTTPException(403, "the build agent's token does not open this route")
    if not rt._synthetic(cui):
        raise HTTPException(
            403, f"the build agent's token is for synthetic tenants only, not {cui}"
        )


def operator_router(
    runtime: Callable[[], Runtime | None],
    token: Callable[[], str | None],
    agent_token: Callable[[], str | None],
    sysbuilder_token: Callable[[], str | None] = lambda: None,
) -> APIRouter:
    def operator(request: Request, authorization: str | None = Header(default=None)) -> Runtime:
        expected, rt = token(), runtime()
        if not expected or rt is None or expected == agent_token():
            raise HTTPException(503, "operator API not configured")
        given = (authorization or "").removeprefix("Bearer ").strip().encode()
        if hmac.compare_digest(given, expected.encode()):
            request.state.principal = "operator"
            return rt
        builder = sysbuilder_token()
        if builder and builder not in (expected, agent_token()):
            if hmac.compare_digest(given, builder.encode()):
                request.state.principal = SYSBUILDER
                _synthetic_only(rt, request)
                return rt
        raise HTTPException(401, "operator token required")

    def who(
        request: Request,
        rt: Runtime = Depends(operator),
        x_operator_name: str | None = Header(default=None),
    ) -> str | None:
        """The person answering (WP-33): one shared token names nobody, so they say. The
        build agent's answers are always its own (WP-38)."""
        if _builder(request):
            return SYSBUILDER
        if x_operator_name is None:
            return None
        name = x_operator_name.strip()
        if not name or len(name) > OPERATOR_NAME_MAX or not name.isprintable():
            raise HTTPException(422, f"X-Operator-Name: 1–{OPERATOR_NAME_MAX} printable chars")
        return name

    router = APIRouter(tags=["operator"])

    @router.put("/tenants/{cui}")
    def put_tenant(
        cui: str, body: Tenant, request: Request, rt: Runtime = Depends(operator)
    ) -> Tenant:
        if body.cui != cui:
            raise HTTPException(422, "body cui differs from the path")
        if _builder(request) and body.data_class != "synthetic":
            raise HTTPException(403, "the build agent's token registers synthetic tenants only")
        rt.registry.put_tenant(body)
        return body

    @router.post("/tenants/{cui}/exports/{kind}")
    def put_export(
        cui: str,
        kind: ExportKind,
        filename: str = Query(...),
        product: Product | None = Query(default=None),
        periods: str | None = Query(default=None, description="comma-separated YYYY-MM"),
        data: bytes = _RAW,
        rt: Runtime = Depends(operator),
    ) -> dict[str, Any]:
        try:
            months = [p.strip() for p in periods.split(",")] if periods else None
            return rt.put_export(cui, kind, product, data, filename, months)
        except (ExportError, IngestRefused, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/ingest")
    def ingest(
        cui: str = Query(...),
        filename: str = Query(...),
        data: bytes = _RAW,
        rt: Runtime = Depends(operator),
    ) -> dict[str, Any]:
        try:
            return rt.ingest_upload(cui, data, filename)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/periods/{cui}/{period}/diff")
    def period_diff(
        cui: str,
        period: str,
        tva: str | None = Query(default=None, description="CO.DiT axis tva until WP-11"),
        exig: str | None = Query(default=None),
        rt: Runtime = Depends(operator),
    ) -> dict[str, Any]:
        axes = {k: v for k, v in (("tva", tva), ("exig", exig)) if v}
        return rt.period_diff(cui, period, axes)

    @router.put("/codit/{cui}/{period}")
    def put_codit(
        cui: str, period: str, body: CoditInput, rt: Runtime = Depends(operator)
    ) -> Codit:
        try:
            return rt.put_codit(cui, period, body)
        except (CoditError, IngestRefused, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/codit/{cui}/{period}")
    def get_codit(cui: str, period: str, rt: Runtime = Depends(operator)) -> Codit:
        doc = rt.codits.get(cui, period) if rt.codits is not None else None
        if doc is None:
            raise HTTPException(404, "no CO.DiT for this period (it is never assumed)")
        return doc

    @router.post("/extras/{cui}")
    def post_statement(
        cui: str, body: StatementUpload, response: Response, rt: Runtime = Depends(operator)
    ) -> dict[str, Any]:
        """A PDF statement (+ its extract tables, or read here) → one Job per movement line.
        202 ``{"status": "waiting"}``: no model can read it now; it is read again later."""
        try:
            pdf = base64.b64decode(body.pdf_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "pdf_b64 is not base64") from exc
        try:
            out = rt.ingest_statement(cui, body.meta, body.tables, pdf, body.strong)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc
        if out.get("status") == "waiting":
            response.status_code = 202
        return out

    @router.get("/reading/{cui}/budget")
    def reading_budget(
        cui: str,
        documents: int = Query(default=0, ge=0, description="statements about to be uploaded"),
        rt: Runtime = Depends(operator),
    ) -> dict[str, Any]:
        """WP-42: Gemini reads left today per model, what waits, and a warning before a batch
        the budget does not cover."""
        try:
            return rt.reading_budget(cui, documents)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/reading/{cui}/waiting")
    def reading_waiting(cui: str, rt: Runtime = Depends(operator)) -> list[dict[str, Any]]:
        """WP-42: this tenant's parked statements (waiting, read, refused)."""
        return [w.model_dump(mode="json", exclude={"meta"}) for w in rt.reading_waits.list(cui)]

    @router.post("/reading/{cui}/choice")
    def reading_choice(
        cui: str,
        body: ReadingChoiceBody,
        rt: Runtime = Depends(operator),
        operator_name: str | None = Depends(who),
    ) -> dict[str, Any]:
        """WP-43 (00_LAW §8 A6): every tier spent — ``wait`` for the reset, or ``reserve``:
        read with the catalog's reserve models until Pacific midnight. Recorded."""
        try:
            return rt.reading_choose(cui, body.choice, operator_name)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/reading/{cui}/waiting/{wait_id}/skip")
    def reading_skip(
        cui: str,
        wait_id: str,
        body: SkipBody,
        rt: Runtime = Depends(operator),
        operator_name: str | None = Depends(who),
    ) -> dict[str, Any]:
        """WP-43: set a parked statement aside (then upload it with its tables)."""
        try:
            return rt.skip_waiting(cui, wait_id, body.reason, operator_name)
        except IngestRefused as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/reading/{cui}/retry")
    def reading_retry(cui: str, rt: Runtime = Depends(operator)) -> list[dict[str, Any]]:
        """WP-42: read again now every parked statement of this tenant whose time has come."""
        return rt.retry_waiting(cui)

    @router.post("/filings/{cui}/{period}")
    def open_filings(cui: str, period: str, rt: Runtime = Depends(operator)) -> list[dict]:
        try:
            return rt.open_filings(cui, period)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/filings/{cui}/{period}")
    def get_filings(cui: str, period: str, rt: Runtime = Depends(operator)) -> list[dict]:
        try:
            return rt.filings_view(cui, period)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/filings/{cui}/{period}/{filing_id}/receipt")
    def filing_receipt(
        cui: str,
        period: str,
        filing_id: str,
        filename: str = Query(...),
        submitted_by: str = Query(..., min_length=1),
        data: bytes = _RAW,
        rt: Runtime = Depends(operator),
    ) -> list[dict]:
        """Attach the ANAF receipt this person got; it is the only thing that closes the item."""
        try:
            return rt.filing_receipt(cui, period, filing_id, data, filename, submitted_by)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/decont/{cui}")
    def post_decont(
        cui: str, body: DecontUpload, rt: Runtime = Depends(operator)
    ) -> dict[str, Any]:
        """An expense report: a container split into parts by a person (folder_triage, A2)."""
        try:
            data = base64.b64decode(body.file_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "file_b64 is not base64") from exc
        try:
            return rt.ingest_decont(
                cui, data, body.filename, body.period, tenant_on_doc=body.tenant_on_doc
            )
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/triage/{batch_id}")
    def get_batch(batch_id: str, rt: Runtime = Depends(operator)) -> dict[str, Any]:
        try:
            return rt.batch_view(batch_id)
        except KeyError:
            raise HTTPException(404, f"unknown batch {batch_id}") from None

    @router.post("/triage/{batch_id}/resume")
    def resume_batch(
        batch_id: str,
        body: dict[str, Any],
        rt: Runtime = Depends(operator),
        name: str | None = Depends(who),
    ) -> dict[str, Any]:
        try:
            return rt.resume_batch(batch_id, body, name)
        except KeyError:
            raise HTTPException(404, f"unknown batch {batch_id}") from None

    @router.get("/answers")
    def answers(
        request: Request,
        cui: str | None = Query(default=None),
        thread: str | None = Query(default=None, description="e.g. job:…, recon:{cui}:{period}"),
        limit: int = Query(default=50, ge=1, le=500),
        rt: Runtime = Depends(operator),
    ) -> list[dict[str, Any]]:
        """Every answer a person submitted, newest first (WP-33): what, when, who, outcome."""
        if _builder(request):  # WP-38: synthetic tenants' rows only
            rows = rt.answers.recent(cui=cui, thread_id=thread, limit=500)
            rows = [r for r in rows if r.tenant_cui and rt._synthetic(r.tenant_cui)][:limit]
        else:
            rows = rt.answers.recent(cui=cui, thread_id=thread, limit=limit)
        return [r.model_dump(mode="json") for r in rows]

    @router.post("/ocr-eval/{cui}")
    def ocr_eval(
        cui: str,
        case: str | None = Query(default=None, description="one case; all when omitted"),
        model: str | None = Query(default=None, description="another AI Studio model"),
        rt: Runtime = Depends(operator),
    ) -> dict[str, Any]:
        """WP-37: Gemini reads the synthetic evaluation statements; each is scored."""
        try:
            return rt.ocr_eval(cui, case, model)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/model-roles")
    def model_roles(rt: Runtime = Depends(operator)) -> list[dict[str, Any]]:
        """Every model role (00_LAW §3.5): where it acts, its model, whether it may be called."""
        return rt.model_roles_view()

    @router.get("/model-keys")
    def model_keys(rt: Runtime = Depends(operator)) -> dict[str, Any]:
        """WP-56: what each OpenRouter key has spent and has left, read from OpenRouter now
        (and the account's credits when a management key is set). Never a key value."""
        return rt.key_usage()

    @router.post("/model-roles/{role_id}/choice")
    def model_role_choice(
        role_id: str,
        body: RoleChoiceBody,
        request: Request,
        rt: Runtime = Depends(operator),
        operator_name: str | None = Depends(who),
    ) -> dict[str, Any]:
        """WP-53 (00_LAW §8 A7): no approved pin passes the data policy — ``wait``, ``pause``
        the role, or ``allow_synthetic`` until a date (synthetic tenants only). Operators only."""
        if _builder(request):
            raise HTTPException(403, "the build agent does not choose model routes")
        try:
            return rt.role_choose(role_id, body.choice, body.until, operator_name)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/model-roles/{role_id}/compare")
    def model_role_compare(
        role_id: str,
        inputs: int = Query(default=2, ge=1, le=5),
        runs: int = Query(default=1, ge=1, le=3),  # ~40 s a call: keep under the edge timeout
        rt: Runtime = Depends(operator),
    ) -> dict[str, Any]:
        """WP-59: the main pin against each approved alternate on the role's latest synthetic
        questions, first answer only. Nothing is recorded or changed."""
        try:
            return rt.model_compare(role_id, inputs, runs)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/model-calls")
    def model_calls(
        request: Request,
        role: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        rt: Runtime = Depends(operator),
    ) -> list[dict[str, Any]]:
        """What each role was sent, or would be (MODEL_CALLS=dry), newest first."""
        if _builder(request):  # WP-38: synthetic tenants' rows only
            rows = rt.model_calls.recent(role, 500)
            rows = [c for c in rows if c.tenant_cui and rt._synthetic(c.tenant_cui)][:limit]
        else:
            rows = rt.model_calls.recent(role, limit)
        return [c.model_dump(mode="json") for c in rows]

    @router.post("/recon/{cui}/{period}")
    def start_recon(cui: str, period: str, rt: Runtime = Depends(operator)) -> dict[str, Any]:
        """One reconcile_sink pass over the month's undecided PRE checks (WP-23)."""
        try:
            return rt.start_recon(cui, period)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/recon/{cui}/{period}")
    def get_recon(cui: str, period: str, rt: Runtime = Depends(operator)) -> dict[str, Any]:
        return rt.recon_view(cui, period)

    @router.post("/recon/{cui}/{period}/resume")
    def resume_recon(
        cui: str,
        period: str,
        body: dict[str, Any],
        rt: Runtime = Depends(operator),
        name: str | None = Depends(who),
    ) -> dict[str, Any]:
        return rt.resume_recon(cui, period, body, name)

    @router.post("/close/{cui}/{period}")
    def start_close(
        cui: str,
        period: str,
        tva: str | None = Query(default=None, description="CO.DiT axis tva until WP-11"),
        exig: str | None = Query(default=None),
        rt: Runtime = Depends(operator),
    ) -> dict[str, Any]:
        axes = {k: v for k, v in (("tva", tva), ("exig", exig)) if v}
        return rt.start_close(cui, period, axes)

    @router.get("/close/{cui}/{period}")
    def get_close(cui: str, period: str, rt: Runtime = Depends(operator)) -> dict[str, Any]:
        return rt.close_view(cui, period)

    @router.post("/close/{cui}/{period}/resume")
    def resume_close(
        cui: str,
        period: str,
        body: Any = Body(...),
        rt: Runtime = Depends(operator),
        name: str | None = Depends(who),
    ) -> dict[str, Any]:
        return rt.resume_close(cui, period, body, name)

    @router.post("/rules")
    def post_rule(
        body: RuleRequest, request: Request, rt: Runtime = Depends(operator)
    ) -> ExplainedRule:
        """A person writes a rule; a changed body is a new version, the old ones stay."""
        if _builder(request) and not rt._synthetic(body.cui):
            raise HTTPException(403, "the build agent's token is for synthetic tenants only")
        if rt.rules is None:
            raise HTTPException(503, "rule store not wired")
        if rt.registry.tenant(body.cui) is None:
            raise HTTPException(422, f"tenant {body.cui} is not registered")
        rule = RuleBody.model_validate(body.model_dump(exclude={"cui", "rule_id"}))
        return rt.rules.add(body.cui, body.rule_id, rule)

    @router.get("/rules/{cui}")
    def get_rules(cui: str, rt: Runtime = Depends(operator)) -> list[ExplainedRule]:
        return rt.rules.active(cui) if rt.rules is not None else []

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str, rt: Runtime = Depends(operator)) -> dict[str, Any]:
        try:
            return rt.view(job_id)
        except KeyError as exc:
            raise HTTPException(404, "unknown job") from exc

    @router.post("/jobs/{job_id}/resume")
    def resume(
        job_id: str,
        body: Any = Body(...),
        rt: Runtime = Depends(operator),
        name: str | None = Depends(who),
    ) -> dict:
        try:
            return rt.resume(job_id, body, name)
        except KeyError as exc:
            raise HTTPException(404, "unknown job") from exc

    return router
