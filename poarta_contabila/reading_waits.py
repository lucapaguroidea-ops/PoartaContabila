"""statements waiting for model quota (LAW L31).

When no Gemini model can read a synthetic statement now (every model in the order at its
limit, or busy), nothing is wrong with the document: it is parked here with its PDF in the
bucket and read again from ``not_before`` on — by the background retry or ``POST
/reading/{cui}/retry``. A parked statement has no Job yet; its lines are minted only when the
read confirms. One row per ``(tenant, PDF)``: uploading the same PDF again while it waits
neither duplicates it nor loses it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from poarta_contabila.types.base import Closed

Status = Literal["waiting", "read", "refused", "skipped"]
Choice = Literal["wait", "reserve"]


class ReadingWait(Closed):
    wait_id: str  # {cui}:{sha256 of the PDF}
    tenant_cui: str
    meta: dict[str, Any]  # the StatementMeta as uploaded
    pdf_key: str  # where the PDF waits in the bucket
    strong: bool = False
    status: Status = "waiting"
    reason: str  # why it waits (or why it was refused)
    not_before: str  # UTC ISO: read again from then on
    attempts: int = 0
    created_at: str
    result: dict[str, Any] | None = None  # once read: the ingest result
    skipped_by: str | None = None  # who set it aside, and why (in reason)


class ReadingChoice(Closed):
    """LAW L31: what an operator chose when every tier was spent, for one Pacific day."""

    choice_id: str  # {pacific date}:{seq}
    day: str  # the Pacific date it holds for
    choice: Choice
    tenant_cui: str  # the tenant whose statements were waiting when it was chosen
    operator: str | None
    at: str  # UTC ISO
    until: str  # UTC ISO: the next Pacific midnight
    released: int = 0  # parked statements it sent to be read again


@dataclass
class InMemoryReadingChoiceStore:
    rows: list[ReadingChoice] = field(default_factory=list)

    def add(self, choice: ReadingChoice) -> None:
        self.rows.append(choice)

    def latest(self, day: str) -> ReadingChoice | None:
        rows = [c for c in self.rows if c.day == day]
        return rows[-1] if rows else None

    def recent(self, limit: int = 50) -> list[ReadingChoice]:
        return list(reversed(self.rows))[:limit]


class PostgresReadingChoiceStore:
    """``domain.reading_choices``: insert-only."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def add(self, choice: ReadingChoice) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.reading_choices (choice_id, day, body) VALUES (%s, %s, %s)",
                (choice.choice_id, choice.day, choice.model_dump_json()),
            )

    def latest(self, day: str) -> ReadingChoice | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.reading_choices WHERE day = %s ORDER BY seq DESC LIMIT 1",
                (day,),
            ).fetchone()
        return ReadingChoice.model_validate(row[0], strict=False) if row else None

    def recent(self, limit: int = 50) -> list[ReadingChoice]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT body FROM domain.reading_choices ORDER BY seq DESC LIMIT %s", (limit,)
            ).fetchall()
        return [ReadingChoice.model_validate(r[0], strict=False) for r in rows]


@dataclass
class InMemoryReadingWaitStore:
    rows: dict[str, ReadingWait] = field(default_factory=dict)

    def put(self, wait: ReadingWait) -> ReadingWait:
        """Park *wait*, or return the one already waiting for the same PDF."""
        current = self.rows.get(wait.wait_id)
        if current is not None and current.status == "waiting":
            return current
        self.rows[wait.wait_id] = wait
        return wait

    def update(self, wait: ReadingWait) -> None:
        self.rows[wait.wait_id] = wait

    def due(self, now: datetime) -> list[ReadingWait]:
        at = now.isoformat()
        rows = [w for w in self.rows.values() if w.status == "waiting" and w.not_before <= at]
        return sorted(rows, key=lambda w: (w.not_before, w.created_at))

    def list(self, cui: str, status: Status | None = None) -> list[ReadingWait]:
        rows = [w for w in self.rows.values() if w.tenant_cui == cui and status in (None, w.status)]
        return sorted(rows, key=lambda w: w.created_at)


class PostgresReadingWaitStore:
    """``domain.reading_waits``."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def put(self, wait: ReadingWait) -> ReadingWait:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.reading_waits (wait_id, tenant_cui, status, not_before, body)"
                " VALUES (%s, %s, %s, %s, %s)"
                " ON CONFLICT (wait_id) DO UPDATE SET status = EXCLUDED.status,"
                " not_before = EXCLUDED.not_before, body = EXCLUDED.body"
                " WHERE domain.reading_waits.status <> 'waiting'",
                (
                    wait.wait_id,
                    wait.tenant_cui,
                    wait.status,
                    wait.not_before,
                    wait.model_dump_json(),
                ),
            )
            row = conn.execute(
                "SELECT body FROM domain.reading_waits WHERE wait_id = %s", (wait.wait_id,)
            ).fetchone()
        return ReadingWait.model_validate(row[0], strict=False)

    def update(self, wait: ReadingWait) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "UPDATE domain.reading_waits SET status = %s, not_before = %s, body = %s"
                " WHERE wait_id = %s",
                (wait.status, wait.not_before, wait.model_dump_json(), wait.wait_id),
            )

    def due(self, now: datetime) -> list[ReadingWait]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT body FROM domain.reading_waits WHERE status = 'waiting'"
                " AND not_before <= %s ORDER BY not_before, wait_id",
                (now.isoformat(),),
            ).fetchall()
        return [ReadingWait.model_validate(r[0], strict=False) for r in rows]

    def list(self, cui: str, status: Status | None = None) -> list[ReadingWait]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT body FROM domain.reading_waits WHERE tenant_cui = %s"
                " AND (%s::text IS NULL OR status = %s) ORDER BY body->>'created_at'",
                (cui, status, status),
            ).fetchall()
        return [ReadingWait.model_validate(r[0], strict=False) for r in rows]
