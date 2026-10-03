"""reconcile_sink (WP-23): the month's PRE questions, one ``recon:{cui}:{period}`` thread.

    load_window → (nothing waits: end) | ask → apply → load_window …

An ingest Job whose PRE check is not decisive stops at ``needs_human`` (``ingest.py``); this
graph is where a person answers it. No nesting: the glue is the job id (ARCHITECTURE §2).

- **load_window**: the period's jobs stopped at PRE are checked again, deterministically,
  against the books as they are now (``det_match``; a fresh upload counts). A decisive
  verdict goes back to its job by itself, unless the review (``llm_review``) contests it.
  Of what is left, the first question is chosen and stored on the thread before it is
  asked, so a resume answers the same question:
  ``need_rj_export`` (months of the books missing, all jobs at once) before
  ``recon_review_contest`` before ``recon_ambiguous`` (one job, oldest first).
- **ask**: the interrupt; the answer is checked against what was shown.
- **apply**: the person's verdict is stored once per ``(job_id, pre, snapshot)`` and handed
  back: ``already_posted`` → the job is ``already_in_sink``; ``absent`` → its thread goes on
  to ``judge`` and ``v3_approve`` as if the check had said absent.

``absent`` is never concluded for a month the books do not cover (``need_rj_export``
cannot be answered with a verdict). The review never flips a verdict to posted: a
contest only asks a person. Nothing here writes to SAGA.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import Field

from poarta_contabila.catalog import Catalog
from poarta_contabila.hitl import ask
from poarta_contabila.recon.post import PostResult
from poarta_contabila.recon.pre import PreResult
from poarta_contabila.types import CanonicalDocument, Closed, JobRecord

GRAPH_ID = "reconcile_sink"
THREAD_PREFIX = "recon:"
_KINDS = ("need_rj_export", "recon_ambiguous", "recon_review_contest", "recon_how_mismatch")


@dataclass(frozen=True)
class WaitingJob:
    """A job of the window stopped at PRE, with what its ingest thread carries."""

    job: JobRecord
    doc: CanonicalDocument
    fiscal_class: str | None
    axes: dict[str, str]


class Review(Closed):
    """``llm_review``: independent of the extract; it may only confirm, abstain or contest."""

    verdict: Literal["confirm", "contest", "abstain"]
    reason: str = ""


def abstain(job: WaitingJob, det: PreResult) -> Review:
    return Review(verdict="abstain", reason="no reviewer wired")


class NeedExportResume(Closed):
    export_id: str = Field(min_length=1)


class AmbiguousResume(Closed):
    action: Literal["already_posted", "override_absent"]
    sink_line_ids: list[int] = Field(default_factory=list)


class ContestResume(Closed):
    action: Literal["already_posted", "override_absent", "how_ok", "ack_mismatch"]


class HowMismatchResume(Closed):
    ack_mismatch: bool  # SAGA's posting stands as it is
    open_storno: bool  # it must be corrected in SAGA (stays open until the posting changes)


_MODELS = {
    "need_rj_export": NeedExportResume,
    "recon_ambiguous": AmbiguousResume,
    "recon_review_contest": ContestResume,
    "recon_how_mismatch": HowMismatchResume,
}


@dataclass
class ReconDeps:
    catalog: Catalog
    waiting: Callable[[str, str], list[WaitingJob]]
    """(cui, period) → the period's jobs stopped at PRE, oldest first."""
    recheck: Callable[[WaitingJob], PreResult]
    """det_match against the witnesses as they are now (stored once per snapshot)."""
    settle: Callable[[WaitingJob, PreResult], None]
    """Store the final verdict and hand it back to the job's thread."""
    export_months: Callable[[str, str], list[str] | None]
    """(cui, export_id) → the months that upload covers, if it is this tenant's latest
    registru jurnal; else None."""
    review: Callable[[WaitingJob, PreResult], Review] = abstain
    observe_question: Callable[[str, dict, str | None], None] = lambda role_or_kind, payload, cui: (
        None
    )
    """(HITL kind, question, tenant cui): the System Two roles that would explain it."""
    post: PostDeps | None = None  # the POST stage; None = PRE only


@dataclass
class PostDeps:
    """POST stage (WP-27): how SAGA posted the period's acked documents."""

    waiting: Callable[[str, str], list[WaitingJob]]
    """(cui, period) → the period's acked jobs."""
    check: Callable[[WaitingJob], PostResult]
    """how_check against the registru jurnal as it is now."""
    known: Callable[[str, str], bool]
    """(job_id, snapshot_id) → a verdict (det how_ok or a person's answer) is stored for it."""
    settle: Callable[[WaitingJob, PostResult], None]
    """Store a POST verdict once per (job, post, snapshot)."""


class ReconState(TypedDict, total=False):
    cui: str
    period: str
    kind: str
    job_id: str
    question: dict[str, Any]
    det: dict[str, Any]
    settled: list[dict[str, str]]  # PRE entries; POST ones also carry "stage" and "profile_id"
    status: str


def person_result(det: PreResult, verdict: str, reason: str, hits: list[str]) -> PreResult:
    """A person's verdict over a det result: its own snapshot id, so both stay stored."""
    return det.model_copy(
        update={
            "verdict": verdict,
            "reason": f"person: {reason}",
            "snapshot_id": f"{det.snapshot_id}:person",
            "hits": hits,
        }
    )


def build_reconcile_graph(deps: ReconDeps, *, checkpointer: Any):
    cat = deps.catalog
    for kind in _KINDS:
        cat.hitl_kind(kind, graph_id=GRAPH_ID)

    def by_id(cui: str, period: str) -> dict[str, WaitingJob]:
        return {w.job.job_id: w for w in deps.waiting(cui, period)}

    def load_window(state: ReconState, config) -> ReconState:
        cui, period = state["cui"], state["period"]
        want = f"{THREAD_PREFIX}{cui}:{period}"
        thread = str(config["configurable"]["thread_id"])
        if thread != want:
            raise ValueError(f"{GRAPH_ID} runs on {want!r}, got {thread!r}")
        settled = list(state.get("settled") or [])
        missing: dict[str, list[str]] = {}
        contested: list[tuple[WaitingJob, PreResult, Review]] = []
        ambiguous: list[tuple[WaitingJob, PreResult]] = []
        for w in deps.waiting(cui, period):
            det = deps.recheck(w)
            if det.verdict in ("absent", "already_posted"):
                review = deps.review(w, det)
                if review.verdict == "contest":
                    contested.append((w, det, review))
                    continue
                deps.settle(w, det)
                settled.append({"job_id": w.job.job_id, "verdict": det.verdict, "by": "det"})
            elif det.missing:
                missing[w.job.job_id] = det.missing
            else:
                ambiguous.append((w, det))

        mismatches: list[tuple[WaitingJob, PostResult]] = []
        for w in deps.post.waiting(cui, period) if deps.post is not None else []:
            res = deps.post.check(w)
            if deps.post.known(w.job.job_id, res.snapshot_id):
                continue
            if res.verdict == "how_ok":
                deps.post.settle(w, res)
                settled.append(
                    {
                        "job_id": w.job.job_id,
                        "verdict": "how_ok",
                        "by": "det",
                        "stage": "post",
                        "profile_id": res.profile_id,
                    }
                )
            elif res.verdict == "need_rj_export":
                missing[w.job.job_id] = res.missing
            else:
                mismatches.append((w, res))

        if missing:
            months = sorted({m for ms in missing.values() for m in ms})
            question = {
                "cui": cui,
                "period": period,
                "months": months,
                "jobs": sorted(missing),
                "note": "upload the registru jurnal for these months, then name its export_id",
            }
            return {"kind": "need_rj_export", "question": question, "settled": settled}
        if contested:
            w, det, review = contested[0]
            question = {
                "job_id": w.job.job_id,
                "det": det.model_dump(),
                "review": review.model_dump(),
                "document": _brief(w.doc),
            }
            return {
                "kind": "recon_review_contest",
                "job_id": w.job.job_id,
                "det": det.model_dump(),
                "question": question,
                "settled": settled,
            }
        if ambiguous:
            w, det = ambiguous[0]
            shown = [*det.hits, *det.near]
            question = {
                "job_id": w.job.job_id,
                "reason": det.reason,
                "document": _brief(w.doc),
                "sink_lines": [{"id": i, "ref": ref} for i, ref in enumerate(shown)],
                "waiting": len(ambiguous),
            }
            return {
                "kind": "recon_ambiguous",
                "job_id": w.job.job_id,
                "det": det.model_dump(),
                "question": question,
                "settled": settled,
            }
        if mismatches:
            w, res = mismatches[0]
            question = {
                "job_id": w.job.job_id,
                "document": _brief(w.doc),
                "reason": res.reason,
                "expected": res.expected,
                "require_all": res.require_all,
                "used": res.used,
                "journal_rows": res.rows,
                "choices": {
                    "ack_mismatch": "SAGA's posting stands as it is",
                    "open_storno": "it must be corrected in SAGA (stays open until it changes)",
                },
                "waiting": len(mismatches),
            }
            return {
                "kind": "recon_how_mismatch",
                "job_id": w.job.job_id,
                "det": res.model_dump(),
                "question": question,
                "settled": settled,
            }
        return {"kind": "", "status": "clear", "settled": settled}

    def ask_node(state: ReconState) -> ReconState:
        kind, question = state["kind"], state["question"]
        cui = state["cui"]

        def check(answer: Any) -> str | None:
            if kind == "need_rj_export":
                months = deps.export_months(cui, answer.export_id)
                if months is None:
                    return f"{answer.export_id!r} is not the latest registru jurnal of {cui}"
                if not set(months) & set(question["months"]):
                    return f"that export covers {months}, none of {question['months']}"
                return None
            if kind == "recon_ambiguous":
                ids = answer.sink_line_ids
                shown = len(question["sink_lines"])
                if answer.action == "already_posted":
                    if not ids:
                        return "already_posted names the sink line(s) it is posted as"
                    if any(i < 0 or i >= shown for i in ids):
                        return f"sink_line_ids must be among 0..{shown - 1}"
                elif ids:
                    return "override_absent names no sink line"
                return None
            if kind == "recon_how_mismatch":
                if answer.ack_mismatch == answer.open_storno:
                    return "choose ack_mismatch (the posting stands) or open_storno (correct it)"
                return None
            if answer.action in ("how_ok", "ack_mismatch"):
                return "how_ok / ack_mismatch answer a POST question; this one is PRE"
            return None

        deps.observe_question(kind, question, cui)
        answer = ask(kind, question, _MODELS[kind], check)
        return {"status": "answered", "question": {**question, "answer": answer.model_dump()}}

    def apply(state: ReconState) -> ReconState:
        kind = state["kind"]
        settled = list(state.get("settled") or [])
        if kind == "need_rj_export":
            return {"status": "export_named", "settled": settled}  # load_window reads it now
        answer = state["question"]["answer"]
        if kind == "recon_how_mismatch":
            post = deps.post
            w = (
                {x.job.job_id: x for x in post.waiting(state["cui"], state["period"])}
                if post is not None
                else {}
            ).get(state["job_id"])
            if w is None:
                return {"status": "gone", "settled": settled}
            res = PostResult.model_validate(state["det"])
            storno = answer["open_storno"]
            person = res.model_copy(
                update={
                    "reason": "person: storno requested: correct the posting in SAGA"
                    if storno
                    else "person: acknowledged: SAGA's posting stands",
                    "snapshot_id": f"{res.snapshot_id}:person",
                }
            )
            post.settle(w, person)
            verdict = "storno_requested" if storno else "how_mismatch_acknowledged"
            settled.append(
                {
                    "job_id": w.job.job_id,
                    "verdict": verdict,
                    "by": "person",
                    "stage": "post",
                    "profile_id": res.profile_id,
                }
            )
            return {"status": "settled", "settled": settled}
        w = by_id(state["cui"], state["period"]).get(state["job_id"])
        if w is None:  # settled meanwhile (e.g. by another pass): nothing to hand back
            return {"status": "gone", "settled": settled}
        det = PreResult.model_validate(state["det"])
        if answer["action"] == "already_posted":
            if kind == "recon_ambiguous":
                shown = [line["ref"] for line in state["question"]["sink_lines"]]
                hits = [shown[i] for i in answer["sink_line_ids"]]
            else:
                hits = det.hits
            result = person_result(det, "already_posted", f"{kind}: posted as {hits}", hits)
        else:
            result = person_result(det, "absent", f"{kind}: not in the books", [])
        deps.settle(w, result)
        settled.append({"job_id": w.job.job_id, "verdict": result.verdict, "by": "person"})
        return {"status": "settled", "settled": settled}

    def after_load(state: ReconState) -> str:
        return "ask" if state.get("kind") else END

    g = StateGraph(ReconState)
    g.add_node("load_window", load_window)
    g.add_node("ask", ask_node)
    g.add_node("apply", apply)
    g.add_edge(START, "load_window")
    g.add_conditional_edges("load_window", after_load, ["ask", END])
    g.add_edge("ask", "apply")
    g.add_edge("apply", "load_window")
    return g.compile(checkpointer=checkpointer)


def _brief(doc: CanonicalDocument) -> dict[str, Any]:
    return {
        "doc_class": doc.doc_class,
        "number": doc.number,
        "date": doc.date,
        "partner": doc.partner.model_dump(),
        "gross": doc.totals.gross,
    }
