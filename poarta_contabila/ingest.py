"""ingest_source_doc (WP-04): a Job walks its articol de cale up to `packaged`.

    bind → reconcile_pre → approve (v3_approve) → package

- **bind**: ArticoleFlux.matches on stored fields. One survivor binds; none or a tie asks
  ``define_articol`` (the answer must be a real articol on this graph).
- **reconcile_pre**: already in the books → ``already_in_sink`` and stop; ambiguous →
  ``needs_human`` and stop. The real check is WP-05; here it is an injected function.
- **approve**: the articol's HITL policy (``always`` / ``first_n`` / ``never_if_risk_low``)
  plus the Jev judge decide whether a person must answer ``v3_approve``. Nothing touches
  SAGA before this answer (no side effect sits before ``interrupt()``).
- **package**: render through the articol's invoice WriteModule and write the XML once per
  ``export_key``; a replay of the node writes nothing.

Edges read ``state["status"]`` only. Runs on ``job:`` threads only.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from poarta_contabila.catalog import Catalog
from poarta_contabila.flux import MatchContext, match_articole
from poarta_contabila.hitl import ask
from poarta_contabila.packages import BlobStore, PackageRow, PackageStore, write_once
from poarta_contabila.sinks.saga_xml import SagaXmlError, export_key, render_invoice
from poarta_contabila.types import CanonicalDocument, Closed, JobRecord, Slug, WriteModule

GRAPH_ID = "ingest_source_doc"
THREAD_PREFIX = "job:"
_INVOICE_MOUTHS = ("iesire_factura_xml", "intrare_factura_xml")
_OUTBOUND = {"iesire", "storn_iesire"}
_INBOUND = {"intrare", "storn_intrare"}

PreVerdict = Literal["absent", "already_posted", "ambiguous"]


class DefineArticolResume(Closed):
    articol_id: Slug


class V3ApproveResume(Closed):
    decision: Literal["approve", "reject", "edit"]
    edit: dict[str, Any] | None = None


@dataclass
class IngestDeps:
    catalog: Catalog
    jobs: Any  # InMemoryJobStore | PostgresJobStore
    packages: PackageStore
    blobs: BlobStore
    pre_check: Callable[[JobRecord, CanonicalDocument], PreVerdict]
    judge: Callable[[CanonicalDocument, dict], dict]
    tenant_name: Callable[[str], str]
    allow_draft: bool = True

    def package(self, job: JobRecord, doc: CanonicalDocument, module: WriteModule) -> PackageRow:
        """Render and write once; set the job to `packaged`. Safe to replay."""
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
    error: str


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


def _our_role(doc: CanonicalDocument) -> str | None:
    if doc.doc_class in _OUTBOUND:
        return "outbound"
    if doc.doc_class in _INBOUND:
        return "inbound"
    return None


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
    for kind in ("define_articol", "v3_approve"):
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
        verdict = deps.pre_check(job, CanonicalDocument.model_validate(state["canonical"]))
        if verdict == "already_posted":
            deps.jobs.update(job.job_id, status="already_in_sink")
            return {"status": "already_in_sink"}
        if verdict != "absent":
            deps.jobs.update(job.job_id, status="needs_human", error=f"reconcile_pre: {verdict}")
            return {"status": "needs_human"}
        return {"status": "reconcile_pre"}

    def approve(state: IngestState) -> IngestState:
        job = deps.jobs.get(state["job_id"])
        doc = CanonicalDocument.model_validate(state["canonical"])
        articol = cat.articol(state["articol_id"])
        verdict = deps.judge(doc, articol)
        if _needs_question(deps, job, articol, verdict):

            def check(answer: V3ApproveResume) -> str | None:
                if answer.decision == "edit":
                    if not answer.edit:
                        return "decision 'edit' needs an edit object"
                    try:
                        CanonicalDocument.model_validate({**doc.model_dump(), **answer.edit})
                    except ValidationError as exc:
                        return f"edit does not validate: {exc.errors(include_url=False)}"
                elif answer.edit:
                    return "edit is only allowed with decision 'edit'"
                return None

            answer = ask(
                "v3_approve",
                {
                    "job_id": job.job_id,
                    "articol_id": state["articol_id"],
                    "judge": verdict,
                    "document": doc.model_dump(),
                },
                V3ApproveResume,
                check,
            )
            if answer.decision == "reject":
                deps.jobs.update(job.job_id, status="rejected")
                return {"status": "rejected"}
            if answer.decision == "edit":
                doc = CanonicalDocument.model_validate({**doc.model_dump(), **answer.edit})
        deps.jobs.update(job.job_id, status="approved")
        return {"status": "approved", "canonical": doc.model_dump()}

    def package(state: IngestState) -> IngestState:
        job = deps.jobs.get(state["job_id"])
        doc = CanonicalDocument.model_validate(state["canonical"])
        mouths = [
            m
            for m in cat.articol(state["articol_id"]).get("write_modules") or []
            if m in _INVOICE_MOUTHS
        ]
        if len(mouths) != 1:
            deps.jobs.update(job.job_id, status="needs_human", error="no single invoice mouth")
            return {"status": "needs_human", "error": "no single invoice mouth"}
        try:
            row = deps.package(job, doc, cat.write_modules[mouths[0]])
        except SagaXmlError as exc:
            deps.jobs.update(job.job_id, status="needs_human", error=str(exc))
            return {"status": "needs_human", "error": str(exc)}
        return {"status": "packaged", "export_key": row.export_key}

    def after_pre(state: IngestState) -> str:
        return "approve" if state["status"] == "reconcile_pre" else END

    def after_approve(state: IngestState) -> str:
        return "package" if state["status"] == "approved" else END

    g = StateGraph(IngestState)
    g.add_node("bind", bind)
    g.add_node("reconcile_pre", reconcile_pre)
    g.add_node("approve", approve)
    g.add_node("package", package)
    g.add_edge(START, "bind")
    g.add_edge("bind", "reconcile_pre")
    g.add_conditional_edges("reconcile_pre", after_pre, ["approve", END])
    g.add_conditional_edges("approve", after_approve, ["package", END])
    g.add_edge("package", END)
    return g.compile(checkpointer=checkpointer)
