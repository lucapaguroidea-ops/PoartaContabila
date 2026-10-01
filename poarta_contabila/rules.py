"""Explained rules (WP-09): what the books may hold with no source document here.

A rule is named, versioned, and written by a person (``POST /rules``); a new body is a
new version, earlier ones are kept. It matches either

- **documents** in the books (side, partner CUI, number prefix, gross ceiling) → their
  bucket row becomes ``explained_sink_only`` carrying the ``rule_id``, and their postings
  count on the expected side of the parity control; or
- **journal lines** (debit / credit account patterns, journal, words in the
  explanation) → their amounts on the watched accounts count as explained turnover.

Nothing is explained without a rule: there is no free-text "ok". The HITL answers that
use rules (``explained_rule``, ``control_disposition``) are checked here.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from poarta_contabila.sinks.exports import SinkLine, synthetic
from poarta_contabila.types import Closed, Cui, DocClass, Money, Period, SinkDoc, Slug

_IN = {"intrare", "storn_intrare"}
_OUT = {"iesire", "storn_iesire"}


class DocumentMatch(Closed):
    doc_class: DocClass | None = None
    partner_cui: Cui | None = None
    number_prefix: str | None = None
    gross_max: Money | None = None


class LineMatch(Closed):
    debit: str = Field(min_length=1, description="account pattern, e.g. 627 or 5121*")
    credit: str = Field(min_length=1)
    journal: str | None = None
    explanation_contains: str | None = None


class RuleBody(Closed):
    """What a person writes. ``rule_id`` + tenant come from the request."""

    description: str = Field(min_length=3)
    scope: Literal["document", "line"]
    document: DocumentMatch | None = None
    line: LineMatch | None = None
    valid_from: Period | None = None
    valid_to: Period | None = None

    @model_validator(mode="after")
    def _one_matcher(self) -> RuleBody:
        if (self.scope == "document") != (self.document is not None) or (self.scope == "line") != (
            self.line is not None
        ):
            raise ValueError("give exactly the matcher named by scope")
        if self.document is not None and not self.document.model_dump(exclude_none=True):
            raise ValueError("a document rule must narrow at least one field")
        return self


class ExplainedRule(RuleBody):
    cui: Cui
    rule_id: Slug
    version: int = Field(ge=1)

    def applies_to(self, period: str) -> bool:
        return (self.valid_from or "0000-00") <= period <= (self.valid_to or "9999-12")

    def matches_doc(self, d: SinkDoc) -> bool:
        m = self.document
        if m is None:
            return False
        if m.doc_class and m.doc_class != d.doc_class:
            return False
        if m.partner_cui and m.partner_cui != d.partner_cui:
            return False
        if m.number_prefix and not d.number.upper().startswith(m.number_prefix.upper()):
            return False
        return not (m.gross_max and abs(Decimal(d.gross)) > Decimal(m.gross_max))

    def matches_line(self, ln: SinkLine) -> bool:
        m = self.line
        if m is None:
            return False
        if not (
            fnmatch.fnmatch(ln.debit, m.debit) or fnmatch.fnmatch(synthetic(ln.debit), m.debit)
        ):
            return False
        if not (
            fnmatch.fnmatch(ln.credit, m.credit) or fnmatch.fnmatch(synthetic(ln.credit), m.credit)
        ):
            return False
        if m.journal and m.journal != ln.journal:
            return False
        return not (
            m.explanation_contains
            and m.explanation_contains.lower() not in (ln.explanation or "").lower()
        )


def explained_turnover(
    docs: list[tuple[SinkDoc, str]], lines: list[SinkLine]
) -> dict[str, dict[str, Decimal]]:
    """Turnover on accounts that explained documents and lines account for."""
    t: dict[str, dict[str, Decimal]] = {}

    def add(account: str, side: str, amount: Decimal) -> None:
        t.setdefault(account, {"debit": Decimal(0), "credit": Decimal(0)})[side] += amount

    for d, _ in docs:
        if d.doc_class in _IN:
            add("401", "credit", Decimal(d.gross))
            add("4426", "debit", Decimal(d.vat))
        elif d.doc_class in _OUT:
            add("4111", "debit", Decimal(d.gross))
            add("4427", "credit", Decimal(d.vat))
        elif d.doc_class == "incasare":
            add("5121", "debit", Decimal(d.gross))
        elif d.doc_class == "plata":
            add("5121", "credit", Decimal(d.gross))
    for ln in lines:
        add(synthetic(ln.debit), "debit", Decimal(ln.amount))
        add(synthetic(ln.credit), "credit", Decimal(ln.amount))
    return t


# ----- store -----


@dataclass
class InMemoryRuleStore:
    rows: list[ExplainedRule] = field(default_factory=list)

    def add(self, cui: str, rule_id: str, body: RuleBody) -> ExplainedRule:
        """A new version; the same body as the latest version is not a new version."""
        latest = self.latest(cui, rule_id)
        if (
            latest
            and RuleBody.model_validate(latest.model_dump(include=set(RuleBody.model_fields)))
            == body
        ):
            return latest
        rule = ExplainedRule(
            **body.model_dump(),
            cui=cui,
            rule_id=rule_id,
            version=(latest.version + 1) if latest else 1,
        )
        self.rows.append(rule)
        return rule

    def latest(self, cui: str, rule_id: str) -> ExplainedRule | None:
        mine = [r for r in self.rows if r.cui == cui and r.rule_id == rule_id]
        return max(mine, key=lambda r: r.version) if mine else None

    def active(self, cui: str) -> list[ExplainedRule]:
        ids = {r.rule_id for r in self.rows if r.cui == cui}
        return [self.latest(cui, i) for i in sorted(ids)]


class PostgresRuleStore:
    """``domain.explained_rules`` (key ``(cui, rule_id, version)``)."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def add(self, cui: str, rule_id: str, body: RuleBody) -> ExplainedRule:
        with self._psycopg.connect(self._dsn) as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"{cui}:{rule_id}",))
            row = conn.execute(
                "SELECT body FROM domain.explained_rules WHERE cui = %s AND rule_id = %s"
                " ORDER BY version DESC LIMIT 1",
                (cui, rule_id),
            ).fetchone()
            latest = ExplainedRule.model_validate(row[0], strict=False) if row else None
            if (
                latest
                and RuleBody.model_validate(
                    latest.model_dump(include=set(RuleBody.model_fields)), strict=False
                )
                == body
            ):
                return latest
            rule = ExplainedRule(
                **body.model_dump(),
                cui=cui,
                rule_id=rule_id,
                version=(latest.version + 1) if latest else 1,
            )
            conn.execute(
                "INSERT INTO domain.explained_rules (cui, rule_id, version, body)"
                " VALUES (%s, %s, %s, %s)",
                (cui, rule_id, rule.version, rule.model_dump_json()),
            )
        return rule

    def latest(self, cui: str, rule_id: str) -> ExplainedRule | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.explained_rules WHERE cui = %s AND rule_id = %s"
                " ORDER BY version DESC LIMIT 1",
                (cui, rule_id),
            ).fetchone()
        return ExplainedRule.model_validate(row[0], strict=False) if row else None

    def active(self, cui: str) -> list[ExplainedRule]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT DISTINCT ON (rule_id) body FROM domain.explained_rules WHERE cui = %s"
                " ORDER BY rule_id, version DESC",
                (cui,),
            ).fetchall()
        return [ExplainedRule.model_validate(r[0], strict=False) for r in rows]


# ----- HITL answers that use rules (monthly_close, WP-10) -----


class ExplainedRuleResume(Closed):
    rule_id: Slug


class ControlDispositionResume(Closed):
    control_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    disposition: Literal["explained_rule", "reopen", "hold"]
    rule_id: Slug | None = None


def check_explained_rule(store, cui: str, answer: ExplainedRuleResume) -> str | None:
    """``cannot: hide_unexplained_without_rule`` — the rule must exist for this tenant."""
    if store.latest(cui, answer.rule_id) is None:
        return f"no explained rule {answer.rule_id!r} for {cui}; write it with POST /rules first"
    return None


def check_control_disposition(
    store, cui: str, controls: dict, answer: ControlDispositionResume
) -> str | None:
    """``cannot: clear_blocking_without_rule``."""
    row = controls.get(answer.control_id)
    if row is None:
        return f"unknown control {answer.control_id!r}"
    if answer.disposition == "explained_rule":
        if not answer.rule_id:
            return "disposition explained_rule needs a rule_id"
        if store.latest(cui, answer.rule_id) is None:
            return f"no explained rule {answer.rule_id!r} for {cui}"
    elif answer.rule_id:
        return "rule_id is only given with disposition explained_rule"
    return None
