"""Operator routes (ARCHITECTURE §10): register tenants, upload witnesses, ingest, answer.

Bearer ``OPERATOR_TOKEN``. It must differ from the agent token: the agent imports, a
person answers questions. Unset, equal to the agent token, or no runtime → 503.
"""

from __future__ import annotations

import base64
import binascii
import hmac
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel

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


class RuleRequest(RuleBody):
    cui: Cui
    rule_id: Slug


def operator_router(
    runtime: Callable[[], Runtime | None],
    token: Callable[[], str | None],
    agent_token: Callable[[], str | None],
) -> APIRouter:
    def operator(authorization: str | None = Header(default=None)) -> Runtime:
        expected, rt = token(), runtime()
        if not expected or rt is None or expected == agent_token():
            raise HTTPException(503, "operator API not configured")
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given.encode(), expected.encode()):
            raise HTTPException(401, "operator token required")
        return rt

    def who(x_operator_name: str | None = Header(default=None)) -> str | None:
        """The person answering (WP-33): one shared token names nobody, so they say."""
        if x_operator_name is None:
            return None
        name = x_operator_name.strip()
        if not name or len(name) > OPERATOR_NAME_MAX or not name.isprintable():
            raise HTTPException(422, f"X-Operator-Name: 1–{OPERATOR_NAME_MAX} printable chars")
        return name

    router = APIRouter(tags=["operator"])

    @router.put("/tenants/{cui}")
    def put_tenant(cui: str, body: Tenant, rt: Runtime = Depends(operator)) -> Tenant:
        if body.cui != cui:
            raise HTTPException(422, "body cui differs from the path")
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
        cui: str, body: StatementUpload, rt: Runtime = Depends(operator)
    ) -> dict[str, Any]:
        """A PDF statement (+ its extract tables, or read here) → one Job per movement line."""
        try:
            pdf = base64.b64decode(body.pdf_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(422, "pdf_b64 is not base64") from exc
        try:
            return rt.ingest_statement(cui, body.meta, body.tables, pdf)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

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
        cui: str | None = Query(default=None),
        thread: str | None = Query(default=None, description="e.g. job:…, recon:{cui}:{period}"),
        limit: int = Query(default=50, ge=1, le=500),
        rt: Runtime = Depends(operator),
    ) -> list[dict[str, Any]]:
        """Every answer a person submitted, newest first (WP-33): what, when, who, outcome."""
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

    @router.get("/model-calls")
    def model_calls(
        role: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        rt: Runtime = Depends(operator),
    ) -> list[dict[str, Any]]:
        """What each role was sent, or would be (MODEL_CALLS=dry), newest first."""
        return [c.model_dump(mode="json") for c in rt.model_calls.recent(role, limit)]

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
    def post_rule(body: RuleRequest, rt: Runtime = Depends(operator)) -> ExplainedRule:
        """A person writes a rule; a changed body is a new version, the old ones stay."""
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
