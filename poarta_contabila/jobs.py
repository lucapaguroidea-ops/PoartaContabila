"""Job store: emit is idempotent on ``(tenant_cui, source_hash)`` (ARCHITECTURE.md §16).

A second emit of the same source returns the existing Job; it never mints a
second one. Only a decision whose gates all passed may be stored.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from poarta_contabila.types import JobRecord, TenantRef

if TYPE_CHECKING:
    from poarta_contabila.triage import EmitDecision, Pack


@dataclass(frozen=True)
class EmitResult:
    job: JobRecord
    created: bool


def _new_job(pack: Pack, decision: EmitDecision) -> JobRecord:
    if not decision.emit or not decision.job_kind:
        raise ValueError(f"pack is not emittable: failed gates {decision.failed}")
    return JobRecord(
        job_id=str(uuid.uuid4()),
        tenant=TenantRef(
            cui=pack.tenant_cui, punct=pack.punct, saga_firm_folder=pack.saga_firm_folder
        ),
        period=pack.period,
        status="ingested",
        job_kind=decision.job_kind,
    )


_PACKAGED_OR_LATER = ("packaged", "wait_validare", "acked")


@dataclass
class InMemoryJobStore:
    """Same contract as :class:`PostgresJobStore`, for tests."""

    jobs: dict[tuple[str, str], JobRecord] = field(default_factory=dict)

    def get(self, job_id: str) -> JobRecord:
        for job in self.jobs.values():
            if job.job_id == job_id:
                return job
        raise KeyError(job_id)

    def update(self, job_id: str, **fields) -> JobRecord:
        """Set fields on a job (validated); returns the new record."""
        for key, job in self.jobs.items():
            if job.job_id == job_id:
                new = JobRecord.model_validate({**job.model_dump(), **fields})
                self.jobs[key] = new
                return new
        raise KeyError(job_id)

    def for_period(self, cui: str, period: str) -> list[JobRecord]:
        return [j for j in self.jobs.values() if j.tenant.cui == cui and j.period == period]

    def by_status(self, status: str, cui: str | None = None) -> list[JobRecord]:
        """Jobs in one status (optionally one tenant), oldest first by insertion."""
        return [j for j in self.jobs.values() if j.status == status and cui in (None, j.tenant.cui)]

    def packaged_count(self, cui: str, articol_id: str) -> int:
        """Jobs of this tenant on this articol that already reached `packaged` or later."""
        return sum(
            1
            for job in self.jobs.values()
            if job.tenant.cui == cui
            and job.articol_id == articol_id
            and job.status in _PACKAGED_OR_LATER
        )

    def emit(self, pack: Pack, decision: EmitDecision) -> EmitResult:
        job = _new_job(pack, decision)
        key = (pack.tenant_cui, pack.source_hash)
        if key in self.jobs:
            return EmitResult(self.jobs[key], created=False)
        self.jobs[key] = job
        return EmitResult(job, created=True)


class PostgresJobStore:
    """Jobs in ``domain.jobs``; the unique constraint does the deduplication."""

    def __init__(self, dsn: str, *, reset: bool = False) -> None:
        import psycopg

        from poarta_contabila.db import schema_sql

        self._dsn = dsn
        self._psycopg = psycopg
        with psycopg.connect(dsn, autocommit=True) as conn:
            if reset:
                conn.execute("DROP SCHEMA IF EXISTS domain CASCADE")
            conn.execute(schema_sql())

    def emit(self, pack: Pack, decision: EmitDecision) -> EmitResult:
        job = _new_job(pack, decision)
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            row = conn.execute(
                "INSERT INTO domain.jobs (job_id, tenant_cui, source_hash, period, status, body)"
                " VALUES (%s, %s, %s, %s, %s, %s)"
                " ON CONFLICT ON CONSTRAINT jobs_source_once DO NOTHING RETURNING body",
                (
                    job.job_id,
                    pack.tenant_cui,
                    pack.source_hash,
                    pack.period,
                    job.status,
                    job.model_dump_json(),
                ),
            ).fetchone()
            if row is not None:
                return EmitResult(job, created=True)
            (body,) = conn.execute(
                "SELECT body FROM domain.jobs WHERE tenant_cui = %s AND source_hash = %s",
                (pack.tenant_cui, pack.source_hash),
            ).fetchone()
        return EmitResult(JobRecord.model_validate(body, strict=False), created=False)

    def get(self, job_id: str) -> JobRecord:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.jobs WHERE job_id = %s", (job_id,)
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return JobRecord.model_validate(row[0], strict=False)

    def update(self, job_id: str, **fields) -> JobRecord:
        new = JobRecord.model_validate({**self.get(job_id).model_dump(), **fields})
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "UPDATE domain.jobs SET status = %s, body = %s, updated_at = now()"
                " WHERE job_id = %s",
                (new.status, new.model_dump_json(), job_id),
            )
        return new

    def for_period(self, cui: str, period: str) -> list[JobRecord]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT body FROM domain.jobs WHERE tenant_cui = %s AND period = %s"
                " ORDER BY created_at, job_id",
                (cui, period),
            ).fetchall()
        return [JobRecord.model_validate(r[0], strict=False) for r in rows]

    def by_status(self, status: str, cui: str | None = None) -> list[JobRecord]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT body FROM domain.jobs WHERE status = %s"
                " AND (%s::text IS NULL OR tenant_cui = %s) ORDER BY created_at, job_id",
                (status, cui, cui),
            ).fetchall()
        return [JobRecord.model_validate(r[0], strict=False) for r in rows]

    def packaged_count(self, cui: str, articol_id: str) -> int:
        with self._psycopg.connect(self._dsn) as conn:
            (n,) = conn.execute(
                "SELECT count(*) FROM domain.jobs WHERE tenant_cui = %s"
                " AND body->>'articol_id' = %s AND status = ANY(%s)",
                (cui, articol_id, list(_PACKAGED_OR_LATER)),
            ).fetchone()
        return int(n)
