"""monthly_close (WP-10): a CloseRun per firm-month, never a Job.

    lock_expected_set → period_diff → v2_gate (v2_close) → v4_codit → end

- **lock_expected_set**: the month's expected jobs are hashed and locked once per
  ``(cui, period)``. A later run whose set differs is a lock mismatch: material.
- **period_diff**: Layer 1 (WP-08/09) against the tenant's eye and rules.
- **v2_gate**: Layer 2 (Jev, ``v2_declaration_gate``) may only suggest, as JSON that
  validates against :class:`V2Gate`; anything else is ignored. Jev cannot clear
  ``material``: its ``file`` on a material month is dropped. Then a person answers
  ``v2_close``; ``file`` is refused while Layer 1 is material (00_LAW 13).
- **v4_codit**: only after ``file``; the CO.DiT answer is recorded (CO.DiT itself, WP-11).
  ``reopen`` releases the lock so the next run takes the month's jobs afresh.

Runs on ``close:{cui}:{period}`` threads only.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import Field, ValidationError

from poarta_contabila.catalog import Catalog
from poarta_contabila.hitl import ask
from poarta_contabila.period_diff import ExpectedJob, build_period_diff, can_file
from poarta_contabila.rules import ExplainedRuleResume, check_explained_rule
from poarta_contabila.sinks.saga_eye import SagaEye
from poarta_contabila.types import Closed, Cui, Period, PeriodDiff, Slug

GRAPH_ID = "monthly_close"
THREAD_PREFIX = "close:"

CloseStatus = Literal["opened", "locked", "sink_pulled", "v2_ready", "hold", "filed", "v4_done"]


class V2Gate(Closed):
    """Layer 2 output (``v2_declaration_gate``): JSON only, a suggestion."""

    books_support_declaration: bool
    gap_materiality: Literal["none", "immaterial", "material"]
    action: Literal["file", "hold", "patch_maps", "reopen"]


class V2CloseResume(Closed):
    action: Literal["file", "hold", "patch_maps", "reopen"]
    explained_rule: Slug | None = None


class V4CoditResume(Closed):
    accept: bool
    skip: bool
    edit: dict[str, Any] | None = None
    seed_next: dict[str, Any] | None = None


class CloseRun(Closed):
    cui: Cui
    period: Period
    status: CloseStatus = "opened"
    close_kind: Slug | None = None
    expected_set_hash: str | None = None
    snapshot_id: str | None = None
    material: bool | None = None
    blockers: list[str] = Field(default_factory=list)
    jev: dict[str, Any] | None = None
    v2_action: str | None = None
    explained_rule: Slug | None = None
    v4: dict[str, Any] | None = None


# ----- store -----


@dataclass
class InMemoryCloseStore:
    rows: dict[tuple[str, str], CloseRun] = field(default_factory=dict)

    def get(self, cui: str, period: str) -> CloseRun | None:
        return self.rows.get((cui, period))

    def put(self, run: CloseRun) -> None:
        self.rows[(run.cui, run.period)] = run


class PostgresCloseStore:
    """``domain.close_runs`` (one row per ``(cui, period)``)."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def get(self, cui: str, period: str) -> CloseRun | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.close_runs WHERE cui = %s AND period = %s",
                (cui, period),
            ).fetchone()
        return CloseRun.model_validate(row[0], strict=False) if row else None

    def put(self, run: CloseRun) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.close_runs (cui, period, expected_set_hash, body)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (cui, period) DO UPDATE"
                " SET expected_set_hash = EXCLUDED.expected_set_hash, body = EXCLUDED.body",
                (run.cui, run.period, run.expected_set_hash, run.model_dump_json()),
            )


# ----- graph -----


@dataclass
class CloseDeps:
    catalog: Catalog
    store: Any  # InMemoryCloseStore | PostgresCloseStore
    expected: Callable[[str, str], list[ExpectedJob]]
    eye: Callable[[str, str], SagaEye]
    rules: Any = None  # rule store (WP-09)
    period_store: Any = None
    jev_v2: Callable[[PeriodDiff], Any] = lambda diff: None  # Layer 2; not wired yet
    codit: Callable[[str, str], Any] = lambda cui, period: None  # CO.DiT (WP-11)


class CloseState(TypedDict, total=False):
    cui: str
    period: str
    axes: dict[str, str]
    diff: dict[str, Any]
    controls: list[dict[str, Any]]
    status: str


def expected_set_hash(expected: list[ExpectedJob]) -> str:
    body = sorted(
        (e.job.job_id, e.job.status, e.doc.totals.gross)
        for e in expected
        if e.job.status != "rejected"
    )
    return hashlib.sha256(json.dumps(body).encode()).hexdigest()


def close_kind(cat: Catalog, axes: dict[str, str]) -> str | None:
    """The one ArticoleClose kind whose require/forbid fit the tenant's axes."""
    kinds = (cat.docs.get("ArticoleClose") or {}).get("kinds") or []
    fits = [
        k["close_kind"]
        for k in kinds
        if all(axes.get(a) in v for a, v in (k.get("require") or {}).items())
        and not any(axes.get(a) in v for a, v in (k.get("forbid") or {}).items())
    ]
    return fits[0] if len(fits) == 1 else None


def build_close_graph(deps: CloseDeps, *, checkpointer: Any):
    cat = deps.catalog
    for kind in ("v2_close", "v4_codit"):
        cat.hitl_kind(kind, graph_id=GRAPH_ID)

    def _run(state: CloseState) -> CloseRun:
        return deps.store.get(state["cui"], state["period"]) or CloseRun(
            cui=state["cui"], period=state["period"]
        )

    def lock_expected_set(state: CloseState, config) -> CloseState:
        thread = str(config["configurable"]["thread_id"])
        want = f"{THREAD_PREFIX}{state['cui']}:{state['period']}"
        if thread != want:
            raise ValueError(f"{GRAPH_ID} runs on {want!r}, got {thread!r}")
        run = _run(state)
        current = expected_set_hash(deps.expected(state["cui"], state["period"]))
        blockers = []
        if run.expected_set_hash and run.expected_set_hash != current:
            blockers.append("lock mismatch: the month's jobs changed since the lock; reopen first")
        doc = deps.codit(state["cui"], state["period"])
        axes = doc.derive() if doc is not None else (state.get("axes") or {})
        kind = close_kind(cat, axes)
        if kind is None:
            blockers.append("no close kind fits the period's CO.DiT (tva/exig)")
        if doc is not None:
            blockers += [f"CO.DiT {flag} blocks filing" for flag in doc.blocks_file]
        run = run.model_copy(
            update={
                "status": "locked",
                "close_kind": kind,
                "expected_set_hash": run.expected_set_hash or current,
                "blockers": blockers,
            }
        )
        deps.store.put(run)
        return {"status": "locked", "axes": axes}

    def period_diff(state: CloseState) -> CloseState:
        cui, period = state["cui"], state["period"]
        run = _run(state)
        rules = deps.rules.active(cui) if deps.rules is not None else []
        diff, runs = build_period_diff(
            cat,
            cui,
            period,
            deps.expected(cui, period),
            deps.eye(cui, period),
            axes=state.get("axes") or {},
            rules=rules,
        )
        if deps.period_store is not None:
            deps.period_store.save(diff, runs)
        material = diff.material or bool(run.blockers)
        deps.store.put(
            run.model_copy(
                update={
                    "status": "v2_ready",
                    "snapshot_id": diff.snapshot_id,
                    "material": material,
                    "blockers": run.blockers + diff.blockers,
                }
            )
        )
        return {
            "diff": diff.model_dump(),
            "controls": [r.model_dump() for r in runs],
            "status": "v2_ready",
        }

    def v2_gate(state: CloseState) -> CloseState:
        cui = state["cui"]
        diff = PeriodDiff.model_validate(state["diff"])
        run = _run(state)
        material = bool(run.material) or not can_file(diff)
        jev = _layer2(deps.jev_v2, diff, material)

        def check(answer: V2CloseResume) -> str | None:
            if answer.action == "file" and material:
                return "cannot file: Layer 1 is material (" + "; ".join(run.blockers[:3]) + ")"
            if answer.explained_rule and deps.rules is not None:
                return check_explained_rule(
                    deps.rules, cui, ExplainedRuleResume(rule_id=answer.explained_rule)
                )
            if answer.explained_rule and deps.rules is None:
                return "no rule store wired"
            return None

        answer = ask(
            "v2_close",
            {
                "cui": cui,
                "period": state["period"],
                "material": material,
                "hard_failures": diff.hard_failures,
                "blockers": run.blockers,
                "outbound_holes": diff.outbound_holes,
                "unexplained": [b.sink.saga_key for b in diff.inbound if b.kind == "unexplained"],
                "jev": jev,
            },
            V2CloseResume,
            check,
        )
        status: CloseStatus = {"file": "filed", "reopen": "opened"}.get(answer.action, "hold")
        update: dict[str, Any] = {
            "status": status,
            "jev": jev,
            "v2_action": answer.action,
            "explained_rule": answer.explained_rule,
        }
        if answer.action == "reopen":
            update["expected_set_hash"] = None  # the next run locks the month afresh
        deps.store.put(run.model_copy(update=update))
        return {"status": status}

    def v4_codit(state: CloseState) -> CloseState:
        answer = ask(
            "v4_codit",
            {"cui": state["cui"], "period": state["period"], "proposal": None},
            V4CoditResume,
            lambda a: "choose accept or skip, not both" if a.accept and a.skip else None,
        )
        run = _run(state)
        deps.store.put(run.model_copy(update={"status": "v4_done", "v4": answer.model_dump()}))
        return {"status": "v4_done"}

    def after_v2(state: CloseState) -> str:
        return "v4_codit" if state["status"] == "filed" else END

    g = StateGraph(CloseState)
    g.add_node("lock_expected_set", lock_expected_set)
    g.add_node("period_diff", period_diff)
    g.add_node("v2_gate", v2_gate)
    g.add_node("v4_codit", v4_codit)
    g.add_edge(START, "lock_expected_set")
    g.add_edge("lock_expected_set", "period_diff")
    g.add_edge("period_diff", "v2_gate")
    g.add_conditional_edges("v2_gate", after_v2, ["v4_codit", END])
    g.add_edge("v4_codit", END)
    return g.compile(checkpointer=checkpointer)


def _layer2(jev: Callable[[PeriodDiff], Any], diff: PeriodDiff, material: bool) -> dict | None:
    """Jev's suggestion if it is valid JSON for V2Gate; never a ``file`` on a material month."""
    raw = jev(diff)
    if raw is None:
        return None
    try:
        gate = (
            V2Gate.model_validate_json(raw)
            if isinstance(raw, str | bytes)
            else (V2Gate.model_validate(raw))
        )
    except ValidationError as exc:
        return {"ignored": f"not V2Gate JSON: {exc.error_count()} error(s)"}
    out = gate.model_dump()
    if material and gate.action == "file":
        out["ignored"] = "Jev may not clear material: its file is dropped"
        out["action"] = None
    return out
