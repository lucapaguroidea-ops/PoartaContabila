"""Windows agent (ARCHITECTURE §13): the only hand that touches SAGA, and only to import.

    GET  /agent/pull        packages waiting, per firm folder, with the backup they need
    POST /agent/ack-backup  the agent made a firm-wide backup: label {cui}:{folder}:{utc}
    POST /agent/imported    the agent imported packages as AGENT (Import only)
    POST /agent/snapshot    what SAGA shows: documents (validated or not) and closed months

Rules (LAW):

- AGENT imports only: no Validare, no Devalidare, no month closing. Nothing here can
  move a job out of ``acked``; a snapshot that no longer shows an acked document is
  reported, never acted on.
- A batch whose module asks for a backup is imported only under an acknowledged
  label of the same firm and folder (a restore across tenants is refused).
- A month closed in SAGA gets nothing (the agent writes 0): its packages are held.
- ``acked`` comes only from a snapshot: the job's thread is resumed with the SAGA key
  of a validated document that matches it. No snapshot, no ack.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import Field

from poarta_contabila.catalog import Catalog
from poarta_contabila.packages import BlobStore, PackageStore
from poarta_contabila.recon.numbers import normalize
from poarta_contabila.sinks.saga_xml import packaged_number
from poarta_contabila.types import (
    CanonicalDocument,
    Closed,
    Cui,
    DocClass,
    FiscalDate,
    JobRecord,
    Money,
    Period,
)

_LABEL = re.compile(r"^(?P<cui>\d{2,10}):(?P<folder>[^:]+):(?P<utc>\d{8}T\d{6}Z)$")


class AgentError(ValueError):
    """The agent's request breaks a rule; nothing was changed."""


# ----- wire models -----


class PullItem(Closed):
    export_key: str
    job_id: str
    module_id: str
    saga_path: Literal["import_xml", "import_dbf", "ui_agent"]
    period: Period
    bucket_key: str
    filename: str
    content_b64: str


class PullBatch(Closed):
    cui: Cui
    folder: str
    backup: Literal["none", "before_batch", "before_each"]
    items: list[PullItem]


class HeldItem(Closed):
    job_id: str
    reason: str


class PullResponse(Closed):
    batches: list[PullBatch] = Field(default_factory=list)
    held: list[HeldItem] = Field(default_factory=list)


class BackupAck(Closed):
    label: str
    cui: Cui
    folder: str


class ImportResult(Closed):
    export_key: str
    ok: bool
    message: str = ""


class ImportedReport(Closed):
    cui: Cui
    folder: str
    backup_label: str | None = None
    results: list[ImportResult] = Field(min_length=1)


class SnapshotDoc(Closed):
    saga_doc_key: str
    doc_class: DocClass
    number: str
    date: FiscalDate
    gross: Money
    validated: bool
    net: Money | None = None  # from the report pack's purchase/sales journal, when read
    vat: Money | None = None
    partner_cui: Cui | None = None


class Snapshot(Closed):
    cui: Cui
    folder: str
    taken_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
    closed_periods: list[Period] = Field(default_factory=list)
    documents: list[SnapshotDoc] = Field(default_factory=list)


class SnapshotResult(Closed):
    snapshot_id: str
    acked: list[str] = Field(default_factory=list)
    intent_mismatch: list[str] = Field(default_factory=list)
    waiting: list[str] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    acked_not_shown: list[str] = Field(default_factory=list)


# ----- store -----


class AgentStore(Protocol):
    def ack_backup(self, label: str, cui: str, folder: str, taken_at: datetime) -> None: ...

    def has_backup(self, label: str, cui: str, folder: str) -> bool: ...

    def add_snapshot(self, snapshot_id: str, snap: Snapshot) -> None: ...

    def latest_snapshot(self, cui: str) -> Snapshot | None: ...


@dataclass
class InMemoryAgentStore:
    backups: dict[str, tuple[str, str, datetime]] = field(default_factory=dict)
    snapshots: dict[str, Snapshot] = field(default_factory=dict)

    def ack_backup(self, label: str, cui: str, folder: str, taken_at: datetime) -> None:
        self.backups.setdefault(label, (cui, folder, taken_at))

    def has_backup(self, label: str, cui: str, folder: str) -> bool:
        row = self.backups.get(label)
        return row is not None and row[:2] == (cui, folder)

    def add_snapshot(self, snapshot_id: str, snap: Snapshot) -> None:
        self.snapshots.setdefault(snapshot_id, snap)

    def latest_snapshot(self, cui: str) -> Snapshot | None:
        mine = [s for s in self.snapshots.values() if s.cui == cui]
        return max(mine, key=lambda s: s.taken_at) if mine else None


class PostgresAgentStore:
    """``domain.agent_backups`` and ``domain.agent_snapshots``."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def ack_backup(self, label: str, cui: str, folder: str, taken_at: datetime) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.agent_backups (label, tenant_cui, folder, taken_at)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (label) DO NOTHING",
                (label, cui, folder, taken_at),
            )

    def has_backup(self, label: str, cui: str, folder: str) -> bool:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT 1 FROM domain.agent_backups"
                " WHERE label = %s AND tenant_cui = %s AND folder = %s",
                (label, cui, folder),
            ).fetchone()
        return row is not None

    def add_snapshot(self, snapshot_id: str, snap: Snapshot) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.agent_snapshots"
                " (snapshot_id, tenant_cui, folder, taken_at, body)"
                " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (snapshot_id) DO NOTHING",
                (snapshot_id, snap.cui, snap.folder, snap.taken_at, snap.model_dump_json()),
            )

    def latest_snapshot(self, cui: str) -> Snapshot | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.agent_snapshots WHERE tenant_cui = %s"
                " ORDER BY taken_at DESC, received_at DESC LIMIT 1",
                (cui,),
            ).fetchone()
        return Snapshot.model_validate(row[0], strict=False) if row else None


# ----- service -----

_SIDE = {
    "intrare": "in",
    "storn_intrare": "in",
    "iesire": "out",
    "storn_iesire": "out",
}


def _matches(doc: CanonicalDocument, sd: SnapshotDoc) -> bool:
    return (
        _SIDE.get(doc.doc_class, doc.doc_class) == _SIDE.get(sd.doc_class, sd.doc_class)
        and normalize(packaged_number(doc), "alnum") == normalize(sd.number, "alnum")
        and doc.date == sd.date
        and Decimal(doc.totals.gross) == Decimal(sd.gross)
    )


@dataclass
class AgentService:
    """The agent's side of the gate. ``resume`` continues a job's ingest thread;
    ``canonical`` reads the job's document from that thread."""

    catalog: Catalog
    jobs: Any  # InMemoryJobStore | PostgresJobStore
    packages: PackageStore
    blobs: BlobStore
    store: AgentStore
    resume: Callable[[str, dict[str, Any]], None]
    canonical: Callable[[str], CanonicalDocument]

    def posted_doc(self, cui: str, saga_doc_key: str) -> dict[str, Any] | None:
        """For ``IngestDeps.posted_doc``: the latest snapshot's document for the key."""
        snap = self.store.latest_snapshot(cui)
        for d in snap.documents if snap else []:
            if d.saga_doc_key == saga_doc_key:
                return d.model_dump()
        return None

    def snapshot_validated(self, cui: str, saga_doc_key: str) -> bool:
        """For ``IngestDeps.snapshot_validated``: the latest snapshot shows it validated."""
        snap = self.store.latest_snapshot(cui)
        return snap is not None and any(
            d.saga_doc_key == saga_doc_key and d.validated for d in snap.documents
        )

    # -- pull --

    def pull(self) -> PullResponse:
        groups: dict[tuple[str, str], list[PullItem]] = {}
        backups: dict[tuple[str, str], set[str]] = {}
        held: list[HeldItem] = []
        counts: dict[tuple[str, str, str], int] = {}
        names: dict[tuple[str, str], set[str]] = {}
        closed: dict[str, set[str]] = {}
        for job in self.jobs.by_status("packaged"):
            cui, folder = job.tenant.cui, job.tenant.saga_firm_folder
            if cui not in closed:
                snap = self.store.latest_snapshot(cui)
                closed[cui] = set(snap.closed_periods) if snap else set()
            if job.period in closed[cui]:
                held.append(HeldItem(job_id=job.job_id, reason=f"{job.period} closed in SAGA"))
                continue
            for row in self.packages.for_job(job.job_id):
                module = self.catalog.write_modules[row.module_id]
                key = (cui, folder, module.module_id)
                if counts.get(key, 0) >= module.max_docs_per_run:
                    held.append(
                        HeldItem(job_id=job.job_id, reason=f"{module.module_id} run is full")
                    )
                    continue
                filename = row.bucket_key.rsplit("/", 1)[-1]
                if filename in names.setdefault((cui, folder), set()):
                    # one import folder per run: two receipts of one day are both I_<data>.xml
                    held.append(
                        HeldItem(job_id=job.job_id, reason=f"{filename} is already in this run")
                    )
                    continue
                names[(cui, folder)].add(filename)
                counts[key] = counts.get(key, 0) + 1
                groups.setdefault((cui, folder), []).append(
                    PullItem(
                        export_key=row.export_key,
                        job_id=job.job_id,
                        module_id=module.module_id,
                        saga_path=module.saga_path,
                        period=job.period,
                        bucket_key=row.bucket_key,
                        filename=filename,
                        content_b64=base64.b64encode(self.blobs.get(row.bucket_key)).decode(),
                    )
                )
                backups.setdefault((cui, folder), set()).add(module.backup)
        batches = []
        for (cui, folder), items in groups.items():
            kinds = backups[(cui, folder)]
            backup = next((b for b in ("before_each", "before_batch") if b in kinds), "none")
            batches.append(PullBatch(cui=cui, folder=folder, backup=backup, items=items))
        return PullResponse(batches=batches, held=held)

    # -- backup --

    def ack_backup(self, ack: BackupAck) -> None:
        m = _LABEL.match(ack.label)
        if m is None:
            raise AgentError("backup label must be {cui}:{folder}:{YYYYMMDDTHHMMSSZ}")
        if (m["cui"], m["folder"]) != (ack.cui, ack.folder):
            raise AgentError("backup label names another firm or folder")
        taken = datetime.strptime(m["utc"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        self.store.ack_backup(ack.label, ack.cui, ack.folder, taken)

    # -- imported --

    def imported(self, report: ImportedReport) -> list[ImportResult]:
        out: list[ImportResult] = []
        for r in report.results:
            row = self.packages.get(r.export_key)
            if row is None:
                out.append(ImportResult(export_key=r.export_key, ok=False, message="unknown"))
                continue
            job = self.jobs.get(row.job_id)
            if (job.tenant.cui, job.tenant.saga_firm_folder) != (report.cui, report.folder):
                out.append(ImportResult(export_key=r.export_key, ok=False, message="another firm"))
                continue
            if job.status != "packaged":
                ok = job.status not in ("needs_human", "rejected", "failed")
                out.append(ImportResult(export_key=r.export_key, ok=ok, message=job.status))
                continue  # replay: already recorded
            module = self.catalog.write_modules[row.module_id]
            if module.backup != "none" and not (
                report.backup_label
                and self.store.has_backup(report.backup_label, report.cui, report.folder)
            ):
                out.append(
                    ImportResult(
                        export_key=r.export_key,
                        ok=False,
                        message="no acknowledged backup for this firm and folder",
                    )
                )
                continue
            if r.ok:
                self.jobs.update(
                    job.job_id,
                    status="wait_validare",
                    saga={"backup_label": report.backup_label},
                )
                out.append(ImportResult(export_key=r.export_key, ok=True, message="wait_validare"))
            else:
                self.jobs.update(
                    job.job_id, status="needs_human", error=f"SAGA import: {r.message}"
                )
                out.append(ImportResult(export_key=r.export_key, ok=False, message="needs_human"))
        return out

    # -- snapshot --

    def snapshot(self, snap: Snapshot) -> SnapshotResult:
        body = snap.model_dump_json()
        snapshot_id = hashlib.sha256(json.dumps(json.loads(body), sort_keys=True).encode())
        snapshot_id = snapshot_id.hexdigest()
        self.store.add_snapshot(snapshot_id, snap)
        result = SnapshotResult(snapshot_id=snapshot_id)
        for job in self._jobs(snap, "wait_validare"):
            doc = self.canonical(job.job_id)
            hits = [d for d in snap.documents if _matches(doc, d)]
            if len(hits) != 1:
                (result.unmatched if not hits else result.waiting).append(job.job_id)
                continue
            if not hits[0].validated:
                result.waiting.append(job.job_id)
                continue
            self.resume(job.job_id, {"validated": True, "saga_doc_key": hits[0].saga_doc_key})
            # the thread re-checks against the latest snapshot; trust its outcome only
            status = self.jobs.get(job.job_id).status
            if status == "acked":
                result.acked.append(job.job_id)
            elif status == "needs_human":
                result.intent_mismatch.append(job.job_id)
            else:
                result.waiting.append(job.job_id)
        shown = {d.saga_doc_key for d in snap.documents if d.validated}
        for job in self._jobs(snap, "acked"):
            if job.saga.get("saga_doc_key") not in shown and self._in_scope(job, snap):
                result.acked_not_shown.append(job.job_id)  # reported only: AGENT never undoes
        return result

    def _jobs(self, snap: Snapshot, status: str) -> list[JobRecord]:
        return [
            j
            for j in self.jobs.by_status(status, snap.cui)
            if j.tenant.saga_firm_folder == snap.folder
        ]

    @staticmethod
    def _in_scope(job: JobRecord, snap: Snapshot) -> bool:
        return any(d.date[:7] == job.period for d in snap.documents)
