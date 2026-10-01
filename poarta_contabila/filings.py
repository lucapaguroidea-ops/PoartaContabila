"""Filings (WP-12): what is due for a firm-month, and what closes it.

This system never submits to ANAF. A due item comes from an ArticoleFiling row whose
``require`` / ``forbid`` fit the period's CO.DiT (no CO.DiT → nothing is assumed due).
It closes only when a receipt artefact is stored (``closer: receipt``) — a calendar
date passing closes nothing. Due dates are law facts not pinned here: they stay
``[de confirmat]``. Each item carries its ``books_gate``: whether the controls it names
passed on the period's latest Layer 1 run. Once any receipt exists for a period, no
package is regenerated for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import Field

from poarta_contabila.catalog import Catalog
from poarta_contabila.types import Closed, Cui, FilingItem, Period, Slug

DUE_UNPINNED = "[de confirmat: legal.lock not pinned]"


class FilingView(Closed):
    cui: Cui
    period: Period
    filing_id: Slug
    form: str
    state: str
    receipt_key: str | None = None
    submitted_by: str | None = None
    due: str = DUE_UNPINNED
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

    def open(self, cui: str, period: str, filing_id: str) -> None:
        self.rows.setdefault(
            (cui, period, filing_id), {"state": "open", "receipt_key": None, "submitted_by": None}
        )

    def items(self, cui: str, period: str) -> dict[str, dict[str, Any]]:
        return {f: dict(v) for (c, p, f), v in self.rows.items() if (c, p) == (cui, period)}

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

    def open(self, cui: str, period: str, filing_id: str) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.filing_items (cui, period, filing_id) VALUES (%s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                (cui, period, filing_id),
            )

    def items(self, cui: str, period: str) -> dict[str, dict[str, Any]]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT filing_id, state, receipt_key, submitted_by FROM domain.filing_items"
                " WHERE cui = %s AND period = %s",
                (cui, period),
            ).fetchall()
        return {r[0]: {"state": r[1], "receipt_key": r[2], "submitted_by": r[3]} for r in rows}

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
                certainty=row.get("certainty", "de_confirmat"),
                books_gate=gate,
                books_support=ok,
                note=row.get("note"),
            )
        )
    return out
