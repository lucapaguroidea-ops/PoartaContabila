"""Filings: what is due for a firm-month, and what closes it.

This system never submits to ANAF. A due item comes from an ArticoleFiling row whose
``require`` / ``forbid`` fit the period's CO.DiT (no CO.DiT → nothing is assumed due).
It closes only when a receipt artefact is stored (``closer: receipt``) — a calendar
date passing closes nothing. An item records, when it is opened, what the calendar
(``calendar.obligations``) said of it, in exactly one of three fields: its due date with the
lock set it was computed under (``due``, ``due_lock``), the calendar's refusal reason
(``due_refused``), or, for a quarterly filing whose quarter does not end in the period, why it
is owed later (``due_later``, not a refusal). The due date is information, not a gate: a
refusal blocks neither opening, nor a receipt, nor the close. Each item carries its
``books_gate``: whether the controls it names passed on the period's latest Layer 1 run. Once
any receipt exists for a period, no package is regenerated for it.

Re-opening keeps a recorded due date: it stays with the lock set it was computed under, never
silently rewritten. A corrected pin finds it through that lock set: each store's ``locked()``
lists every item with its ``due_lock``, so ``provenance.impacted_records`` returns the items
dated under a pin (record ``filings``). An open item with no due date recorded (refused, later,
or opened before due dates were recorded) takes the newer answer, so a refusal clears once the
calendar can date the item. A filed item is not touched.

The portfolio calendar (``portfolio``, R45) lists every tenant's items at once, read-only, by
due date: each row holds the tenant key, the form, the period, the due date, the engagement
mode and frequency the CO.DiT gives, the state and the lock-set key; nothing else of the
client. An item with no date is never dropped: refused, later and unrecorded items are listed
apart from the dated ones, each under its own label, with the calendar's reason.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field

from poarta_contabila.catalog import Catalog
from poarta_contabila.lockset import LockSet
from poarta_contabila.types import Closed, Cui, FilingItem, Period, Slug


class FilingView(Closed):
    cui: Cui
    period: Period
    filing_id: Slug
    form: str
    state: str
    receipt_key: str | None = None
    submitted_by: str | None = None
    due: str | None = None  # ISO date the calendar gave when the item was opened
    due_lock: dict[str, str | None] | None = None  # the lock set that due date was computed under
    due_refused: str | None = None  # the calendar's reason when it refused a date
    due_later: str | None = None  # why it is owed later (its quarter does not end in the period)
    certainty: str
    books_gate: dict[str, str] = Field(default_factory=dict)
    books_support: bool
    note: str | None = None


def due_filings(cat: Catalog, axes: dict[str, str]) -> list[dict[str, Any]]:
    """Catalog rows that apply to these CO.DiT axes. An unset axis satisfies no ``require``."""
    rows = (cat.docs.get("ArticoleFiling") or {}).get("filings") or []
    out = []
    for row in rows:
        req = row.get("require") or {}
        forbid = row.get("forbid") or {}
        if all(axes.get(a) in v for a, v in req.items()) and not any(
            axes.get(a) in v for a, v in forbid.items()
        ):
            out.append(row)
    return out


def books_gate(row: dict[str, Any], controls: dict[str, str]) -> tuple[dict[str, str], bool]:
    """Each gate control's latest status; supported only if every one PASSed."""
    gate = {cid: controls.get(cid, "not run") for cid in row.get("books_gate") or []}
    return gate, all(s == "PASS" for s in gate.values())


# ----- store -----


@dataclass
class InMemoryFilingStore:
    rows: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)

    def open(
        self,
        cui: str,
        period: str,
        filing_id: str,
        *,
        due: str | None = None,
        due_lock: dict[str, str | None] | None = None,
        due_refused: str | None = None,
        due_later: str | None = None,
    ) -> None:
        answer = {
            "due": due,
            "due_lock": due_lock,
            "due_refused": due_refused,
            "due_later": due_later,
        }
        row = self.rows.get((cui, period, filing_id))
        if row is None:
            self.rows[(cui, period, filing_id)] = {
                "state": "open",
                "receipt_key": None,
                "submitted_by": None,
                **answer,
            }
        elif row["state"] == "open" and row.get("due") is None:
            row.update(answer)  # a recorded due date is kept; a missing one takes the answer

    def items(self, cui: str, period: str) -> dict[str, dict[str, Any]]:
        return {f: dict(v) for (c, p, f), v in self.rows.items() if (c, p) == (cui, period)}

    def every_item(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        """Every tenant's items, ``(cui, period, filing_id)`` → the calendar's answer and state
        (the portfolio calendar; neither the receipt nor who submitted it)."""
        return {k: {f: v.get(f) for f in PORTFOLIO_READ} for k, v in sorted(self.rows.items())}

    def locked(self) -> list[tuple[tuple[str, ...], LockSet | None]]:
        """``((cui, period, filing_id), lock set or None)`` per item: the lock set its due date
        was computed under, None when the calendar gave it no date (provenance.py)."""
        return [(k, LockSet.from_dict(v.get("due_lock"))) for k, v in sorted(self.rows.items())]

    def receipt(self, cui: str, period: str, filing_id: str, key: str, by: str) -> None:
        row = self.rows.get((cui, period, filing_id))
        if row is None:
            raise KeyError(filing_id)
        row.update(state="filed", receipt_key=key, submitted_by=by)

    def has_receipt(self, cui: str, period: str) -> bool:
        return any(v["state"] == "filed" for v in self.items(cui, period).values())


class PostgresFilingStore:
    """``domain.filing_items``: ``filed`` needs a receipt (CHECK constraint)."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def open(
        self,
        cui: str,
        period: str,
        filing_id: str,
        *,
        due: str | None = None,
        due_lock: dict[str, str | None] | None = None,
        due_refused: str | None = None,
        due_later: str | None = None,
    ) -> None:
        lock = json.dumps(due_lock) if due_lock is not None else None
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.filing_items"
                " (cui, period, filing_id, due, due_lock, due_refused, due_later)"
                " VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)"
                " ON CONFLICT (cui, period, filing_id) DO UPDATE SET due = EXCLUDED.due,"
                " due_lock = EXCLUDED.due_lock, due_refused = EXCLUDED.due_refused,"
                " due_later = EXCLUDED.due_later"
                " WHERE domain.filing_items.state = 'open' AND domain.filing_items.due IS NULL",
                (cui, period, filing_id, due, lock, due_refused, due_later),
            )

    def items(self, cui: str, period: str) -> dict[str, dict[str, Any]]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT filing_id, state, receipt_key, submitted_by, due, due_lock, due_refused,"
                " due_later FROM domain.filing_items WHERE cui = %s AND period = %s",
                (cui, period),
            ).fetchall()
        return {
            r[0]: {
                "state": r[1],
                "receipt_key": r[2],
                "submitted_by": r[3],
                "due": r[4],
                "due_lock": json.loads(r[5]) if isinstance(r[5], str) else r[5],
                "due_refused": r[6],
                "due_later": r[7],
            }
            for r in rows
        }

    def every_item(self) -> dict[tuple[str, str, str], dict[str, Any]]:
        """Every tenant's items, ``(cui, period, filing_id)`` → the calendar's answer and state
        (the portfolio calendar; neither the receipt nor who submitted it)."""
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT cui, period, filing_id, state, due, due_lock, due_refused, due_later"
                " FROM domain.filing_items ORDER BY cui, period, filing_id"
            ).fetchall()
        return {
            (r[0], r[1], r[2]): {
                "state": r[3],
                "due": r[4],
                "due_lock": json.loads(r[5]) if isinstance(r[5], str) else r[5],
                "due_refused": r[6],
                "due_later": r[7],
            }
            for r in rows
        }

    def locked(self) -> list[tuple[tuple[str, ...], LockSet | None]]:
        """``((cui, period, filing_id), lock set or None)`` per item: the lock set its due date
        was computed under, None when the calendar gave it no date (provenance.py)."""
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT cui, period, filing_id, due_lock FROM domain.filing_items"
                " ORDER BY cui, period, filing_id"
            ).fetchall()
        return [
            ((c, p, f), LockSet.from_dict(json.loads(lk) if isinstance(lk, str) else lk))
            for c, p, f, lk in rows
        ]

    def receipt(self, cui: str, period: str, filing_id: str, key: str, by: str) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            done = conn.execute(
                "UPDATE domain.filing_items SET state = 'filed', receipt_key = %s,"
                " submitted_by = %s WHERE cui = %s AND period = %s AND filing_id = %s"
                " RETURNING 1",
                (key, by, cui, period, filing_id),
            ).fetchone()
        if done is None:
            raise KeyError(filing_id)

    def has_receipt(self, cui: str, period: str) -> bool:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT 1 FROM domain.filing_items WHERE cui = %s AND period = %s"
                " AND state = 'filed' LIMIT 1",
                (cui, period),
            ).fetchone()
        return row is not None


def views(
    cat: Catalog,
    cui: str,
    period: str,
    items: dict[str, dict[str, Any]],
    controls: dict[str, str],
) -> list[FilingView]:
    rows = {r["filing_id"]: r for r in (cat.docs.get("ArticoleFiling") or {}).get("filings") or []}
    out = []
    for fid, item in sorted(items.items()):
        row = rows.get(fid, {})
        gate, ok = books_gate(row, controls)
        FilingItem(
            filing_id=fid, period=period, state=item["state"], receipt_key=item["receipt_key"]
        )  # the domain type's own checks
        out.append(
            FilingView(
                cui=cui,
                period=period,
                filing_id=fid,
                form=row.get("form", "?"),
                state=item["state"],
                receipt_key=item["receipt_key"],
                submitted_by=item.get("submitted_by"),
                due=item.get("due"),
                due_lock=item.get("due_lock"),
                due_refused=item.get("due_refused"),
                due_later=item.get("due_later"),
                certainty=row.get("certainty", "de_confirmat"),
                books_gate=gate,
                books_support=ok,
                note=row.get("note"),
            )
        )
    return out


# ----- the portfolio calendar (R45) -----

PORTFOLIO_READ = ("state", "due", "due_lock", "due_refused", "due_later")  # what a store gives
Dating = Literal["dated", "later", "refused", "unrecorded"]
GROUPS: tuple[Dating, ...] = ("dated", "later", "refused", "unrecorded")


class PortfolioItem(Closed):
    """One filing item on the portfolio calendar. The tenant key is the only client field: no
    name, address, amount, receipt or person (R45)."""

    tenant: Cui  # the tenant key
    filing_id: Slug
    form: str
    period: Period  # the firm-month the item was opened for
    due: str | None  # ISO date, only when ``dating`` is ``dated``
    dating: Dating  # dated | later (owed once its quarter ends) | refused | unrecorded
    reason: str | None  # the calendar's reason when it gave no date
    mode: str | None  # the CO.DiT ``engagement`` axis of that period; None when unset
    frequency: str | None  # lunar | trimestrial, from the term and the CO.DiT; None when unknown
    state: str  # open | filed
    lock: str | None  # the key of the lock set the due date was computed under


PORTFOLIO_FIELDS: tuple[str, ...] = tuple(PortfolioItem.model_fields)


def _frequencies(cat: Catalog) -> dict[str, tuple[str, str | None]]:
    """form → (the term's frequency, its CO.DiT axis); malformed rows are skipped, never fixed:
    the calendar's own refusal already says what is wrong with them."""
    out: dict[str, tuple[str, str | None]] = {}
    for row in (cat.docs.get("ArticoleTerms") or {}).get("terms") or []:
        if isinstance(row, dict) and isinstance(row.get("form"), str):
            freq = row.get("frequency")
            if isinstance(freq, str):
                out.setdefault(row["form"], (freq, row.get("frequency_axis")))
    return out


def _dating(item: dict[str, Any]) -> tuple[Dating, str | None]:
    if item.get("due"):
        return "dated", None
    if item.get("due_later"):
        return "later", item["due_later"]
    if item.get("due_refused"):
        return "refused", item["due_refused"]
    return "unrecorded", "opened before due dates were recorded; open the period again"


def portfolio(
    cat: Catalog,
    items: dict[tuple[str, str, str], dict[str, Any]],
    axes: Callable[[str, str], dict[str, str]],
    *,
    keep: Callable[[str], bool] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Every tenant's filing items, grouped by ``dating``: the dated ones by due date (then
    tenant and form, for a stable order), the others apart, each with its reason.

    Nothing is computed here: the due date and reason are what the calendar recorded when the
    item was opened, the mode and frequency what the period's CO.DiT says
    (``axes(cui, period)``). *keep*, when given, keeps only the tenant keys it accepts."""
    forms = {
        r["filing_id"]: r.get("form", "?")
        for r in (cat.docs.get("ArticoleFiling") or {}).get("filings") or []
    }
    freqs = _frequencies(cat)
    out: dict[str, list[PortfolioItem]] = {g: [] for g in GROUPS}
    for (cui, period, fid), item in items.items():
        if keep is not None and not keep(cui):
            continue
        form = forms.get(fid, "?")
        found = axes(cui, period)
        freq, axis = freqs.get(form, (None, None))
        frequency = found.get(axis) if freq == "from_axis" and axis else freq
        dating, reason = _dating(item)
        lock = LockSet.from_dict(item.get("due_lock")) if dating == "dated" else None
        out[dating].append(
            PortfolioItem(
                tenant=cui,
                filing_id=fid,
                form=form,
                period=period,
                due=item.get("due") if dating == "dated" else None,
                dating=dating,
                reason=reason,
                mode=found.get("engagement"),
                frequency=frequency if frequency != "from_axis" else None,
                state=item["state"],
                lock=lock.key if lock is not None else None,
            )
        )
    # by due date only: any further order (mode, blocking items) is the accountant's (H-08)
    out["dated"].sort(key=lambda i: (i.due or "", i.tenant, i.form, i.filing_id))
    for g in GROUPS[1:]:
        out[g].sort(key=lambda i: (i.tenant, i.period, i.form, i.filing_id))
    return {g: [i.model_dump() for i in rows] for g, rows in out.items()}
