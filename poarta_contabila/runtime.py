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
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langgraph.types import Command

from poarta_contabila.agent import AgentService
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
from poarta_contabila.jev import make_judge, make_v2
from poarta_contabila.packages import BlobStore, PackageStore
from poarta_contabila.period_diff import ExpectedJob, build_period_diff, can_file
from poarta_contabila.recon.pre import ReconStore, make_pre_check
from poarta_contabila.recon.settle import (
    SETTLES,
    InvoiceJob,
    SettlementProposal,
    propose_settlement,
    settle_key,
)
from poarta_contabila.registry import (
    ExportKind,
    Product,
    Tenant,
    check_export,
    export_row,
    witnesses_provider,
)
from poarta_contabila.triage import Pack, decide_emit
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

    def __post_init__(self) -> None:
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
                jev_v2=make_v2(self.jev, self.axes),
                codit=lambda cui, period: (
                    self.codits.get(cui, period) if self.codits is not None else None
                ),
                codit_put=self.codits.put if self.codits is not None else None,
            ),
            checkpointer=self.checkpointer,
        )
        self.deps.posted_doc = self.agent.posted_doc
        self.deps.treasury_account = self._treasury_account
        self.deps.settlement = self.settlement

    # -- helpers --

    def _tenant_name(self, cui: str) -> str:
        tenant = self.registry.tenant(cui)
        if tenant is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        return tenant.name

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

    def resume(self, job_id: str, payload: Any) -> dict[str, Any]:
        self.jobs.get(job_id)  # KeyError for an unknown job
        self.ingest.invoke(Command(resume=payload), self._cfg(job_id))
        return self.view(job_id)

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
        """The invoices an unbound bank line could settle (WP-22), from this tenant's invoice
        Jobs and the books' journals in the line's month and the two before it."""
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
        return propose_settlement(
            line,
            invoices,
            books,
            settled_ids=frozenset(d.maps["factura_id"] for d in bound if d.maps.get("factura_id")),
            settled_numbers=frozenset(
                settle_key(d.partner.cui, d.maps["factura_numar"])
                for d in bound
                if d.maps.get("factura_numar")
            ),
        )

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

    def resume_close(self, cui: str, period: str, payload: Any) -> dict[str, Any]:
        self.close.invoke(Command(resume=payload), self._close_cfg(cui, period))
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
        if not result.created:
            return {"created": False, **self.view(result.job.job_id)}
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
        return {"created": True, **self.view(result.job.job_id)}


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
    from poarta_contabila.close import PostgresCloseStore
    from poarta_contabila.codit import PostgresCoditStore
    from poarta_contabila.extract.contract import PostgresExtractStore
    from poarta_contabila.extract.document_ai import document_ai_from_env
    from poarta_contabila.filings import PostgresFilingStore
    from poarta_contabila.jev import PostgresJevCache, jev_from_env
    from poarta_contabila.jobs import PostgresJobStore
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
        jev=jev_from_env(PostgresJevCache(dsn)),
        statement_reader=document_ai_from_env(),
        extracts=PostgresExtractStore(dsn),
    )
    return runtime, "ok"
