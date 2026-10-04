"""monthly_close: a CloseRun per firm-month, never a Job.

    lock_expected_set → period_diff → layer2 → v2_gate (v2_close) → v4_codit → end

- **lock_expected_set**: the month's expected jobs are hashed and locked once per
  ``(cui, period)``. A later run whose set differs is a lock mismatch: material.
- **period_diff**: Layer 1 against the tenant's eye and rules.
- **layer2**: Layer 2 (Jev, ``v2_declaration_gate``) may only suggest, as JSON that
  validates against :class:`V2Gate`; anything else, an error or a timeout is no suggestion.
  Jev cannot clear ``material``: on a material month its ``file`` and any reading that the
  books are fine are dropped. The suggestion is stored on the thread before ``v2_gate``
  asks, so a resume shows and records the same one without asking Jev again.
- **v2_gate**: a person answers ``v2_close``; ``file`` is refused while Layer 1 is material
  (LAW L25).
- A month with documents still waiting on a ``reconcile_sink`` PRE answer is material
  (blocker at lock): it is answered on ``recon:{cui}:{period}``, never closed around.
- **v4_codit**: only after ``file``. ``skip`` writes nothing; ``accept`` may patch the filed
  period's CO.DiT on ``v4.may_patch`` only (``edit``) and seed the next period's on
  ``v4.seed_next_period_on`` (``seed_next``; an existing next CO.DiT is never overwritten).
  Hard pairs refuse the answer; it is asked again with the reason.
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
from poarta_contabila.codit import CoditError, next_period, v4_patch, v4_rules, v4_seed
from poarta_contabila.hitl import ask
from poarta_contabila.jev import V2Gate
from poarta_contabila.period_diff import ExpectedJob, build_period_diff, can_file
from poarta_contabila.rules import ExplainedRuleResume, check_explained_rule
from poarta_contabila.sinks.saga_eye import SagaEye
from poarta_contabila.types import Closed, Cui, Period, PeriodDiff, Slug

GRAPH_ID = "monthly_close"
THREAD_PREFIX = "close:"

CloseStatus = Literal["opened", "locked", "sink_pulled", "v2_ready", "hold", "filed", "v4_done"]


MAX_DRAFT = 20  # book documents shown to the rule drafter at once


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
    rules: Any = None  # rule store
    period_store: Any = None
    jev_v2: Callable[[PeriodDiff], Any] = lambda diff: None  # Layer 2 (jev.make_v2)
    codit: Callable[[str, str], Any] = lambda cui, period: None  # CO.DiT
    codit_put: Callable[[Any], None] | None = None  # V4 writes CO.DiT through this
    observe_question: Callable[[str, dict, str | None], None] = lambda role_or_kind, payload, cui: (
        None
    )
    """(HITL kind, question, tenant cui): the System Two roles that would explain it."""
    recon_open: Callable[[str, str], list[str]] = lambda cui, period: []
    stalled: Callable[[str, str], list[str]] = lambda cui, period: []
    prior: Callable[[str, str], list[ExpectedJob]] = lambda cui, period: []
    """(cui, period) → the expected jobs of the months before (TVA la încasare)."""
    """(cui, period) → jobs minted with no document on their thread."""
    """(cui, period) → jobs still waiting on a reconcile_sink PRE answer."""


class CloseState(TypedDict, total=False):
    cui: str
    period: str
    axes: dict[str, str]
    diff: dict[str, Any]
    controls: list[dict[str, Any]]
    jev: dict[str, Any] | None
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
        waiting = deps.recon_open(state["cui"], state["period"])
        if waiting:
            blockers.append(
                f"reconcile_sink: {len(waiting)} document(s) wait on a PRE answer"
                f" (POST /recon/{state['cui']}/{state['period']})"
            )
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
            stalled=deps.stalled(cui, period),
            prior=deps.prior(cui, period),
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

    def layer2(state: CloseState) -> CloseState:
        diff = PeriodDiff.model_validate(state["diff"])
        material = bool(_run(state).material) or not can_file(diff)
        return {"jev": _layer2(deps.jev_v2, diff, material)}

    def v2_gate(state: CloseState) -> CloseState:
        cui = state["cui"]
        diff = PeriodDiff.model_validate(state["diff"])
        run = _run(state)
        material = bool(run.material) or not can_file(diff)
        jev = state.get("jev")

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

        question = {
            "cui": cui,
            "period": state["period"],
            "material": material,
            "hard_failures": diff.hard_failures,
            "blockers": run.blockers,
            "outbound_holes": diff.outbound_holes,
            "unexplained": [b.sink.saga_key for b in diff.inbound if b.kind == "unexplained"],
            "jev": jev,
        }
        deps.observe_question("v2_close", question, cui)
        unexplained = [b.sink for b in diff.inbound if b.kind == "unexplained"]
        if unexplained:  # shadow: what the rule drafter would be given
            rules = deps.rules.active(cui) if deps.rules is not None else []
            deps.observe_question(
                "explained_rule",
                {
                    "cui": cui,
                    "period": state["period"],
                    "documents": [d.model_dump(mode="json") for d in unexplained[:MAX_DRAFT]],
                    "rules": [{"rule_id": r.rule_id, "description": r.description} for r in rules],
                },
                cui,
            )
        answer = ask("v2_close", question, V2CloseResume, check)
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
        cui, period = state["cui"], state["period"]
        may_patch, seed_on = v4_rules(cat)
        doc = deps.codit(cui, period)

        def effects(a: V4CoditResume):
            """(patched CO.DiT | None, seeded next CO.DiT | None); raises on a bad answer."""
            if a.accept == a.skip:
                raise ValueError("choose accept or skip")
            if a.skip:
                if a.edit or a.seed_next is not None:
                    raise ValueError("skip writes nothing: leave edit and seed_next empty")
                return None, None
            if (a.edit or a.seed_next is not None) and (doc is None or deps.codit_put is None):
                raise ValueError(f"{period} has no CO.DiT to patch or seed from")
            patched = v4_patch(cat, doc, a.edit) if a.edit else None
            seeded = None
            if a.seed_next is not None:
                base = patched or doc
                seeded = v4_seed(cat, base, a.seed_next, deps.codit(cui, next_period(period)))
            return patched, seeded

        def check(a: V4CoditResume) -> str | None:
            try:
                effects(a)
            except (ValueError, CoditError, ValidationError) as exc:
                return str(exc)
            return None

        answer = ask(
            "v4_codit",
            {
                "cui": cui,
                "period": period,
                "proposal": None
                if doc is None
                else {
                    "may_patch": may_patch,
                    "seed_next_period_on": seed_on,
                    "seed_next": {a: doc.axes[a].model_dump() for a in seed_on if a in doc.axes},
                },
            },
            V4CoditResume,
            check,
        )
        patched, seeded = effects(answer)  # after the answer: writes are replay-safe
        if patched is not None:
            deps.codit_put(patched)
        if seeded is not None:
            deps.codit_put(seeded)
        v4 = {
            **answer.model_dump(),
            "patched_hash": patched.hash if patched else None,
            "seeded_period": seeded.period if seeded else None,
        }
        run = _run(state)
        deps.store.put(run.model_copy(update={"status": "v4_done", "v4": v4}))
        return {"status": "v4_done"}

    def after_v2(state: CloseState) -> str:
        return "v4_codit" if state["status"] == "filed" else END

    g = StateGraph(CloseState)
    g.add_node("lock_expected_set", lock_expected_set)
    g.add_node("period_diff", period_diff)
    g.add_node("layer2", layer2)
    g.add_node("v2_gate", v2_gate)
    g.add_node("v4_codit", v4_codit)
    g.add_edge(START, "lock_expected_set")
    g.add_edge("lock_expected_set", "period_diff")
    g.add_edge("period_diff", "layer2")
    g.add_edge("layer2", "v2_gate")
    g.add_conditional_edges("v2_gate", after_v2, ["v4_codit", END])
    g.add_edge("v4_codit", END)
    return g.compile(checkpointer=checkpointer)


def _layer2(jev: Callable[[PeriodDiff], Any], diff: PeriodDiff, material: bool) -> dict | None:
    """Jev's suggestion if it is valid JSON for V2Gate; it never clears a material month."""
    try:
        raw = jev(diff)
    except Exception as exc:  # fail closed: no suggestion, the person decides
        return {"ignored": f"Layer 2 unavailable: {type(exc).__name__}: {exc}"}
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
    out: dict[str, Any] = gate.model_dump()
    if material:
        dropped = []
        if gate.action == "file":
            out["action"] = None
            dropped.append("action 'file'")
        if gate.gap_materiality != "material":
            out["gap_materiality"] = None
            dropped.append(f"gap_materiality {gate.gap_materiality!r}")
        if gate.books_support_declaration:
            out["books_support_declaration"] = None
            dropped.append("books_support_declaration true")
        if dropped:
            out["ignored"] = "Jev may not clear material: dropped " + ", ".join(dropped)
    return out
