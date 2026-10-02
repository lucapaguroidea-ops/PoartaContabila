"""The wired gate: stores, bucket, checkpointer, the ingest graph and the agent service.

``build_runtime`` takes every part explicitly (tests pass in-memory ones);
``runtime_from_env`` builds the production one from ``DATABASE_URL`` and ``S3_*``.
Parts not wired fail closed: without Jev (``JEV_BASE_URL`` + ``JEV_API_KEY``) every document
is asked (``v3_approve``) and the close gets no Layer 2 suggestion; a tenant without an
uploaded journal export gets ``need_rj_export``.
"""

from __future__ import annotations

import hashlib
import io
import os
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from langgraph.types import Command

from poarta_contabila.agent import AgentService
from poarta_contabila.answers import InMemoryAnswerLog
from poarta_contabila.answers import record as record_answer
from poarta_contabila.catalog import Catalog
from poarta_contabila.close import CloseDeps, InMemoryCloseStore, build_close_graph
from poarta_contabila.codit import Codit, CoditInput, write_codit
from poarta_contabila.extract.contract import (
    Extraction,
    InMemoryExtractStore,
    read_extraction,
    write_extraction,
)
from poarta_contabila.extract.document_ai import DocumentAiError, shows_iban
from poarta_contabila.extract.statement import (
    StatementError,
    StatementMeta,
    line_source_hash,
    parse_statement,
    statement_line_document,
)
from poarta_contabila.extract.ubl import UblError, parse_ubl, read_spv_zip, to_canonical
from poarta_contabila.filings import due_filings
from poarta_contabila.filings import views as filing_views
from poarta_contabila.ingest import IngestDeps, build_ingest_graph, start_payload
from poarta_contabila.jev import (
    InMemoryJevCache,
    Jev,
    make_judge,
    make_recon_review,
    make_v2,
    role_pin,
    role_transport,
)
from poarta_contabila.model_roles import InMemoryModelCallStore, ModelGateway, brief
from poarta_contabila.packages import BlobStore, PackageStore
from poarta_contabila.period_diff import ExpectedJob, build_period_diff, can_file
from poarta_contabila.recon.post import PostResult, how_check
from poarta_contabila.recon.pre import PreResult, ReconStore, make_pre_check, pre_profile
from poarta_contabila.recon.settle import (
    SETTLES,
    InvoiceJob,
    SettlementProposal,
    propose_settlement,
    settle_key,
)
from poarta_contabila.reconcile import PostDeps, ReconDeps, WaitingJob, build_reconcile_graph
from poarta_contabila.registry import (
    ExportKind,
    Product,
    Tenant,
    check_export,
    export_row,
    rj_eye,
    witnesses_provider,
)
from poarta_contabila.triage import Pack, build_triage_graph, decide_emit
from poarta_contabila.types import CanonicalDocument, JobRecord, SourceRef, TenantRef

SETTLE_MONTHS = 3
"""A bank line looks for the invoice it settles in its own month and the two before it."""


def _months_back(period: str, n: int) -> list[str]:
    year, month = int(period[:4]), int(period[5:])
    out = []
    for _ in range(n):
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return out


class IngestRefused(ValueError):
    """The upload cannot become a Job; the message says which gate."""


@dataclass
class Runtime:
    catalog: Catalog
    jobs: Any
    packages: PackageStore
    blobs: BlobStore
    registry: Any
    recon: ReconStore | None
    agent_store: Any
    checkpointer: Any
    periods: Any = None  # InMemoryPeriodStore | PostgresPeriodStore
    rules: Any = None  # InMemoryRuleStore | PostgresRuleStore
    closes: Any = None  # InMemoryCloseStore | PostgresCloseStore
    codits: Any = None  # InMemoryCoditStore | PostgresCoditStore
    filings: Any = None  # InMemoryFilingStore | PostgresFilingStore
    jev: Any = None  # jev.Jev; None = not wired (fail closed)
    statement_reader: Any = None  # (pdf, *, tenant_cui) -> Extraction; DocumentAiReader
    extracts: Any = None  # InMemoryExtractStore | PostgresExtractStore
    model_calls: Any = None  # InMemoryModelCallStore | PostgresModelCallStore
    model_mode: str = "off"  # MODEL_CALLS: off | dry (record, send nothing)
    answers: Any = None  # InMemoryAnswerLog | PostgresAnswerLog (WP-33)

    def __post_init__(self) -> None:
        if self.model_calls is None:
            self.model_calls = InMemoryModelCallStore()
        if self.answers is None:
            self.answers = InMemoryAnswerLog()
        if self.model_mode not in ("off", "dry"):
            self.model_mode = "off"  # an unknown mode calls nothing
        if self.jev is None and self.model_mode == "dry":
            self.jev = Jev(
                transport=role_transport(
                    self.catalog.model_roles,
                    mode="dry",
                    calls=self.model_calls,
                    synthetic=self._synthetic,
                ),
                cache=InMemoryJevCache(),
                pin=role_pin(self.catalog.model_roles),
            )
        self.gateway = ModelGateway(
            roles=self.catalog.model_roles,
            calls=self.model_calls,
            mode=self.model_mode,
            synthetic=self._synthetic,
        )
        self.deps = IngestDeps(
            catalog=self.catalog,
            jobs=self.jobs,
            packages=self.packages,
            blobs=self.blobs,
            pre_check=make_pre_check(
                self.catalog, witnesses_provider(self.registry, self.blobs), store=self.recon
            ),
            judge=make_judge(self.jev),
            tenant_name=self._tenant_name,
            observe=self.gateway.observe,
            observe_question=self.gateway.observe_question,
        )
        self.ingest = build_ingest_graph(self.deps, checkpointer=self.checkpointer)
        self.agent = AgentService(
            catalog=self.catalog,
            jobs=self.jobs,
            packages=self.packages,
            blobs=self.blobs,
            store=self.agent_store,
            resume=lambda job_id, payload: self.resume(job_id, payload),
            canonical=self.canonical,
        )
        self.deps.snapshot_validated = self.agent.snapshot_validated
        self.deps.period_filed = lambda cui, period: (
            self.filings is not None and self.filings.has_receipt(cui, period)
        )
        if self.closes is None:
            self.closes = InMemoryCloseStore()
        if self.extracts is None:
            self.extracts = InMemoryExtractStore()
        self.close = build_close_graph(
            CloseDeps(
                catalog=self.catalog,
                store=self.closes,
                expected=self.expected,
                eye=self._eye,
                rules=self.rules,
                period_store=self.periods,
                jev_v2=make_v2(self.jev, self.axes, lambda axes: due_filings(self.catalog, axes)),
                codit=lambda cui, period: (
                    self.codits.get(cui, period) if self.codits is not None else None
                ),
                codit_put=self.codits.put if self.codits is not None else None,
                observe_question=self.gateway.observe_question,
                recon_open=lambda cui, period: (
                    [w.job.job_id for w in self.recon_waiting(cui, period)]
                    + self.post_open(cui, period)
                ),
            ),
            checkpointer=self.checkpointer,
        )
        self.deps.posted_doc = self.agent.posted_doc
        self.deps.treasury_account = self._treasury_account
        self.reconcile = build_reconcile_graph(
            ReconDeps(
                catalog=self.catalog,
                waiting=self.recon_waiting,
                recheck=lambda w: self.deps.pre_check(
                    w.job, w.doc, fiscal_class=w.fiscal_class, axes=w.axes
                ),
                settle=self._settle_pre,
                export_months=self._rj_export_months,
                review=make_recon_review(self.jev),
                observe_question=self.gateway.observe_question,
                post=PostDeps(
                    waiting=lambda cui, period: self.post_waiting(cui, period),
                    check=lambda w: self.post_check(w),
                    known=self._post_known,
                    settle=self._settle_post,
                ),
            ),
            checkpointer=self.checkpointer,
        )
        self.deps.settlement = self.settlement
        self.triage = build_triage_graph(self.catalog, self.jobs, checkpointer=self.checkpointer)

    # -- helpers --

    def _tenant_name(self, cui: str) -> str:
        tenant = self.registry.tenant(cui)
        if tenant is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        return tenant.name

    def _synthetic(self, cui: str | None) -> bool:
        tenant = self.registry.tenant(cui) if cui else None
        return tenant is not None and tenant.data_class == "synthetic"

    def model_roles_view(self) -> list[dict[str, Any]]:
        """Each model role: where it acts, its pinned model, and whether it could be called.

        Key variables are reported as set or not, never their values.
        """
        out = []
        for role in self.catalog.model_roles.values():
            out.append(
                {
                    **role.model_dump(mode="json"),
                    "key_env": role.key_env,
                    "key_set": bool(os.environ.get(role.key_env)),
                    "mode": self.model_mode,
                    "callable_in_dry_run": role.status == "wired" and role.model is not None,
                    "card_hash": role.card_hash,
                    "brief": brief(role),
                }
            )
        return out

    def _treasury_account(self, cui: str, iban: str) -> str | None:
        tenant = self.registry.tenant(cui)
        return tenant.treasury_account(iban) if tenant else None

    @staticmethod
    def _cfg(job_id: str) -> dict:
        return {"configurable": {"thread_id": f"job:{job_id}"}}

    def canonical(self, job_id: str) -> CanonicalDocument:
        values = self.ingest.get_state(self._cfg(job_id)).values
        return CanonicalDocument.model_validate(values["canonical"])

    def view(self, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(job_id)
        tasks = self.ingest.get_state(self._cfg(job_id)).tasks
        question = next((i.value for t in tasks for i in t.interrupts), None)
        return {"job": job.model_dump(), "question": question}

    def resume(self, job_id: str, payload: Any, operator: str | None = None) -> dict[str, Any]:
        job = self.jobs.get(job_id)  # KeyError for an unknown job
        self._answer(
            self.ingest, self._cfg(job_id), "ingest_source_doc", job.tenant.cui, payload, operator
        )
        return self.view(job_id)

    # -- the answer log (WP-33) --

    @staticmethod
    def _waiting(graph: Any, cfg: dict) -> dict[str, Any] | None:
        tasks = graph.get_state(cfg).tasks
        return next((i.value for t in tasks for i in t.interrupts), None)

    def _answer(
        self,
        graph: Any,
        cfg: dict,
        graph_id: str,
        cui: str | None,
        payload: Any,
        operator: str | None,
    ) -> None:
        """Resume *graph* with a person's answer and log it, whatever became of it.

        With no question waiting the graph is not touched: an answer to nothing changes
        nothing (it is logged as ``no_question``).
        """
        before = self._waiting(graph, cfg)
        if before is not None:
            graph.invoke(Command(resume=payload), cfg)
        self.answers.add(
            record_answer(
                graph_id=graph_id,
                thread_id=cfg["configurable"]["thread_id"],
                tenant_cui=cui,
                before=before,
                after=self._waiting(graph, cfg),
                answer=payload,
                operator=operator,
            )
        )

    # -- reconcile_sink (WP-23) --

    def recon_waiting(self, cui: str, period: str) -> list[WaitingJob]:
        """The period's jobs whose ingest thread ended at an undecided PRE check."""
        out = []
        for job in self.jobs.for_period(cui, period):
            if job.status != "needs_human":
                continue
            state = self.ingest.get_state(self._cfg(job.job_id))
            pre = state.values.get("pre") or {}
            if state.tasks or state.values.get("status") != "needs_human":
                continue
            if pre.get("verdict") != "ambiguous" or "canonical" not in state.values:
                continue
            source = self.catalog.source_docs.get(state.values.get("source_doc_id")) or {}
            out.append(
                WaitingJob(
                    job=job,
                    doc=CanonicalDocument.model_validate(state.values["canonical"]),
                    fiscal_class=source.get("fiscal_class"),
                    axes=dict(state.values.get("axes") or {}),
                )
            )
        return sorted(out, key=lambda w: (w.doc.date, w.job.job_id))

    def _thread_job(self, job: JobRecord) -> WaitingJob | None:
        values = self.ingest.get_state(self._cfg(job.job_id)).values
        if "canonical" not in values:
            return None
        source = self.catalog.source_docs.get(values.get("source_doc_id")) or {}
        return WaitingJob(
            job=job,
            doc=CanonicalDocument.model_validate(values["canonical"]),
            fiscal_class=source.get("fiscal_class"),
            axes=dict(values.get("axes") or {}),
        )

    def post_waiting(self, cui: str, period: str) -> list[WaitingJob]:
        """The period's acked jobs: SAGA shows them validated, POST checks how (WP-27)."""
        out = [
            w
            for job in self.jobs.for_period(cui, period)
            if job.status == "acked" and (w := self._thread_job(job)) is not None
        ]
        return sorted(out, key=lambda w: (w.doc.date, w.job.job_id))

    def post_check(self, w: WaitingJob) -> PostResult:
        profile = pre_profile(
            self.catalog, w.doc, fiscal_class=w.fiscal_class, axes=w.axes, stage="post"
        )
        articol = self.catalog.articole.get(w.job.articol_id or "") or {}
        eye = rj_eye(self.registry, self.blobs, w.job.tenant.cui)
        return how_check(w.doc, articol, profile, eye, w.job.tenant.cui)

    def _post_known(self, job_id: str, snapshot_id: str) -> bool:
        if self.recon is None:
            return False
        return any(
            self.recon.get(job_id, "post", sid) is not None
            for sid in (snapshot_id, f"{snapshot_id}:person")
        )

    def _settle_post(self, w: WaitingJob, result: PostResult) -> None:
        if self.recon is not None:
            self.recon.put_once(w.job.job_id, "post", result)

    def post_open(self, cui: str, period: str) -> list[str]:
        """Acked jobs whose posting is not settled: unchecked (no journal), an unanswered
        mismatch, or a requested storno SAGA does not show yet."""
        out = []
        for w in self.post_waiting(cui, period):
            res = self.post_check(w)
            if res.verdict == "how_ok":
                continue
            answer = (
                self.recon.get(w.job.job_id, "post", f"{res.snapshot_id}:person")
                if self.recon is not None and res.verdict == "how_mismatch"
                else None
            )
            if answer is None or str(answer.get("reason", "")).startswith("person: storno"):
                out.append(w.job.job_id)
        return out

    def _settle_pre(self, w: WaitingJob, result: PreResult) -> None:
        """Hand a final PRE verdict back to the job's own thread (glue = job id)."""
        if self.recon is not None:
            result = self.recon.put_once(w.job.job_id, "pre", result)
        cfg = self._cfg(w.job.job_id)
        if result.verdict == "already_posted":
            self.jobs.update(w.job.job_id, status="already_in_sink", error=None)
            self.ingest.update_state(
                cfg,
                {"status": "already_in_sink", "pre": result.model_dump()},
                as_node="reconcile_pre",
            )
            return
        if result.verdict != "absent":
            raise ValueError(f"only a decided verdict is handed back, not {result.verdict!r}")
        self.jobs.update(w.job.job_id, status="reconcile_pre", error=None)
        self.ingest.update_state(
            cfg, {"status": "reconcile_pre", "pre": result.model_dump()}, as_node="reconcile_pre"
        )
        self.ingest.invoke(None, cfg)  # judge → v3_approve, as if PRE had said absent

    def _rj_export_months(self, cui: str, export_id: str) -> list[str] | None:
        row = self.registry.latest_export(cui, "rj")
        return list(row.periods) if row is not None and row.export_id == export_id else None

    @staticmethod
    def _recon_cfg(cui: str, period: str) -> dict:
        return {"configurable": {"thread_id": f"recon:{cui}:{period}"}}

    def recon_view(self, cui: str, period: str) -> dict[str, Any]:
        state = self.reconcile.get_state(self._recon_cfg(cui, period))
        question = next((i.value for t in state.tasks for i in t.interrupts), None)
        return {
            "question": question,
            "settled": state.values.get("settled") or [],
            "waiting": [w.job.job_id for w in self.recon_waiting(cui, period)],
            "post_open": self.post_open(cui, period),
        }

    def start_recon(self, cui: str, period: str) -> dict[str, Any]:
        """One pass over the period's PRE questions; a waiting question is shown, not redone."""
        if self.registry.tenant(cui) is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        cfg = self._recon_cfg(cui, period)
        if self.reconcile.get_state(cfg).tasks:
            return self.recon_view(cui, period)
        self.reconcile.invoke({"cui": cui, "period": period, "settled": []}, cfg)
        return self.recon_view(cui, period)

    def resume_recon(
        self, cui: str, period: str, payload: Any, operator: str | None = None
    ) -> dict[str, Any]:
        cfg = self._recon_cfg(cui, period)
        self._answer(self.reconcile, cfg, "reconcile_sink", cui, payload, operator)
        return self.recon_view(cui, period)

    # -- period --

    def expected(self, cui: str, period: str) -> list[ExpectedJob]:
        """The month's jobs with the documents their threads carry."""
        out = []
        for job in self.jobs.for_period(cui, period):
            values = self.ingest.get_state(self._cfg(job.job_id)).values
            if "canonical" in values:
                doc = CanonicalDocument.model_validate(values["canonical"])
                out.append(ExpectedJob(job=job, doc=doc))
        return out

    def settlement(self, line: CanonicalDocument) -> SettlementProposal:
        """The invoices an unbound bank line could settle (WP-22, WP-30), from this tenant's
        invoice Jobs and the books' journals in the line's month and the two before it, less
        what other bound bank lines already paid on each."""
        cui = line.tenant.cui
        periods = _months_back(line.period, SETTLE_MONTHS)
        jobs = [ej for p in periods for ej in self.expected(cui, p)]
        invoices = [
            InvoiceJob(job_id=ej.job.job_id, doc=ej.doc)
            for ej in jobs
            if ej.doc.doc_class in SETTLES.values() and ej.job.status not in ("rejected", "failed")
        ]
        books = []
        for p in periods:
            eye = self._eye(cui, p)
            if eye.covers(cui, p):
                books.extend(eye.documents(cui, p))
        bound = [
            ej.doc
            for ej in jobs
            if ej.doc.doc_class in SETTLES
            and ej.doc.job_id != line.job_id
            and ej.doc.partner.cui
            and ej.job.status not in ("rejected", "failed")
        ]
        paid: dict[tuple[str, str], Decimal] = {}  # what bound lines paid per invoice (WP-30)
        for d in bound:
            if d.maps.get("factura_numar"):
                key = settle_key(d.partner.cui, d.maps["factura_numar"])
                paid[key] = paid.get(key, Decimal(0)) + Decimal(d.totals.gross)
        return propose_settlement(line, invoices, books, paid=paid)

    def _eye(self, cui: str, period: str):
        probe = JobRecord(
            job_id="period",
            tenant=TenantRef(cui=cui, saga_firm_folder="-"),
            period=period,
            status="bound",
        )
        return witnesses_provider(self.registry, self.blobs)(probe).eye

    # -- CO.DiT --

    def axes(self, cui: str, period: str, fallback: dict[str, str] | None = None) -> dict:
        """The period's CO.DiT axes; *fallback* (explicit operator input) only without one."""
        doc = self.codits.get(cui, period) if self.codits is not None else None
        return doc.derive() if doc is not None else dict(fallback or {})

    def put_codit(self, cui: str, period: str, data: CoditInput) -> Codit:
        if self.codits is None:
            raise IngestRefused("CO.DiT store not wired")
        if self.registry.tenant(cui) is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        previous = self.codits.get(cui, period)
        run = self.closes.get(cui, period) if self.closes is not None else None
        closed = run is not None and run.status in ("filed", "v4_done")
        if closed and previous is not None:
            raise IngestRefused(f"{period} is filed; a filed period's CO.DiT is not rewritten")
        doc = write_codit(self.catalog, cui, period, data, previous=previous, closed=closed)
        self.codits.put(doc)
        return doc

    # -- bank statements (WP-13) --

    def read_statement(self, tenant: Tenant, period: str, pdf: bytes) -> tuple[Extraction, str]:
        """The extract contract for a statement PDF (WP-21): read once per
        ``(source_hash, document_ai)``, reused after; returns it with the PDF's bucket key."""
        cui = tenant.cui
        source_hash = hashlib.sha256(pdf).hexdigest()
        row = self.extracts.get(source_hash, "document_ai")
        if row is not None:
            if not str(row["prefix"]).startswith(f"tenants/{cui}/"):
                raise IngestRefused("this PDF was read for another tenant")
            return read_extraction(self.blobs, row["prefix"]), f"{row['prefix']}/statement.pdf"
        if self.statement_reader is None:
            raise IngestRefused(
                "no statement reader is wired (DOCUMENT_AI_PROCESSOR): send the extract tables"
            )
        try:
            extraction = self.statement_reader(pdf, tenant_cui=cui)
        except DocumentAiError as exc:
            raise IngestRefused(str(exc)) from exc
        prefix = f"tenants/{cui}/{tenant.punct}/{period}/extras/source/{source_hash}"
        self.blobs.put(f"{prefix}/statement.pdf", pdf)
        write_extraction(self.blobs, prefix, extraction)
        self.extracts.put(extraction.meta, prefix)  # the row after the files it proves
        return extraction, f"{prefix}/statement.pdf"

    def ingest_statement(
        self,
        cui: str,
        meta: StatementMeta,
        tables: list[dict[str, Any]] | None,
        pdf: bytes,
    ) -> dict[str, Any]:
        """A PDF statement → a pack and one Job per movement line.

        The movement tables come with the upload or, when none are sent, from the statement
        reader (Document AI), which must also show the tenant's CUI and the header's IBAN.
        """
        tenant: Tenant | None = self.registry.tenant(cui)
        if tenant is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        if not pdf.startswith(b"%PDF"):
            raise IngestRefused("the statement source must be the bank's PDF")
        period = meta.statement_date[:7]
        pdf_key = None
        self.gateway.observe(  # shadow: what Gemini would be given (the file by fingerprint)
            "ocr_extract",
            {
                "tenant_cui": cui,
                "file": {
                    "sha256": hashlib.sha256(pdf).hexdigest(),
                    "bytes": len(pdf),
                    "content_type": "application/pdf",
                },
                "header": meta.model_dump(),
            },
            cui,
        )
        if tables is None:
            extraction, pdf_key = self.read_statement(tenant, period, pdf)
            if not extraction.meta.identity_ok:
                raise IngestRefused(f"stmt_no_identity: the statement does not show CUI {cui}")
            if not shows_iban(extraction.markdown, meta.iban):
                raise IngestRefused(f"the statement does not show the IBAN {meta.iban}")
            tables = extraction.tables
        try:
            statement = parse_statement(tables, meta, cui)
        except StatementError as exc:
            raise IngestRefused(str(exc)) from exc
        base = f"tenants/{cui}/{tenant.punct}/{period}/extras/{statement.statement_id}"
        if pdf_key is None:
            pdf_key = f"{base}/statement.pdf"
            self.blobs.put(pdf_key, pdf)
        self.blobs.put(f"{base}/statement.json", statement.model_dump_json().encode())
        jobs = []
        for line in statement.lines:
            source_hash = line_source_hash(statement.statement_id, line.seq)
            pack = Pack(
                tenant_cui=cui,
                saga_firm_folder=tenant.saga_firm_folder,
                punct=tenant.punct,
                period=line.date[:7],
                source_hash=source_hash,
                source_doc_id="extras_statement_pdf",
                kinds=["pdf"],
                our_role="n/a",
                identity_ok=True,  # the holder CUI was checked against the tenant
            )
            decision = decide_emit(self.catalog, pack)
            if not decision.emit:
                raise IngestRefused(f"line {line.seq}: emit gates failed: {decision.failed}")
            result = self.jobs.emit(pack, decision)
            if result.created:
                doc = statement_line_document(
                    statement, line, job=result.job, bucket_key=pdf_key, source_hash=source_hash
                )
                self.ingest.invoke(
                    start_payload(
                        result.job,
                        doc,
                        source_doc_id="extras_statement_pdf",
                        axes=self.axes(cui, doc.period),
                    ),
                    self._cfg(result.job.job_id),
                )
            jobs.append(
                {"seq": line.seq, "created": result.created, **self.view(result.job.job_id)}
            )
        return {"statement_id": statement.statement_id, "lines": len(statement.lines), "jobs": jobs}

    # -- filings --

    def open_filings(self, cui: str, period: str) -> list[dict[str, Any]]:
        """Open the items the period's CO.DiT makes due (idempotent) and list them."""
        if self.filings is None:
            raise IngestRefused("filing store not wired")
        doc = self.codits.get(cui, period) if self.codits is not None else None
        if doc is None:
            raise IngestRefused(f"no CO.DiT for {period}: nothing is assumed due")
        for row in due_filings(self.catalog, doc.derive()):
            self.filings.open(cui, period, row["filing_id"])
        return self.filings_view(cui, period)

    def filings_view(self, cui: str, period: str) -> list[dict[str, Any]]:
        if self.filings is None:
            raise IngestRefused("filing store not wired")
        items = self.filings.items(cui, period)
        controls = (
            {c["control_id"]: c["status"] for c in self.period_diff(cui, period)["controls"]}
            if items
            else {}
        )
        return [v.model_dump() for v in filing_views(self.catalog, cui, period, items, controls)]

    def filing_receipt(
        self, cui: str, period: str, filing_id: str, data: bytes, filename: str, by: str
    ) -> list[dict[str, Any]]:
        """Store the receipt artefact (the only thing that closes an item)."""
        if self.filings is None:
            raise IngestRefused("filing store not wired")
        if filing_id not in self.filings.items(cui, period):
            raise IngestRefused(f"{filing_id} is not due for {period}; open the period's items")
        if not data:
            raise IngestRefused("a receipt is a file; an empty upload closes nothing")
        tenant = self.registry.tenant(cui)
        digest = hashlib.sha256(data).hexdigest()
        key = (
            f"tenants/{cui}/{tenant.punct if tenant else 'default'}/{period}/receipts/"
            f"{filing_id}/{digest}{Path(filename).suffix.lower()}"
        )
        self.blobs.put(key, data)
        self.filings.receipt(cui, period, filing_id, key, by)
        return self.filings_view(cui, period)

    # -- close --

    @staticmethod
    def _close_cfg(cui: str, period: str) -> dict:
        return {"configurable": {"thread_id": f"close:{cui}:{period}"}}

    def close_view(self, cui: str, period: str) -> dict[str, Any]:
        state = self.close.get_state(self._close_cfg(cui, period))
        question = next((i.value for t in state.tasks for i in t.interrupts), None)
        stored = self.closes.get(cui, period)
        return {"run": stored.model_dump() if stored else None, "question": question}

    def start_close(self, cui: str, period: str, axes: dict[str, str]) -> dict[str, Any]:
        cfg = self._close_cfg(cui, period)
        if self.close.get_state(cfg).tasks:
            return self.close_view(cui, period)  # already waiting on a person
        self.close.invoke({"cui": cui, "period": period, "axes": axes}, cfg)
        return self.close_view(cui, period)

    def resume_close(
        self, cui: str, period: str, payload: Any, operator: str | None = None
    ) -> dict[str, Any]:
        cfg = self._close_cfg(cui, period)
        self._answer(self.close, cfg, "monthly_close", cui, payload, operator)
        return self.close_view(cui, period)

    def period_diff(
        self, cui: str, period: str, axes: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Layer 1 for one firm-month: PeriodDiff, control runs, and whether V2 may file."""
        expected = self.expected(cui, period)
        eye = self._eye(cui, period)
        axes = self.axes(cui, period, axes)
        rules = self.rules.active(cui) if self.rules is not None else []
        diff, runs = build_period_diff(
            self.catalog, cui, period, expected, eye, axes=axes, rules=rules
        )
        if self.periods is not None:
            self.periods.save(diff, runs)
        return {
            "diff": diff.model_dump(),
            "controls": [r.model_dump() for r in runs],
            "can_file": can_file(diff),
        }

    # -- uploads --

    def put_export(
        self,
        cui: str,
        kind: ExportKind,
        product: Product | None,
        data: bytes,
        filename: str,
        periods: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.registry.tenant(cui) is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        covered = check_export(cui, product, kind, data, filename, periods)
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        row = export_row(cui, product, kind, data, filename, covered, now)
        self.blobs.put(row.bucket_key, data)
        self.registry.add_export(row)
        return row.model_dump()

    # -- folder_triage: expense reports (WP-28) --

    _DECONT_KINDS = {".pdf": "pdf", ".xls": "xls", ".xlsx": "xlsx", ".msg": "msg", ".eml": "eml"}

    @staticmethod
    def _batch_cfg(batch_id: str) -> dict:
        return {"configurable": {"thread_id": f"batch:{batch_id}"}}

    def batch_view(self, batch_id: str) -> dict[str, Any]:
        state = self.triage.get_state(self._batch_cfg(batch_id))
        if not state.values:
            raise KeyError(batch_id)
        question = next((i.value for t in state.tasks for i in t.interrupts), None)
        values = state.values
        return {
            "batch_id": batch_id,
            "question": question,
            "decision": values.get("decision"),
            "children": [
                {
                    "source_doc_id": c["pack"]["source_doc_id"],
                    "part_hash": c["pack"]["source_hash"],
                    "emit": c["decision"]["emit"],
                    "failed": c["decision"]["failed"],
                    "job_id": c.get("job_id"),
                }
                for c in values.get("children") or []
            ],
        }

    def ingest_decont(
        self, cui: str, data: bytes, filename: str, period: str, *, tenant_on_doc: bool
    ) -> dict[str, Any]:
        """An expense report (decont de cheltuieli, A2) → folder_triage on ``batch:decont-…``.

        The report is a container: it never becomes a Job. Once its identity and primary
        gates pass, a person names its parts (``decont_split``); each part is a child Pack
        through the same gates. Nothing reads the file yet, so the tenant's presence on it
        is the operator's statement (``tenant_on_doc``); without it the identity gate fails.
        """
        tenant: Tenant | None = self.registry.tenant(cui)
        if tenant is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        kind = self._DECONT_KINDS.get(Path(filename).suffix.lower())
        if kind is None:
            raise IngestRefused(f"an expense report is one of {sorted(self._DECONT_KINDS)}")
        if not data:
            raise IngestRefused("the expense report file is empty")
        source_hash = hashlib.sha256(data).hexdigest()
        batch_id = f"decont-{cui}-{source_hash[:32]}"
        cfg = self._batch_cfg(batch_id)
        if self.triage.get_state(cfg).values:
            return {"created": False, **self.batch_view(batch_id)}
        self.blobs.put(
            f"tenants/{cui}/{tenant.punct}/{period}/decont/source/{source_hash}/{filename}", data
        )
        row = self.catalog.source_docs["decont_cheltuieli"]
        self.gateway.observe(  # shadow: what Gemini would be given to propose the parts
            "ocr_decont_split",
            {
                "tenant_cui": cui,
                "file": {"sha256": source_hash, "bytes": len(data), "kind": kind},
                "children": list(row["split"]["children"]),
            },
            cui,
        )
        pack = Pack(
            tenant_cui=cui,
            saga_firm_folder=tenant.saga_firm_folder,
            punct=tenant.punct,
            period=period,
            source_hash=source_hash,
            source_doc_id="decont_cheltuieli",
            kinds=[kind],
            our_role="inbound",
            identity_ok=tenant_on_doc,
        )
        self.triage.invoke({"pack": pack.model_dump()}, cfg)
        return {"created": True, **self.batch_view(batch_id)}

    def resume_batch(
        self, batch_id: str, payload: Any, operator: str | None = None
    ) -> dict[str, Any]:
        self.batch_view(batch_id)  # KeyError for an unknown batch
        cfg = self._batch_cfg(batch_id)
        cui = (self.triage.get_state(cfg).values.get("pack") or {}).get("tenant_cui")
        self._answer(self.triage, cfg, "folder_triage", cui, payload, operator)
        return self.batch_view(batch_id)

    def ingest_upload(self, cui: str, data: bytes, filename: str) -> dict[str, Any]:
        """XML first: an SPV zip or a UBL XML becomes a Job and starts its thread."""
        tenant: Tenant | None = self.registry.tenant(cui)
        if tenant is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        try:
            if zipfile.is_zipfile(io.BytesIO(data)):
                xml = read_spv_zip(data).invoice
            elif filename.lower().endswith(".xml"):
                xml = data
            else:
                raise IngestRefused("v1 ingests SPV zips and UBL XML only (XML first)")
            invoice = parse_ubl(xml, where=filename)
            source_hash = hashlib.sha256(data).hexdigest()
            draft_job = JobRecord(
                job_id="pending", tenant=tenant.ref(), period="2000-01", status="ingested"
            )
            source = SourceRef(
                kind="ubl_spv",
                bucket_key=f"tenants/{cui}/{tenant.punct}/{invoice.issue_date[:7]}/source/"
                f"{source_hash}/{filename}",
                content_type="application/zip" if xml is not data else "application/xml",
                source_hash=source_hash,
            )
            doc = to_canonical(invoice, job=draft_job, source=source)
        except UblError as exc:
            raise IngestRefused(str(exc)) from exc
        self.gateway.observe(  # shadow: what Jev would be asked at triage
            "jev_source_doc",
            {
                "tenant_cui": cui,
                "filename": filename,
                "content_type": source.content_type,
                "root": invoice.root,
                "type_code": invoice.type_code,
            },
            cui,
        )
        self.gateway.observe(
            "jev_our_role",
            {
                "tenant_cui": cui,
                "supplier": invoice.supplier.model_dump(),
                "customer": invoice.customer.model_dump(),
            },
            cui,
        )

        pack = Pack(
            tenant_cui=cui,
            saga_firm_folder=tenant.saga_firm_folder,
            punct=tenant.punct,
            period=doc.period,
            source_hash=source_hash,
            source_doc_id="ro_efactura_ubl",
            kinds=["ubl_spv"],
            our_role="outbound" if doc.doc_class in ("iesire", "storn_iesire") else "inbound",
            counterparty_cui=doc.partner.cui,
            identity_ok=True,
            is_storno=doc.is_storno,
        )
        decision = decide_emit(self.catalog, pack)
        if not decision.emit:
            raise IngestRefused(f"emit gates failed: {decision.failed}")
        result = self.jobs.emit(pack, decision)
        started = "canonical" in self.ingest.get_state(self._cfg(result.job.job_id)).values
        if not result.created and started:
            return {"created": False, **self.view(result.job.job_id)}
        # a Job minted by folder_triage (an expense report's part) gets its thread now
        self.blobs.put(source.bucket_key, data)
        doc = doc.model_copy(update={"job_id": result.job.job_id})
        self.ingest.invoke(
            start_payload(
                result.job,
                doc,
                source_doc_id="ro_efactura_ubl",
                axes=self.axes(cui, doc.period),
            ),
            self._cfg(result.job.job_id),
        )
        return {"created": result.created, **self.view(result.job.job_id)}


def build_runtime(**parts: Any) -> Runtime:
    return Runtime(**parts)


def runtime_from_env(catalog: Catalog, dsn: str | None) -> tuple[Runtime | None, str]:
    """The production runtime, or None with the reason it is not wired."""
    from poarta_contabila.storage import S3BlobStore, S3Config

    if not dsn:
        return None, "DATABASE_URL not set"
    s3 = S3Config.from_env()
    if s3 is None:
        return None, "S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY / S3_BUCKET not set"
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from poarta_contabila.agent import PostgresAgentStore
    from poarta_contabila.answers import PostgresAnswerLog
    from poarta_contabila.close import PostgresCloseStore
    from poarta_contabila.codit import PostgresCoditStore
    from poarta_contabila.extract.contract import PostgresExtractStore
    from poarta_contabila.extract.document_ai import document_ai_from_env
    from poarta_contabila.filings import PostgresFilingStore
    from poarta_contabila.jev import PostgresJevCache, jev_from_env
    from poarta_contabila.jobs import PostgresJobStore
    from poarta_contabila.model_roles import PostgresModelCallStore
    from poarta_contabila.packages import PostgresPackageStore
    from poarta_contabila.period_diff import PostgresPeriodStore
    from poarta_contabila.recon.pre import PostgresReconStore
    from poarta_contabila.registry import PostgresRegistry
    from poarta_contabila.rules import PostgresRuleStore

    pool = ConnectionPool(
        dsn,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
        open=True,
    )
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    model_mode = os.environ.get("MODEL_CALLS", "off").strip().lower() or "off"
    runtime = build_runtime(
        catalog=catalog,
        jobs=PostgresJobStore(dsn),
        packages=PostgresPackageStore(dsn),
        blobs=S3BlobStore(s3),
        registry=PostgresRegistry(dsn),
        recon=PostgresReconStore(dsn),
        agent_store=PostgresAgentStore(dsn),
        checkpointer=checkpointer,
        periods=PostgresPeriodStore(dsn),
        rules=PostgresRuleStore(dsn),
        closes=PostgresCloseStore(dsn),
        codits=PostgresCoditStore(dsn),
        filings=PostgresFilingStore(dsn),
        jev=None if model_mode == "dry" else jev_from_env(PostgresJevCache(dsn)),
        model_calls=PostgresModelCallStore(dsn),
        model_mode=model_mode,
        statement_reader=document_ai_from_env(),
        extracts=PostgresExtractStore(dsn),
        answers=PostgresAnswerLog(dsn),
    )
    return runtime, "ok"
