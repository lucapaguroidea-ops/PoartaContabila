"""ArticoleFlux.matches (ARTICOLE_FLUX header): which articol de cale a document is on.

    matches(ctx): status allowed AND date in range AND graph_id
      AND filters exact AND extra_filters exact
      AND require ⊆ ctx.axes AND forbid ∩ ctx.axes = ∅
      AND (ctx.stage unset OR stage = ctx.stage)
    Tie-break: more filters > narrower require > latest valid_from; else HITL.

Only stored fields are read; no model is consulted. ``allow_draft`` admits Lane B
``draft`` rows (no row is ``active`` before its fixture is green).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from poarta_contabila.catalog import Catalog
from poarta_contabila.types import Closed, FiscalDate


class MatchContext(Closed):
    graph_id: str
    fiscal_class: str | None = None
    our_role: str | None = None
    is_storno: bool = False
    our_cui_on_doc: bool | None = None
    axes: dict[str, str] = Field(default_factory=dict)
    day: FiscalDate | None = None
    stage: str | None = None  # reconcile_sink rows: "pre" or "post"


def _allowed_status(row: dict[str, Any], allow_draft: bool) -> bool:
    status = row.get("status", "draft")
    return status == "active" or (allow_draft and status == "draft")


def _in_range(row: dict[str, Any], day: str | None) -> bool:
    if day is None:
        return True
    start, end = row.get("valid_from"), row.get("valid_to")
    return (not start or str(start) <= day) and (not end or day <= str(end))


def _matches(row: dict[str, Any], ctx: MatchContext) -> bool:
    if ctx.stage is not None and row.get("stage") != ctx.stage:
        return False
    for key, want in (row.get("filters") or {}).items():
        if getattr(ctx, key, None) != want:
            return False
    for key, want in (row.get("extra_filters") or {}).items():
        if getattr(ctx, key, None) != want:
            return False
    for axis, values in (row.get("require") or {}).items():
        if ctx.axes.get(axis) not in values:
            return False
    for axis, values in (row.get("forbid") or {}).items():
        if ctx.axes.get(axis) in values:
            return False
    return True


def _rank(row: dict[str, Any]) -> tuple[int, int, str]:
    n_filters = len(row.get("filters") or {}) + len(row.get("extra_filters") or {})
    require = row.get("require") or {}
    narrow = -sum(len(v) for v in require.values()) if require else -(10**6)
    return (n_filters, narrow, str(row.get("valid_from") or ""))


def match_articole(cat: Catalog, ctx: MatchContext, *, allow_draft: bool = True) -> list[str]:
    """Surviving articol ids after the tie-break: one id, or several tied (→ HITL), or none."""
    allowed = cat.graphs[ctx.graph_id].get("allowed_flux") or []
    survivors = [
        (aid, row)
        for aid in allowed
        if (row := cat.articole[aid]).get("graph_id") == ctx.graph_id
        and _allowed_status(row, allow_draft)
        and _in_range(row, ctx.day)
        and _matches(row, ctx)
    ]
    if not survivors:
        return []
    best = max(_rank(row) for _, row in survivors)
    return sorted(aid for aid, row in survivors if _rank(row) == best)
