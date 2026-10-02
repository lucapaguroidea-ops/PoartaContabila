"""WP-33: the answer log — every answer a person submits to a question, append-only.

The graphs keep the answer inside their checkpoints, which are working state, not a record.
This log is the record: for each submission, which thread and question it answered, what was
sent, when, by whom (``X-Operator-Name``; one shared operator token names no person), and
whether the graph took it:

- ``accepted``: the question is gone, or another one follows;
- ``asked_again``: the same question came back with an ``error`` (the answer did not
  validate, or broke a rule);
- ``no_question``: nothing was waiting on that thread.

Rows are only ever added; no code path updates or deletes one. The question is kept as its
sha256 (``question_hash``, without any ``error``) plus its kind; the answer is kept whole.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import Field

from poarta_contabila.types import Closed

Outcome = Literal["accepted", "asked_again", "no_question"]
OPERATOR_NAME_MAX = 64


class AnswerRecord(Closed):
    answer_id: str
    at: str  # UTC, microseconds
    graph_id: str
    thread_id: str
    tenant_cui: str | None
    kind: str | None
    question_hash: str | None
    answer: Any
    outcome: Outcome
    error: Any = None
    operator: str | None = None
    next_kind: str | None = None  # the question that followed, if any
    meta: dict[str, Any] = Field(default_factory=dict)


def _bare(question: dict[str, Any] | None) -> dict[str, Any] | None:
    return None if question is None else {k: v for k, v in question.items() if k != "error"}


def question_hash(question: dict[str, Any] | None) -> str | None:
    bare = _bare(question)
    if bare is None:
        return None
    return hashlib.sha256(json.dumps(bare, sort_keys=True, default=str).encode()).hexdigest()


def judge(before: dict[str, Any] | None, after: dict[str, Any] | None) -> tuple[Outcome, Any]:
    """What became of an answer, from the question before and after it was submitted."""
    if before is None:
        return "no_question", None
    if after is not None and "error" in after and _bare(after) == _bare(before):
        return "asked_again", after["error"]
    return "accepted", None


def record(
    *,
    graph_id: str,
    thread_id: str,
    tenant_cui: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    answer: Any,
    operator: str | None,
) -> AnswerRecord:
    outcome, error = judge(before, after)
    return AnswerRecord(
        answer_id=str(uuid.uuid4()),
        at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        graph_id=graph_id,
        thread_id=thread_id,
        tenant_cui=tenant_cui,
        kind=(before or {}).get("kind"),
        question_hash=question_hash(before),
        answer=answer,
        outcome=outcome,
        error=error,
        operator=operator,
        next_kind=(after or {}).get("kind") if outcome == "accepted" else None,
    )


class InMemoryAnswerLog:
    def __init__(self) -> None:
        self.rows: list[AnswerRecord] = []

    def add(self, row: AnswerRecord) -> None:
        self.rows.append(row)

    def recent(
        self, *, cui: str | None = None, thread_id: str | None = None, limit: int = 50
    ) -> list[AnswerRecord]:
        out = [
            r
            for r in reversed(self.rows)
            if (cui is None or r.tenant_cui == cui)
            and (thread_id is None or r.thread_id == thread_id)
        ]
        return out[:limit]


class PostgresAnswerLog:
    """``domain.answers``: insert-only."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def add(self, row: AnswerRecord) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.answers (answer_id, at, tenant_cui, thread_id, body)"
                " VALUES (%s, %s, %s, %s, %s)",
                (row.answer_id, row.at, row.tenant_cui, row.thread_id, row.model_dump_json()),
            )

    def recent(
        self, *, cui: str | None = None, thread_id: str | None = None, limit: int = 50
    ) -> list[AnswerRecord]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT body FROM domain.answers"
                " WHERE (%s::text IS NULL OR tenant_cui = %s)"
                " AND (%s::text IS NULL OR thread_id = %s)"
                " ORDER BY seq DESC LIMIT %s",
                (cui, cui, thread_id, thread_id, limit),
            ).fetchall()
        return [AnswerRecord.model_validate(r[0], strict=False) for r in rows]
