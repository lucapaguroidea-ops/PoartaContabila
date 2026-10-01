"""The wired gate: stores, bucket, checkpointer, the ingest graph and the agent service.

``build_runtime`` takes every part explicitly (tests pass in-memory ones);
``runtime_from_env`` builds the production one from ``DATABASE_URL`` and ``S3_*``.
Parts not wired yet fail closed: there is no Jev judge, so every document is asked
(``v3_approve``); a tenant without an uploaded journal export gets ``need_rj_export``.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command

from poarta_contabila.agent import AgentService
from poarta_contabila.catalog import Catalog
from poarta_contabila.extract.ubl import UblError, parse_ubl, read_spv_zip, to_canonical
from poarta_contabila.ingest import IngestDeps, build_ingest_graph, start_payload
from poarta_contabila.packages import BlobStore, PackageStore
from poarta_contabila.period_diff import ExpectedJob, build_period_diff, can_file
from poarta_contabila.recon.pre import ReconStore, make_pre_check
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


class IngestRefused(ValueError):
    """The upload cannot become a Job; the message says which gate."""


def _no_judge(doc: CanonicalDocument, articol: dict) -> dict:
    return {"accounts_ok": False, "risk": "unknown", "needs_human": True, "judge": "not wired"}


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

    def __post_init__(self) -> None:
        self.deps = IngestDeps(
            catalog=self.catalog,
            jobs=self.jobs,
            packages=self.packages,
            blobs=self.blobs,
            pre_check=make_pre_check(
                self.catalog, witnesses_provider(self.registry, self.blobs), store=self.recon
            ),
            judge=_no_judge,
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
        self.deps.posted_doc = self.agent.posted_doc

    # -- helpers --

    def _tenant_name(self, cui: str) -> str:
        tenant = self.registry.tenant(cui)
        if tenant is None:
            raise IngestRefused(f"tenant {cui} is not registered")
        return tenant.name

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

    def period_diff(
        self, cui: str, period: str, axes: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Layer 1 for one firm-month: PeriodDiff, control runs, and whether V2 may file."""
        expected = []
        for job in self.jobs.for_period(cui, period):
            values = self.ingest.get_state(self._cfg(job.job_id)).values
            if "canonical" in values:
                doc = CanonicalDocument.model_validate(values["canonical"])
                expected.append(ExpectedJob(job=self.jobs.get(job.job_id), doc=doc))
        probe = JobRecord(
            job_id="period",
            tenant=TenantRef(cui=cui, saga_firm_folder="-"),
            period=period,
            status="bound",
        )
        eye = witnesses_provider(self.registry, self.blobs)(probe).eye
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
            start_payload(result.job, doc, source_doc_id="ro_efactura_ubl"),
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
    )
    return runtime, "ok"
