"""PeriodDiff and ArticoleControls, Layer 1 (WP-08). Not a ledger.

Left operand: the expected set (this period's Jobs and their documents) plus explained
rules (WP-09). Right operand: what the SagaEye shows. Nothing is plugged: a remainder
is a bucket row or a failed control, never an adjusting entry.

- **Buckets.** Every sink document of the period is matched to an expected one (by the
  SAGA key a job carries, else side + number + date + gross) → ``expected``; else to a
  document rule → ``explained_sink_only`` with its ``rule_id`` (WP-09); else
  ``unexplained``. Line rules explain journal movements (bank fees, payroll) on the
  parity side; lines of documents already counted are never counted twice.
- **Outbound holes.** Expected jobs not ``acked`` / ``already_in_sink``.
- **Synthetic parity (C0).** For each watched account, the period turnover the expected
  documents imply (purchase: 401 Cr gross, 4426 Dr VAT; sale: 4111 Dr gross, 4427 Cr
  VAT; a statement line: 5121 on its side) against the eye's turnover. A movement with no
  expected source (a payment on 5121 before bank jobs exist) is a difference, on purpose.
- **A statement line's counterpart (WP-46, owner 2026-10-02).** Bound to a customer it
  implies 4111, to a supplier 401, on the side opposite 5121 (what ``incasare_xml`` /
  ``plata_xml`` post). Never bound (it was already in the books when it arrived), it counts
  the books' own counterpart only when its bank document there is one journal line, 401
  debit for a payment or 4111 credit for a receipt, of exactly the line's amount: the
  statement proves the amount, the books chose the account. Anything else is a difference.
- **Controls.** Each catalog row gives PASS / FAIL / INFO. A blocking control that
  cannot be computed for want of an input it needs FAILs; INFO is only for a control
  that does not apply (its ``require`` axes are absent) or whose precondition
  ("after maps exist") is not met.

``material`` ⇒ V2 ``file`` is impossible (00_LAW 13). Prefile controls gate packaging.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from poarta_contabila.catalog import Catalog
from poarta_contabila.recon.numbers import normalize
from poarta_contabila.rules import ExplainedRule, explained_turnover
from poarta_contabila.sinks.exports import synthetic as synthetic_account
from poarta_contabila.sinks.saga_eye import SagaEye
from poarta_contabila.types import (
    AccountDelta,
    BucketRow,
    CanonicalDocument,
    ControlRun,
    ExpectedItem,
    JobRecord,
    PeriodDiff,
    SinkDoc,
)

_CENT = Decimal("0.01")
_IN = {"intrare", "storn_intrare"}
_OUT = {"iesire", "storn_iesire"}
_DONE = {"acked", "already_in_sink"}
_NOT_EXPECTED = {"rejected"}
_BANK = {"incasare", "plata"}


def _m(d: Decimal) -> str:
    return str(d.quantize(_CENT))


def _side(doc_class: str) -> str:
    return "in" if doc_class in _IN else "out" if doc_class in _OUT else doc_class


@dataclass(frozen=True)
class ExpectedJob:
    job: JobRecord
    doc: CanonicalDocument

    def item(self) -> ExpectedItem:
        d = self.doc
        return ExpectedItem(
            job_id=self.job.job_id,
            doc_class=d.doc_class,
            number=d.number,
            date=d.date,
            partner_cui=d.partner.cui,
            gross=d.totals.gross,
            net=d.totals.net,
            vat=d.totals.vat,
        )


def expected_turnover(items: list[ExpectedItem]) -> dict[str, dict[str, Decimal]]:
    """The turnover the expected documents imply on the watched accounts."""
    t: dict[str, dict[str, Decimal]] = {}

    def add(account: str, side: str, amount: str) -> None:
        t.setdefault(account, {"debit": Decimal(0), "credit": Decimal(0)})[side] += Decimal(amount)

    for it in items:
        if it.doc_class in _IN:
            add("401", "credit", it.gross)
            add("4426", "debit", it.vat)
        elif it.doc_class in _OUT:
            add("4111", "debit", it.gross)
            add("4427", "credit", it.vat)
        elif it.doc_class == "incasare":  # a statement line (WP-13): the bank side only
            add("5121", "debit", it.gross)
        elif it.doc_class == "plata":
            add("5121", "credit", it.gross)
    return t


_COUNTERPART = {"customer": "4111", "supplier": "401"}  # incasare_xml / plata_xml (WP-46)
_POSTED_COUNTERPART = {"incasare": "4111", "plata": "401"}


def bank_counterparts(
    exp: list[ExpectedJob], matched: dict[str, SinkDoc], lines: list[Any]
) -> list[tuple[str, str, Decimal]]:
    """``(account, side, amount)`` the period's statement lines imply opposite 5121 (WP-46).

    *matched*: job id → the bank document the books show for it; *lines*: the month's
    journal lines. A bound line implies its partner's account; a line never bound implies
    the books' own counterpart only when that is one line of the posting account below,
    for exactly the line's amount.
    """
    out = []
    for e in exp:
        d = e.doc
        if d.doc_class not in _BANK:
            continue
        side = "credit" if d.doc_class == "incasare" else "debit"  # opposite the bank
        gross = Decimal(d.totals.gross)
        account = _COUNTERPART.get(d.partner.role)
        if account is not None:
            out.append((account, side, gross))
            continue
        sd = matched.get(e.job.job_id)
        if sd is None:
            continue
        bank_side = "debit" if side == "credit" else "credit"
        mine = [
            ln
            for ln in lines
            if normalize(ln.doc_number, "alnum") == normalize(sd.number, "alnum")
            and ln.date == sd.date
            and synthetic_account(getattr(ln, bank_side) or "") == "5121"
        ]
        if len(mine) != 1:
            continue
        ln = mine[0]
        want = _POSTED_COUNTERPART[d.doc_class]
        if synthetic_account(getattr(ln, side) or "") == want and Decimal(ln.amount) == gross:
            out.append((want, side, gross))
    return out


def _match(exp: list[ExpectedJob], sd: SinkDoc) -> ExpectedJob | None:
    for e in exp:
        if e.job.saga.get("saga_doc_key") == sd.saga_key:
            return e
    if sd.doc_class in _BANK:  # statement lines carry no SAGA number: side + date + amount
        hits = [
            e
            for e in exp
            if e.doc.doc_class == sd.doc_class
            and e.doc.date == sd.date
            and Decimal(e.doc.totals.gross) == Decimal(sd.gross)
        ]
        return hits[0] if len(hits) == 1 else None
    hits = [
        e
        for e in exp
        if _side(e.doc.doc_class) == _side(sd.doc_class)
        and normalize(e.doc.number, "alnum") == normalize(sd.number, "alnum")
        and e.doc.date == sd.date
        and Decimal(e.doc.totals.gross) == Decimal(sd.gross)
    ]
    return hits[0] if len(hits) == 1 else None


def build_period_diff(
    cat: Catalog,
    cui: str,
    period: str,
    expected: list[ExpectedJob],
    eye: SagaEye,
    *,
    axes: dict[str, str] | None = None,
    rules: list[ExplainedRule] | None = None,
) -> tuple[PeriodDiff, list[ControlRun]]:
    """PeriodDiff + one ControlRun per v2/both control row."""
    axes = axes or {}
    rules = [r for r in rules or [] if r.cui == cui and r.applies_to(period)]
    exp = [e for e in expected if e.job.status not in _NOT_EXPECTED]
    items = [e.item() for e in exp]
    covered = eye.covers(cui, period)
    sink_docs = eye.documents(cui, period) if covered else []
    turnover = eye.turnover(cui, period) if covered else {}

    inbound: list[BucketRow] = []
    matched: dict[str, SinkDoc] = {}  # job id → the books' document for it
    explained_docs: list[tuple[SinkDoc, str]] = []
    counted: set[tuple[str | None, str]] = set()  # sink documents whose postings are counted
    month_lines = eye.journal_lines(cui, period) if covered else []
    line_rules = [r for r in rules if r.scope == "line"]
    for sd in sink_docs:
        e = _match(exp, sd)
        if e is None:
            rule = next((r for r in rules if r.scope == "document" and r.matches_doc(sd)), None)
            by_lines = _line_rule_for(sd, month_lines, line_rules) if rule is None else None
            if by_lines is not None:  # its lines are counted by the line rule below
                inbound.append(
                    BucketRow(
                        kind="explained_sink_only",
                        sink=sd,
                        rule_id=by_lines,
                        delta_gross="0.00",
                    )
                )
            elif rule is not None:
                counted.add((normalize(sd.number, "alnum"), sd.date))
                explained_docs.append((sd, rule.rule_id))
                inbound.append(
                    BucketRow(
                        kind="explained_sink_only",
                        sink=sd,
                        rule_id=rule.rule_id,
                        delta_gross="0.00",
                    )
                )
            else:
                inbound.append(BucketRow(kind="unexplained", sink=sd, delta_gross=sd.gross))
        else:
            counted.add((normalize(sd.number, "alnum"), sd.date))
            matched[e.job.job_id] = sd
            inbound.append(
                BucketRow(
                    kind="expected",
                    expected=e.item(),
                    sink=sd,
                    delta_gross=_m(Decimal(sd.gross) - Decimal(e.doc.totals.gross)),
                )
            )
    holes = sorted(e.job.job_id for e in exp if e.job.status not in _DONE)

    control = cat.controls.get("C0_synthetic_parity") or {}
    watched = list(control.get("watched") or [])
    epsilon = Decimal(str(control.get("epsilon", "0.01")))
    implied = expected_turnover(items)
    for account, side, amount in bank_counterparts(exp, matched, month_lines):
        implied.setdefault(account, {"debit": Decimal(0), "credit": Decimal(0)})[side] += amount
    explained_lines = []
    for ln in month_lines if line_rules else []:
        if (normalize(ln.doc_number, "alnum"), ln.date) in counted:
            continue
        if any(r.matches_line(ln) for r in line_rules):
            explained_lines.append(ln)
    for account, sides in explained_turnover(explained_docs, explained_lines).items():
        for side, amount in sides.items():
            implied.setdefault(account, {"debit": Decimal(0), "credit": Decimal(0)})[side] += amount
    synthetic: dict[str, AccountDelta] = {}
    for account in watched:
        for side in ("debit", "credit"):
            want = implied.get(account, {}).get(side, Decimal(0))
            shown = Decimal(turnover.get(account, {}).get(side, "0"))
            if want or shown:
                synthetic[f"{account}:{side}"] = AccountDelta(
                    expected=_m(want), sink=_m(shown), delta=_m(shown - want)
                )

    snapshot_id = hashlib.sha256(
        json.dumps(
            {
                "cui": cui,
                "period": period,
                "covered": covered,
                "expected": [i.model_dump() for i in items],
                "statuses": sorted((e.job.job_id, e.job.status) for e in exp),
                "sink": [d.model_dump() for d in sink_docs],
                "turnover": turnover,
                "axes": axes,
                "rules": sorted((r.rule_id, r.version) for r in rules),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    ctx = _Ctx(
        cui=cui,
        period=period,
        covered=covered,
        eye=eye,
        axes=axes,
        holes=holes,
        inbound=inbound,
        synthetic=synthetic,
        epsilon=epsilon,
        turnover=turnover,
    )
    runs: list[ControlRun] = []
    blockers: list[str] = []
    analytic: dict[str, AccountDelta] = {}
    hard = 0
    for cid, row in cat.controls.items():
        if row.get("layer") not in ("v2", "both"):
            continue
        status, reason, delta = _evaluate(cid, row, ctx, analytic)
        runs.append(
            ControlRun(
                control_id=cid,
                status=status,
                target=delta[0] if delta else None,
                actual=delta[1] if delta else None,
                diff=delta[2] if delta else None,
            )
        )
        if status == "FAIL":
            if row.get("severity") == "blocking":
                hard += 1
                blockers.append(f"{cid}: {reason}")
            else:
                blockers.append(f"{cid} (advisory): {reason}")
    if not covered:
        blockers.insert(0, f"need_rj_export: no export of the books covers {period}")
    material = (
        not covered
        or bool(holes)
        or any(b.kind == "unexplained" for b in inbound)
        or any(abs(Decimal(d.delta)) >= epsilon for d in synthetic.values())
        or hard > 0
    )
    diff = PeriodDiff(
        cui=cui,
        period=period,
        outbound_holes=holes,
        inbound=inbound,
        synthetic_delta=synthetic,
        analytic_delta=analytic,
        material=material,
        blockers=blockers,
        snapshot_id=snapshot_id,
        hard_failures=hard,
    )
    return diff, runs


def _line_rule_for(sd: SinkDoc, lines, line_rules) -> str | None:
    """The line rule explaining every journal line of this sink document, if one does."""
    mine = [
        ln
        for ln in lines
        if normalize(ln.doc_number, "alnum") == normalize(sd.number, "alnum") and ln.date == sd.date
    ]
    if not mine:
        return None
    for rule in line_rules:
        if all(rule.matches_line(ln) for ln in mine):
            return rule.rule_id
    return None


def can_file(diff: PeriodDiff) -> bool:
    """V2 ``file`` is possible only when Layer 1 is clean (00_LAW 13)."""
    return not diff.material and diff.hard_failures == 0


# ----- control evaluation -----


@dataclass
class _Ctx:
    cui: str
    period: str
    covered: bool
    eye: SagaEye
    axes: dict[str, str]
    holes: list[str]
    inbound: list[BucketRow]
    synthetic: dict[str, AccountDelta]
    epsilon: Decimal
    turnover: dict[str, dict[str, str]]


def _balance(row: dict[str, Any] | None) -> Decimal:
    if not row:
        return Decimal(0)
    return Decimal(str(row.get("debit") or "0")) - Decimal(str(row.get("credit") or "0"))


def _tie(ctx: _Ctx, roots: list[str], out: dict[str, AccountDelta]):
    solduri = ctx.eye.solduri(ctx.cui, ctx.period)
    worst = None
    seen = False
    for root in roots:
        analytic = ctx.eye.analytic(ctx.cui, ctx.period, root)
        if not analytic:
            continue
        seen = True
        parent = _balance(solduri.get(root))
        children = sum((_balance(v) for v in analytic.values()), Decimal(0))
        out[root] = AccountDelta(
            expected=_m(parent), sink=_m(children), delta=_m(children - parent)
        )
        if abs(children - parent) >= ctx.epsilon and worst is None:
            worst = (root, parent, children)
    if not seen:
        return "INFO", "no analytic accounts shown yet (after maps exist)", None
    if worst:
        root, parent, children = worst
        return (
            "FAIL",
            f"analytics under {root} sum to {_m(children)}, synthetic is {_m(parent)}",
            (_m(parent), _m(children), _m(children - parent)),
        )
    return "PASS", "", None


def _requires(row: dict[str, Any], axes: dict[str, str]) -> bool:
    return all(axes.get(axis) in values for axis, values in (row.get("require") or {}).items())


def _evaluate(cid: str, row: dict[str, Any], ctx: _Ctx, analytic: dict[str, AccountDelta]):
    if row.get("require") and not _requires(row, ctx.axes):
        return "INFO", "does not apply to this tenant's axes", None
    if not ctx.covered:
        return "FAIL", "no export of the books for the period", None
    if cid == "C0_synthetic_parity":
        bad = [(k, d) for k, d in ctx.synthetic.items() if abs(Decimal(d.delta)) >= ctx.epsilon]
        if not bad:
            return "PASS", "", None
        k, d = bad[0]
        more = f" (+{len(bad) - 1} more)" if len(bad) > 1 else ""
        return (
            "FAIL",
            f"{k} expected {d.expected}, books {d.sink}{more}",
            (d.expected, d.sink, d.delta),
        )
    if cid == "C1_outbound_complete":
        if ctx.holes:
            return "FAIL", f"{len(ctx.holes)} expected job(s) not in the books yet", None
        return "PASS", "", None
    if cid == "C2_unexplained_empty":
        n = sum(1 for b in ctx.inbound if b.kind == "unexplained")
        return (
            ("FAIL", f"{n} document(s) in the books with no source here", None)
            if n
            else (
                "PASS",
                "",
                None,
            )
        )
    if cid in ("M1_1_payables_tie", "M1_2_receivables_tie", "M1_1_trade_ext", "M1_2_trade_ext"):
        return _tie(ctx, list(row.get("watched") or []), analytic)
    if cid == "T_regime_4428":
        tva = ctx.axes.get("tva")
        if tva is None:
            return "FAIL", "TVA regime unknown (CO.DiT axis tva, WP-11)", None
        moved = ctx.turnover.get("4428", {})
        if tva != "tva_platitor" and (_balance(moved) or Decimal(moved.get("debit", "0"))):
            return "FAIL", "4428 moves on a non-payer", None
        return "PASS", "", None
    if cid == "T_regime_442x":
        tva = ctx.axes.get("tva")
        if tva is None:
            return "INFO", "TVA regime unknown (CO.DiT, WP-11)", None
        moved = [a for a in ("4423", "4424") if a in ctx.turnover]
        if tva != "tva_platitor" and moved:
            return "FAIL", f"{', '.join(moved)} move on a non-payer", None
        return "PASS", "", None
    # a control row this code does not compute yet: blocking fails closed
    if row.get("severity") == "blocking":
        return "FAIL", "not computed in v1 (needs an input not built yet)", None
    return "INFO", "not computed in v1", None


# ----- prefile -----


def prefile_failures(cat: Catalog, *, pre_verdict: str | None) -> list[str]:
    """Blocking prefile controls that fail for one job about to be packaged."""
    failed = []
    for cid, row in cat.controls.items():
        if row.get("layer") not in ("prefile", "both") or row.get("severity") != "blocking":
            continue
        if cid == "P_prefile_duplicate" and pre_verdict != "absent":
            failed.append(f"{cid}: PRE verdict is {pre_verdict!r}, not absent")
    if failed and "P_prefile_hard_failures" in cat.controls:
        failed.append(f"P_prefile_hard_failures: {len(failed)} blocking failure(s)")
    return failed


# ----- store -----


@dataclass
class InMemoryPeriodStore:
    diffs: dict[str, PeriodDiff] = None  # type: ignore[assignment]
    runs: dict[tuple[str, str, str, str], ControlRun] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.diffs, self.runs = {}, {}

    def save(self, diff: PeriodDiff, runs: list[ControlRun]) -> None:
        self.diffs.setdefault(diff.snapshot_id, diff)
        for r in runs:
            self.runs.setdefault((diff.cui, diff.period, r.control_id, diff.snapshot_id), r)


class PostgresPeriodStore:
    """``domain.close_snapshots`` (the diff) and ``domain.control_runs`` (one row per control)."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def save(self, diff: PeriodDiff, runs: list[ControlRun]) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.close_snapshots (snapshot_id, cui, period, body)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (snapshot_id) DO NOTHING",
                (diff.snapshot_id, diff.cui, diff.period, diff.model_dump_json()),
            )
            for r in runs:
                conn.execute(
                    "INSERT INTO domain.control_runs (cui, period, control_id, snapshot_id, body)"
                    " VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (diff.cui, diff.period, r.control_id, diff.snapshot_id, r.model_dump_json()),
                )
