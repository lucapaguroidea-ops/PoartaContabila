"""ingest_source_doc: a Job walks its articol de cale up to `packaged`.

    bind → reconcile_pre → judge → approve (v3_approve) → package → wait_validare → intent_check

- **bind**: ArticoleFlux.matches on stored fields. One survivor binds; none or a tie asks
  ``define_articol`` (the answer must be a real articol on this graph).
- **reconcile_pre**: already in the books → ``already_in_sink`` and stop; ambiguous →
  ``needs_human`` and stop (the reason is on the job). The check is
  :func:`poarta_contabila.recon.pre.make_pre_check`, injected.
- **judge** (``v3_judge``): Jev's verdict, checkpointed on the thread before ``approve``.
  ``approve`` re-runs from its first line on resume; were Jev asked there, a call that failed
  (a person asked) and then answered on the replay would skip the question and drop the
  person's answer. Any error is a verdict that asks a person.
- **approve**: the articol's HITL policy (``always`` / ``first_n`` / ``never_if_risk_low``)
  plus the stored verdict decide whether a person must answer ``v3_approve``. Nothing
  touches SAGA before this answer (no side effect sits before ``interrupt()``).
- **package**: render through the articol's invoice WriteModule and write the XML once per
  ``export_key``; a replay of the node writes nothing.
- **wait_validare**: waits for SAGA. The Windows agent imports the package
  (status ``wait_validare``), a person validates in SAGA, and the agent's snapshot
  resumes the thread with the ``saga_doc_key`` of a document a stored snapshot shows
  validated; an answer without one is asked again. ``validated: false`` (import
  cancelled) → ``reopened``.
- **intent_check**: what SAGA posted must be what was packaged — side,
  gross, and net / VAT / partner CUI where the eye shows them. Same → ``acked``;
  any difference → ``needs_human`` with the differences (Devalidare is a person's).

Edges read ``state["status"]`` only. Runs on ``job:`` threads only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from poarta_contabila.catalog import Catalog
from poarta_contabila.flux import MatchContext, match_articole
from poarta_contabila.hitl import ask
from poarta_contabila.jev import unjudged
from poarta_contabila.packages import BlobStore, PackageRow, PackageStore, write_once
from poarta_contabila.period_diff import prefile_failures
from poarta_contabila.recon.pre import PreResult
from poarta_contabila.recon.settle import SETTLES, SettlementProposal
from poarta_contabila.sinks.saga_xml import (
    SagaXmlError,
    export_key,
    is_bank_mouth,
    mouth_doc_class,
    render_bank_line,
    render_invoice,
)
from poarta_contabila.types import CanonicalDocument, Closed, JobRecord, Slug, WriteModule

GRAPH_ID = "ingest_source_doc"
log = logging.getLogger(__name__)
THREAD_PREFIX = "job:"
_OUTBOUND = {"iesire", "storn_iesire"}
_INBOUND = {"intrare", "storn_intrare"}


class DefineArticolResume(Closed):
    articol_id: Slug


class V3ApproveResume(Closed):
    decision: Literal["approve", "reject", "edit"]
    edit: dict[str, Any] | None = None


class WaitValidareResume(Closed):
    validated: bool
    saga_doc_key: str | None = None


@dataclass
class IngestDeps:
    catalog: Catalog
    jobs: Any  # InMemoryJobStore | PostgresJobStore
    packages: PackageStore
    blobs: BlobStore
    pre_check: Callable[..., PreResult]  # (job, doc, *, fiscal_class, axes)
    judge: Callable[[CanonicalDocument, dict], dict]
    tenant_name: Callable[[str], str]
    allow_draft: bool = True
    snapshot_validated: Callable[[str, str], bool] = lambda cui, saga_doc_key: False
    """(tenant cui, saga_doc_key) → a stored agent snapshot shows it validated."""
    period_filed: Callable[[str, str], bool] = lambda cui, period: False
    """(cui, period) → a filing receipt exists: the period's packages are never regenerated."""
    posted_doc: Callable[[str, str], dict[str, Any] | None] = lambda cui, saga_doc_key: None
    """(tenant cui, saga_doc_key) → what SAGA shows for it (gross; net, vat, partner_cui,
    doc_class when known), or None."""
    treasury_account: Callable[[str, str], str | None] = lambda cui, iban: None
    """(tenant cui, IBAN) → the SAGA treasury account it maps to (``5121.01``), or None."""
    settlement: Callable[[CanonicalDocument], SettlementProposal | None] = lambda doc: None
    book_of_record: Callable[[str], str] = lambda cui: "saga"
    """(tenant cui) → its book of record; only ``saga`` has a mouth (LAW L8)."""
    observe: Callable[[str, dict, str | None], None] = lambda role_or_kind, payload, cui: None
    """(role_id, input, tenant cui): a shadow model role at its place (records only)."""
    observe_question: Callable[[str, dict, str | None], None] = lambda role_or_kind, payload, cui: (
        None
    )
    """(HITL kind, question, tenant cui): the System Two roles that would explain it."""
    """An unbound bank line → the invoices it could settle (a proposal for the person)."""

    def package(self, job: JobRecord, doc: CanonicalDocument, module: WriteModule) -> PackageRow:
        """Render and write once; set the job to `packaged`. Safe to replay."""
        if is_bank_mouth(module.module_id):
            cont = self.treasury_account(doc.tenant.cui, doc.maps.get("iban", ""))
            rendered = render_bank_line(doc, module, cont=cont)
        else:
            rendered = render_invoice(doc, module, tenant_name=self.tenant_name(doc.tenant.cui))
        key = export_key(module.module_id, job.job_id, job.schema_version)
        t = job.tenant
        bucket_key = (
            f"tenants/{t.cui}/{t.punct}/{job.period}/packages/{job.job_id}/"
            f"{rendered.folder}/{rendered.filename}"
        )
        row = write_once(
            self.packages,
            self.blobs,
            PackageRow(
                export_key=key, job_id=job.job_id, module_id=module.module_id, bucket_key=bucket_key
            ),
            rendered.xml,
        )
        self.jobs.update(job.job_id, status="packaged", module_id=module.module_id, export_key=key)
        return row


class IngestState(TypedDict, total=False):
    job_id: str
    source_doc_id: str
    axes: dict[str, str]
    canonical: dict[str, Any]
    articol_id: str
    status: str
    export_key: str
    saga_doc_key: str
    error: str
    pre: dict[str, Any]
    judge: dict[str, Any]


def start_payload(
    job: JobRecord,
    doc: CanonicalDocument,
    *,
    source_doc_id: str,
    axes: dict[str, str] | None = None,
) -> IngestState:
    """Initial state for a Job's thread (``job:{job_id}``)."""
    if doc.job_id != job.job_id:
        raise ValueError("canonical document belongs to another job")
    return {
        "job_id": job.job_id,
        "source_doc_id": source_doc_id,
        "axes": dict(axes or {}),
        "canonical": doc.model_dump(),
    }


_SIDE = {"intrare": "in", "storn_intrare": "in", "iesire": "out", "storn_iesire": "out"}


def intent_diffs(doc: CanonicalDocument, posted: dict[str, Any]) -> list[str]:
    """What SAGA shows against what was packaged; empty when they agree."""
    out = []
    side = posted.get("doc_class")
    if side and _SIDE.get(side, side) != _SIDE.get(doc.doc_class, doc.doc_class):
        out.append(f"posted as {side}, packaged as {doc.doc_class}")
    for field in ("gross", "net", "vat"):
        shown = posted.get(field)
        want = getattr(doc.totals, field)
        if shown is not None and Decimal(str(shown)) != Decimal(want):
            out.append(f"{field} {shown} in SAGA, {want} packaged")
    shown_cui = posted.get("partner_cui")
    if shown_cui and doc.partner.cui and shown_cui != doc.partner.cui:
        out.append(f"partner {shown_cui} in SAGA, {doc.partner.cui} packaged")
    return out


def _our_role(doc: CanonicalDocument) -> str | None:
    if doc.doc_class in _OUTBOUND:
        return "outbound"
    if doc.doc_class in _INBOUND:
        return "inbound"
    return None


def _edited(doc: CanonicalDocument, edit: dict[str, Any]) -> CanonicalDocument:
    """A person's edit over the document; ``maps`` keys are added or replaced, not dropped."""
    data = {**doc.model_dump(), **edit}
    if isinstance(edit.get("maps"), dict):
        data["maps"] = {**doc.maps, **edit["maps"]}
    return CanonicalDocument.model_validate(data)


def _proposal(deps: IngestDeps, doc: CanonicalDocument) -> dict[str, Any]:
    """For a bank line with no partner: the invoices it could settle, under ``proposal``.

    A proposal that cannot be built is left out; the question is asked all the same.
    """
    if doc.doc_class not in SETTLES or doc.partner.cui:
        return {}
    try:
        proposal = deps.settlement(doc)
    except Exception:  # a missing proposal never blocks the question
        log.exception("settlement proposal failed for %s", doc.job_id)
        return {}
    return {"proposal": proposal.model_dump()} if proposal is not None else {}


def _needs_question(deps: IngestDeps, job: JobRecord, articol: dict, verdict: dict) -> bool:
    if verdict.get("needs_human") or not verdict.get("accounts_ok", False):
        return True
    policy = articol.get("hitl", "always")
    if policy == "always":
        return True
    if policy == "first_n":
        return deps.jobs.packaged_count(job.tenant.cui, articol["articol_id"]) < int(
            articol.get("first_n") or 0
        )
    if policy == "never_if_risk_low":
        return verdict.get("risk") != "low"
    return True  # unknown policy: fail closed


def build_ingest_graph(deps: IngestDeps, *, checkpointer: Any):
    """Compile ingest_source_doc. Edges read stored status only."""
    cat = deps.catalog
    for kind in ("define_articol", "v3_approve", "wait_validare"):
        cat.hitl_kind(kind, graph_id=GRAPH_ID)

    def bind(state: IngestState, config) -> IngestState:
        thread = str(config["configurable"]["thread_id"])
        if not thread.startswith(THREAD_PREFIX):
            raise ValueError(f"{GRAPH_ID} runs on '{THREAD_PREFIX}' threads, got {thread!r}")
        job = deps.jobs.get(state["job_id"])
        doc = CanonicalDocument.model_validate(state["canonical"])
        source = cat.source_docs.get(state["source_doc_id"]) or {}
        ctx = MatchContext(
            graph_id=GRAPH_ID,
            fiscal_class=source.get("fiscal_class"),
            our_role=_our_role(doc),
            is_storno=doc.is_storno,
            axes=state.get("axes") or {},
            day=doc.date,
        )
        cands = match_articole(cat, ctx, allow_draft=deps.allow_draft)
        seen = doc.model_dump(exclude={"job_id", "tenant", "source", "jev"})
        cui = job.tenant.cui
        deps.observe("jev_v3_classify", {"tenant_cui": cui, "document": seen}, cui)
        if len(cands) > 1:
            deps.observe(
                "jev_flux", {"tenant_cui": cui, "document": seen, "candidates": cands}, cui
            )
        if len(cands) == 1:
            articol_id = cands[0]
        else:
            allowed = cands or list(cat.graphs[GRAPH_ID].get("allowed_flux") or [])
            articol_id = ask(
                "define_articol",
                {"job_id": job.job_id, "candidates": cands},
                DefineArticolResume,
                lambda a: (
                    None
                    if a.articol_id in allowed
                    else f"articol {a.articol_id!r} is not a candidate on {GRAPH_ID}"
                ),
            ).articol_id
        row = cat.articol(articol_id)
        deps.jobs.update(
            job.job_id,
            status="bound",
            articol_id=articol_id,
            schema_version=str(row.get("schema_version", "1")),
        )
        return {"articol_id": articol_id, "status": "bound"}

    def reconcile_pre(state: IngestState) -> IngestState:
        job = deps.jobs.update(state["job_id"], status="reconcile_pre")
        source = cat.source_docs.get(state["source_doc_id"]) or {}
        pre = deps.pre_check(
            job,
            CanonicalDocument.model_validate(state["canonical"]),
            fiscal_class=source.get("fiscal_class"),
            axes=state.get("axes") or {},
        )
        if pre.verdict == "already_posted":
            deps.jobs.update(job.job_id, status="already_in_sink")
            return {"status": "already_in_sink", "pre": pre.model_dump()}
        if pre.verdict != "absent":
            deps.jobs.update(
                job.job_id,
                status="needs_human",
                error=f"reconcile_pre: {pre.verdict}: {pre.reason}",
            )
            return {"status": "needs_human", "pre": pre.model_dump()}
        return {"status": "reconcile_pre", "pre": pre.model_dump()}

    def judge(state: IngestState) -> IngestState:
        doc = CanonicalDocument.model_validate(state["canonical"])
        try:
            verdict = deps.judge(doc, cat.articol(state["articol_id"]))
        except Exception as exc:  # fail closed: a person is asked
            verdict = unjudged(f"judge failed: {type(exc).__name__}: {exc}")
        if not isinstance(verdict, dict):
            verdict = unjudged("judge gave no verdict object")
        return {"judge": verdict}

    def approve(state: IngestState) -> IngestState:
        job = deps.jobs.get(state["job_id"])
        doc = CanonicalDocument.model_validate(state["canonical"])
        articol = cat.articol(state["articol_id"])
        verdict = state.get("judge") or unjudged("no verdict on the thread")
        if _needs_question(deps, job, articol, verdict):

            def check(answer: V3ApproveResume) -> str | None:
                if answer.decision == "edit":
                    if not answer.edit:
                        return "decision 'edit' needs an edit object"
                    try:
                        _edited(doc, answer.edit)
                    except ValidationError as exc:
                        return f"edit does not validate: {exc.errors(include_url=False)}"
                elif answer.edit:
                    return "edit is only allowed with decision 'edit'"
                return None

            question = {
                "job_id": job.job_id,
                "articol_id": state["articol_id"],
                "judge": verdict,
                "document": doc.model_dump(),
                **_proposal(deps, doc),
            }
            deps.observe_question("v3_approve", question, job.tenant.cui)
            answer = ask("v3_approve", question, V3ApproveResume, check)
            if answer.decision == "reject":
                deps.jobs.update(job.job_id, status="rejected")
                return {"status": "rejected"}
            if answer.decision == "edit":
                doc = _edited(doc, answer.edit)
        deps.jobs.update(job.job_id, status="approved")
        return {"status": "approved", "canonical": doc.model_dump()}

    def package(state: IngestState) -> IngestState:
        job = deps.jobs.get(state["job_id"])
        doc = CanonicalDocument.model_validate(state["canonical"])
        book = deps.book_of_record(job.tenant.cui)
        if book != "saga":  # LAW L8: nothing is written to NextUp; gating only, no PreFile
            error = f"book of record is {book}: no PreFile (LAW L8); post it there"
            deps.jobs.update(job.job_id, status="needs_human", error=error)
            return {"status": "needs_human", "error": error}
        declared = cat.articol(state["articol_id"]).get("write_modules") or []
        mouths = [m for m in declared if mouth_doc_class(m) == doc.doc_class]
        if len(mouths) != 1:
            error = f"no single rendered mouth for {doc.doc_class!r} among {declared}"
            deps.jobs.update(job.job_id, status="needs_human", error=error)
            return {"status": "needs_human", "error": error}
        failed = prefile_failures(cat, pre_verdict=(state.get("pre") or {}).get("verdict"))
        if deps.period_filed(job.tenant.cui, doc.period):
            failed.append(f"{doc.period} has a filing receipt: no new package for it")
        if failed:  # ArticoleControls prefile layer: hard failures refuse the package
            error = "prefile controls: " + "; ".join(failed)
            deps.jobs.update(job.job_id, status="needs_human", error=error)
            return {"status": "needs_human", "error": error}
        try:
            row = deps.package(job, doc, cat.write_modules[mouths[0]])
        except SagaXmlError as exc:
            deps.jobs.update(job.job_id, status="needs_human", error=str(exc))
            return {"status": "needs_human", "error": str(exc)}
        return {"status": "packaged", "export_key": row.export_key}

    def wait_validare(state: IngestState) -> IngestState:
        job_id = state["job_id"]

        def check(answer: WaitValidareResume) -> str | None:
            job = deps.jobs.get(job_id)
            if job.status != "wait_validare":
                return f"job is {job.status}, not imported into SAGA yet"
            if not answer.validated:
                return "saga_doc_key is only given with validated" if answer.saga_doc_key else None
            if not answer.saga_doc_key:
                return "validated needs the saga_doc_key"
            if not deps.snapshot_validated(job.tenant.cui, answer.saga_doc_key):
                return f"no SAGA snapshot shows {answer.saga_doc_key!r} validated"
            return None

        answer = ask(
            "wait_validare",
            {"job_id": job_id, "export_key": state.get("export_key")},
            WaitValidareResume,
            check,
        )
        if answer.validated:
            return {"status": "validated", "saga_doc_key": answer.saga_doc_key}
        deps.jobs.update(job_id, status="reopened")
        return {"status": "reopened"}

    def intent_check(state: IngestState) -> IngestState:
        job = deps.jobs.get(state["job_id"])
        key = state["saga_doc_key"]
        doc = CanonicalDocument.model_validate(state["canonical"])
        posted = deps.posted_doc(job.tenant.cui, key)
        diffs = intent_diffs(doc, posted) if posted else ["SAGA shows no document for the key"]
        if diffs:
            deps.jobs.update(
                job.job_id,
                status="needs_human",
                error="intent_check: " + "; ".join(diffs),
                saga={"saga_doc_key": key},
            )
            return {"status": "needs_human"}
        deps.jobs.update(job.job_id, status="acked", saga={"saga_doc_key": key})
        return {"status": "acked"}

    def after_wait(state: IngestState) -> str:
        return "intent_check" if state["status"] == "validated" else END

    def after_package(state: IngestState) -> str:
        return "wait_validare" if state["status"] == "packaged" else END

    def after_pre(state: IngestState) -> str:
        return "judge" if state["status"] == "reconcile_pre" else END

    def after_approve(state: IngestState) -> str:
        return "package" if state["status"] == "approved" else END

    g = StateGraph(IngestState)
    g.add_node("bind", bind)
    g.add_node("reconcile_pre", reconcile_pre)
    g.add_node("judge", judge)
    g.add_node("approve", approve)
    g.add_node("package", package)
    g.add_node("wait_validare", wait_validare)
    g.add_node("intent_check", intent_check)
    g.add_edge(START, "bind")
    g.add_edge("bind", "reconcile_pre")
    g.add_conditional_edges("reconcile_pre", after_pre, ["judge", END])
    g.add_edge("judge", "approve")
    g.add_conditional_edges("approve", after_approve, ["package", END])
    g.add_conditional_edges("package", after_package, ["wait_validare", END])
    g.add_conditional_edges("wait_validare", after_wait, ["intent_check", END])
    g.add_edge("intent_check", END)
    return g.compile(checkpointer=checkpointer)
