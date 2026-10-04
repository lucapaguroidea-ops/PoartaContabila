"""reconcile_sink — the month's undecided PRE checks, answered on recon:{cui}:{period}."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from poarta_contabila.catalog import load_catalog
from poarta_contabila.reconcile import ReconDeps, Review, build_reconcile_graph
from tests.test_runtime import CUI, INVOICE, Ops, _runtime, _spv_zip

PERIOD = "2026-09"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _recon(o, body=None):
    if body is None:
        return o.http.post(f"/recon/{CUI}/{PERIOD}", headers=o.op).json()
    return o.http.post(f"/recon/{CUI}/{PERIOD}/resume", json=body, headers=o.op).json()


def _job(o, job_id):
    return o.http.get(f"/jobs/{job_id}", headers=o.op).json()


# ----- need_rj_export -----


def test_missing_books_ask_for_the_export_then_the_job_goes_on(cat):
    o = Ops(_runtime(cat))
    o.tenant()
    job_id = o.ingest().json()["job"]["job_id"]  # no books yet: PRE cannot say absent
    view = _recon(o)
    q = view["question"]
    assert q["kind"] == "need_rj_export" and q["months"] == [PERIOD] and q["jobs"] == [job_id]

    assert (
        "not the latest registru jurnal" in _recon(o, {"export_id": "rj:nope"})["question"]["error"]
    )
    export_id = o.upload_rj().json()["export_id"]
    view = _recon(o, {"export_id": export_id})
    assert view["question"] is None and view["waiting"] == []
    assert view["settled"] == [{"job_id": job_id, "verdict": "absent", "by": "det"}]
    after = _job(o, job_id)
    assert after["job"]["status"] == "reconcile_pre"  # its own thread went on …
    assert after["question"]["kind"] == "v3_approve"  # … to the person's approval


def _graph(cat, rt, **over):
    deps = {
        "catalog": cat,
        "waiting": rt.recon_waiting,
        "recheck": lambda w: rt.deps.pre_check(
            w.job, w.doc, fiscal_class=w.fiscal_class, axes=w.axes
        ),
        "settle": rt._settle_pre,
        "export_months": rt._rj_export_months,
        **over,
    }
    graph = build_reconcile_graph(ReconDeps(**deps), checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": f"recon:{CUI}:{PERIOD}"}}

    def question():
        tasks = graph.get_state(cfg).tasks
        return tasks[0].interrupts[0].value if tasks and tasks[0].interrupts else None

    return graph, cfg, question


def test_an_export_that_covers_none_of_the_months_is_refused(cat):
    o = Ops(_runtime(cat))
    o.tenant()
    job_id = o.ingest().json()["job"]["job_id"]
    graph, cfg, question = _graph(cat, o.rt, export_months=lambda cui, eid: ["2026-08"])
    graph.invoke({"cui": CUI, "period": PERIOD, "settled": []}, cfg)
    assert question()["kind"] == "need_rj_export"
    graph.invoke(Command(resume={"export_id": "rj:x"}), cfg)
    assert "none of ['2026-09']" in question()["error"]
    assert _job(o, job_id)["job"]["status"] == "needs_human"


# ----- recon_ambiguous -----


def _close_call(cat):
    o = Ops(_runtime(cat))
    o.tenant()
    o.upload_rj()
    # AB 0058 of 2026-09-10 is in the journal with another gross: close, not decisive
    out = o.ingest(_spv_zip(INVOICE)).json()
    assert out["job"]["status"] == "needs_human"
    return o, out["job"]["job_id"]


def test_a_close_call_is_asked_with_the_sink_lines_shown(cat):
    o, job_id = _close_call(cat)
    q = _recon(o)["question"]
    assert q["kind"] == "recon_ambiguous" and q["job_id"] == job_id
    assert q["document"]["number"] == "AB 0058" and q["sink_lines"]
    assert q["sink_lines"][0]["id"] == 0


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ({"action": "already_posted", "sink_line_ids": []}, "names the sink line"),
        ({"action": "already_posted", "sink_line_ids": [99]}, "must be among"),
        ({"action": "override_absent", "sink_line_ids": [0]}, "names no sink line"),
        ({"action": "absent"}, "action"),
    ],
)
def test_an_answer_that_does_not_fit_what_was_shown_is_asked_again(cat, body, match):
    o, job_id = _close_call(cat)
    _recon(o)
    q = _recon(o, body)["question"]
    assert q["kind"] == "recon_ambiguous" and match in str(q["error"])
    assert _job(o, job_id)["job"]["status"] == "needs_human"


def test_already_posted_closes_the_job_without_a_package(cat):
    o, job_id = _close_call(cat)
    ref = _recon(o)["question"]["sink_lines"][0]["ref"]
    view = _recon(o, {"action": "already_posted", "sink_line_ids": [0]})
    assert view["question"] is None and view["waiting"] == []
    assert view["settled"][-1] == {"job_id": job_id, "verdict": "already_posted", "by": "person"}
    after = _job(o, job_id)
    assert after["job"]["status"] == "already_in_sink" and after["question"] is None
    stored = [r for (j, st, _), r in o.rt.recon.rows.items() if j == job_id and st == "pre"]
    person = [r for r in stored if r.reason.startswith("person:")]
    assert person and person[0].hits == [ref]  # the det verdict is kept beside it
    assert o.rt.blobs.puts == 2  # export + source; no package


def test_override_absent_sends_the_job_on_to_approval(cat):
    o, job_id = _close_call(cat)
    _recon(o)
    view = _recon(o, {"action": "override_absent", "sink_line_ids": []})
    assert view["question"] is None
    after = _job(o, job_id)
    assert after["question"]["kind"] == "v3_approve"
    view = o.resume(job_id, {"decision": "approve", "edit": None})
    assert view["job"]["status"] == "packaged"


def test_a_second_pass_with_nothing_waiting_asks_nothing(cat):
    o, _ = _close_call(cat)
    _recon(o)
    _recon(o, {"action": "override_absent", "sink_line_ids": []})
    view = _recon(o)
    assert view["question"] is None and view["waiting"] == []


def test_recon_runs_only_on_its_own_thread(cat):
    o = Ops(_runtime(cat))
    with pytest.raises(ValueError, match="recon:"):
        o.rt.reconcile.invoke(
            {"cui": CUI, "period": PERIOD, "settled": []},
            {"configurable": {"thread_id": f"close:{CUI}:{PERIOD}"}},
        )


# ----- llm_review: confirm / abstain keep det; contest only asks -----


def test_a_contested_det_verdict_is_asked_not_flipped(cat):
    o = Ops(_runtime(cat))
    o.tenant()
    job_id = o.ingest().json()["job"]["job_id"]  # waits: no books
    o.upload_rj()  # now det would say absent …
    graph, cfg, question = _graph(
        cat, o.rt, review=lambda w, det: Review(verdict="contest", reason="looks posted to me")
    )
    graph.invoke({"cui": CUI, "period": PERIOD, "settled": []}, cfg)
    q = graph.get_state(cfg).tasks[0].interrupts[0].value
    assert q["kind"] == "recon_review_contest" and q["det"]["verdict"] == "absent"
    assert _job(o, job_id)["job"]["status"] == "needs_human"  # … but the contest holds it
    graph.invoke(Command(resume={"action": "how_ok"}), cfg)
    q = graph.get_state(cfg).tasks[0].interrupts[0].value
    assert "POST question" in q["error"]
    graph.invoke(Command(resume={"action": "override_absent"}), cfg)
    assert _job(o, job_id)["question"]["kind"] == "v3_approve"


# ----- monthly_close waits on open PRE answers -----


def test_close_is_material_while_a_pre_answer_is_open(cat):
    o, job_id = _close_call(cat)
    out = o.http.post(f"/close/{CUI}/{PERIOD}", params={"tva": "tva_platitor"}, headers=o.op)
    q = out.json()["question"]
    assert q["kind"] == "v2_close" and q["material"] is True
    assert any("reconcile_sink: 1 document(s)" in b for b in q["blockers"])
    filed = o.http.post(
        f"/close/{CUI}/{PERIOD}/resume",
        json={"action": "file", "explained_rule": None},
        headers=o.op,
    ).json()
    assert "cannot file" in filed["question"]["error"]
    # answered on the recon thread, the next close run no longer names it
    _recon(o)
    _recon(o, {"action": "already_posted", "sink_line_ids": [0]})
    o.http.post(
        f"/close/{CUI}/{PERIOD}/resume",
        json={"action": "reopen", "explained_rule": None},
        headers=o.op,
    )
    again = o.http.post(f"/close/{CUI}/{PERIOD}", params={"tva": "tva_platitor"}, headers=o.op)
    assert not any("reconcile_sink" in b for b in again.json()["question"]["blockers"])
