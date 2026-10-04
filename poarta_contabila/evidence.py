"""The evidence ledger: friction and control of one firm-month, from what the runtime stores.

Part D of the plan (BUILD.md) balances two measures per graph, gate and articol:

- **friction**: questions asked of a person, proposals the person changed or refused,
  documents held for a person;
- **control**: errors a gate stopped (an answer that changed or refused what was proposed, a
  control that failed and passed later), errors caught late (SAGA posted it otherwise:
  ``recon_how_mismatch``), and errors that got through (a job acked in SAGA and reopened).

It reads only stored data — the checkpointer (which nodes ran, which edges were taken), the
job status events, the answer log (with what each question proposed), the control runs and the
model calls — and estimates nothing: what it cannot measure is listed under
``not_measured``. No minutes are recorded (BUILD.md Q10).

    GET /evidence/{cui}/{period}
    uv run python -m poarta_contabila.evidence --scenario NAME
    uv run python -m poarta_contabila.evidence --base-url URL CUI PERIOD
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from poarta_contabila.answers import AnswerRecord

NOT_MEASURED = [
    "minutes per question: not recorded (BUILD.md Q10)",
    "errors found after a filing: no correction or rectification is recorded yet",
    "model cost per call: OpenRouter reports spend per key (GET /model-keys), not per call",
]

# What an answer did to what the question proposed, per HITL kind. A kind not listed here has
# no proposal to compare with: its answers count as ``answered``.
VERDICTS = ("as_proposed", "changed", "refused", "held", "answered")
ASKED_AGAIN = "asked_again"


def verdict(kind: str | None, answer: Any, meta: dict[str, Any]) -> str:
    """``as_proposed`` | ``changed`` | ``refused`` | ``held`` | ``answered``."""
    a = answer if isinstance(answer, dict) else {}
    if kind == "v3_approve":
        decision = a.get("decision")
        if decision == "reject":
            return "refused"
        if decision == "edit":
            proposed = meta.get("proposed_edit")
            return (
                "as_proposed" if proposed is not None and a.get("edit") == proposed else "changed"
            )
        return "as_proposed" if decision == "approve" else "answered"
    if kind == "v2_close":
        return {
            "file": "as_proposed",
            "hold": "held",
            "patch_maps": "changed",
            "reopen": "changed",
        }.get(a.get("action"), "answered")
    if kind == "v4_codit":
        if a.get("edit"):
            return "changed"
        if a.get("skip"):
            return "refused"
        return "as_proposed" if a.get("accept") else "answered"
    if kind == "wait_validare":
        return "as_proposed" if a.get("validated") else "refused"
    return "answered"


def judged(meta: dict[str, Any], v: str) -> str | None:
    """Did the person agree with Jev's verdict? ``None`` when Jev gave none."""
    j = meta.get("judge") or {}
    if not j or j.get("risk") in (None, "unknown"):
        return None
    clean = bool(j.get("accounts_ok")) and not j.get("needs_human")
    took_it = v == "as_proposed"
    return "agreed" if clean == took_it else "overridden"


def _threads(rt: Any, cui: str, period: str) -> list[tuple[str, Any, dict]]:
    out = [
        ("ingest_source_doc", rt.ingest, rt._cfg(j.job_id)) for j in rt.jobs.for_period(cui, period)
    ]
    out += [
        ("folder_triage", rt.triage, rt._batch_cfg(b)) for b in rt.batches.for_period(cui, period)
    ]
    out.append(("reconcile_sink", rt.reconcile, rt._recon_cfg(cui, period)))
    out.append(("monthly_close", rt.close, rt._close_cfg(cui, period)))
    return out


def _paths(graph: Any, cfg: dict) -> list[str]:
    """The nodes a thread ran, in order (from its checkpoints)."""
    steps = [s for s in reversed(list(graph.get_state_history(cfg)))]
    nodes: list[str] = []
    for s in steps:
        for n in s.next:
            if n != "__start__" and (not nodes or nodes[-1] != n):
                nodes.append(n)
    return nodes


def _days(start: str, end: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ"
    return round(
        (datetime.strptime(end, fmt) - datetime.strptime(start, fmt)).total_seconds() / 86400, 3
    )


def ledger(rt: Any, cui: str, period: str) -> dict[str, Any]:
    """The evidence ledger of *cui* in *period* (a JSON-able dict)."""
    # ----- graphs: nodes and edges -----
    graphs: dict[str, dict[str, Any]] = {}
    threads = _threads(rt, cui, period)
    thread_ids = set()
    for gid, graph, cfg in threads:
        thread_ids.add(cfg["configurable"]["thread_id"])
        path = _paths(graph, cfg)
        if not path:
            continue
        g = graphs.setdefault(gid, {"threads": 0, "nodes": Counter(), "edges": Counter()})
        g["threads"] += 1
        g["nodes"].update(path)
        g["edges"].update(f"{a} → {b}" for a, b in zip(path, path[1:], strict=False))

    # ----- questions: asked, waiting, what the answers did -----
    answers: list[AnswerRecord] = [
        a for a in rt.answers.recent(cui=cui, limit=1_000_000) if a.thread_id in thread_ids
    ]
    questions: dict[str, Counter] = defaultdict(Counter)
    for a in answers:
        q = questions[a.kind or "?"]
        if a.outcome == "asked_again":
            q[ASKED_AGAIN] += 1
            continue
        if a.outcome != "accepted":
            continue
        v = verdict(a.kind, a.answer, a.meta)
        q["answered_total"] += 1
        q[v] += 1
        j = judged(a.meta, v)
        if j:
            q[f"jev_{j}"] += 1
    for item in rt.inbox(cui, period)["items"]:
        if item["kind"] and (item["job"] is None or item["job"]["period"] == period):
            questions[item["kind"]]["waiting"] += 1
    for q in questions.values():
        q["asked"] = q["answered_total"] + q["waiting"]

    # ----- controls -----
    controls: dict[str, dict[str, Any]] = {}
    if rt.periods is not None:
        by_id: dict[str, list[str]] = defaultdict(list)
        for _sid, run in rt.periods.runs_for(cui, period):
            by_id[run.control_id].append(run.status)
        for cid, statuses in by_id.items():
            resolved = sum(
                1 for i, s in enumerate(statuses) if s == "FAIL" and "PASS" in statuses[i + 1 :]
            )
            controls[cid] = {
                "runs": len(statuses),
                "fail": statuses.count("FAIL"),
                "pass": statuses.count("PASS"),
                "info": statuses.count("INFO"),
                "failed_then_passed": resolved,
                "last": statuses[-1],
            }

    # ----- jobs: articole and the month -----
    jobs = rt.jobs.for_period(cui, period)
    events = rt.jobs.events_for(cui, period)
    by_job: dict[str, list] = defaultdict(list)
    for e in events:
        by_job[e.job_id].append(e)
    articole: dict[str, Counter] = defaultdict(Counter)
    days, reopened_after_ack, held = [], 0, 0
    asked_jobs = {
        a.thread_id.removeprefix("job:") for a in answers if a.thread_id.startswith("job:")
    }
    for j in jobs:
        statuses = [e.status for e in by_job[j.job_id]]
        c = articole[j.articol_id or "(unbound)"]
        c["jobs"] += 1
        held_here = "needs_human" in statuses or j.job_id in asked_jobs
        c["held_for_a_person"] += held_here
        held += held_here
        c[j.status] += 1
        if "acked" in statuses and "reopened" in statuses[statuses.index("acked") :]:
            c["reopened_after_ack"] += 1
            reopened_after_ack += 1
        first, acked = by_job[j.job_id][:1], [e for e in by_job[j.job_id] if e.status == "acked"]
        if first and acked:
            days.append(_days(first[0].at, acked[0].at))

    # ----- model roles (this firm; the calls carry no period) -----
    roles: dict[str, Counter] = defaultdict(Counter)
    if rt.model_calls is not None:
        for call in rt.model_calls.recent(limit=1_000_000):
            if call.tenant_cui == cui:
                roles[call.role_id]["calls"] += 1
                roles[call.role_id][call.status] += 1

    # ----- the two sides -----
    total = Counter()
    for q in questions.values():
        total.update(q)
    late = questions.get("recon_how_mismatch", Counter())["asked"]
    friction = {
        "questions_asked": total["asked"],
        "asked_again": total[ASKED_AGAIN],
        "proposals_changed_or_refused": total["changed"] + total["refused"],
        "documents_held_for_a_person": held,
    }
    control = {
        "stopped_at_a_gate": total["changed"] + total["refused"] + total["held"],
        "controls_failed_then_passed": sum(c["failed_then_passed"] for c in controls.values()),
        "caught_late_by_post": late,
        "got_through_reopened_after_ack": reopened_after_ack,
    }
    return {
        "cui": cui,
        "period": period,
        "friction": friction,
        "control": control,
        "month": {
            "documents": len(jobs),
            "acked": sum(1 for j in jobs if j.status == "acked"),
            "held_for_a_person": held,
            "days_to_validare": {
                "n": len(days),
                "median": statistics.median(days) if days else None,
                "max": max(days) if days else None,
            },
        },
        "graphs": {
            g: {"threads": v["threads"], "nodes": dict(v["nodes"]), "edges": dict(v["edges"])}
            for g, v in sorted(graphs.items())
        },
        "questions": {k: dict(sorted(v.items())) for k, v in sorted(questions.items())},
        "controls": dict(sorted(controls.items())),
        "articole": {k: dict(sorted(v.items())) for k, v in sorted(articole.items())},
        "model_roles": {k: dict(sorted(v.items())) for k, v in sorted(roles.items())},
        "not_measured": NOT_MEASURED,
    }


def render(led: dict[str, Any]) -> str:
    lines = [f"Evidence ledger {led['cui']} {led['period']}", ""]
    lines.append("friction: " + ", ".join(f"{k} {v}" for k, v in led["friction"].items()))
    lines.append("control:  " + ", ".join(f"{k} {v}" for k, v in led["control"].items()))
    m = led["month"]
    d = m["days_to_validare"]
    lines.append(
        f"month:    {m['documents']} documents, {m['acked']} acked, {m['held_for_a_person']} held"
        f" for a person; days to Validare: n={d['n']} median={d['median']} max={d['max']}"
    )
    lines += ["", "graphs (threads; node visits; edges):"]
    for g, v in led["graphs"].items():
        lines.append(f"  {g}: {v['threads']} threads")
        lines.append("    nodes: " + ", ".join(f"{n} {c}" for n, c in v["nodes"].items()))
        lines.append("    edges: " + ", ".join(f"{e} {c}" for e, c in v["edges"].items()))
    lines += ["", "questions:"]
    for k, v in led["questions"].items():
        lines.append(f"  {k}: " + ", ".join(f"{a} {b}" for a, b in v.items()))
    lines += ["", "controls (runs, FAIL, PASS, failed then passed, last):"]
    for k, v in led["controls"].items():
        lines.append(
            f"  {k}: {v['runs']} runs, FAIL {v['fail']}, PASS {v['pass']},"
            f" failed then passed {v['failed_then_passed']}, last {v['last']}"
        )
    lines += ["", "articole:"]
    for k, v in led["articole"].items():
        lines.append(f"  {k}: " + ", ".join(f"{a} {b}" for a, b in v.items()))
    lines += ["", "model roles (this firm, all periods):"]
    for k, v in led["model_roles"].items():
        lines.append(f"  {k}: " + ", ".join(f"{a} {b}" for a, b in v.items()))
    lines += ["", "not measured:"] + [f"  - {x}" for x in led["not_measured"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="poarta_contabila.evidence", description=__doc__.split("\n")[0]
    )
    ap.add_argument("--scenario", help="run this scenario locally, then print its months' ledgers")
    ap.add_argument("--base-url", help="read GET /evidence/{cui}/{period} from a server")
    ap.add_argument("cui", nargs="?")
    ap.add_argument("period", nargs="?")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.scenario:
        from poarta_contabila.scenarios import local_clients, run_one, scenarios
        from poarta_contabila.synthetic.firms import firm

        client, agent = local_clients()
        sc = scenarios([args.scenario])[0]
        run_one(sc, client, agent)
        cui = firm(sc.firm, book_of_record=sc.book_of_record).cui
        leds = [client.get(f"/evidence/{cui}/{p}").json() for p in (sc.months or [sc.period])]
    elif args.base_url and args.cui and args.period:
        import httpx

        token = os.environ.get("GRAPHUSERTOKEN_OPERATOR") or os.environ.get(
            "GRAPHUSERTOKEN_CLAUDE_SYSBUILDER"
        )
        if not token:
            print("set GRAPHUSERTOKEN_OPERATOR or GRAPHUSERTOKEN_CLAUDE_SYSBUILDER")
            return 2
        r = httpx.get(
            f"{args.base_url.rstrip('/')}/evidence/{args.cui}/{args.period}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=120,
        )
        r.raise_for_status()
        leds = [r.json()]
    else:
        ap.error("--scenario NAME, or --base-url URL CUI PERIOD")
    for led in leds:
        print(json.dumps(led, indent=2, ensure_ascii=False) if args.json else render(led))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
