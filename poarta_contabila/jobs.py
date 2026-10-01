"""Job store: emit is idempotent on ``(tenant_cui, source_hash)`` (IDEMPOTENCY.md).

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


@dataclass
class InMemoryJobStore:
    """Same contract as :class:`PostgresJobStore`, for tests."""

    jobs: dict[tuple[str, str], JobRecord] = field(default_factory=dict)

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
