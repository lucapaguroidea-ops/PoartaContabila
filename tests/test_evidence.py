"""The evidence ledger (BUILD.md B6, item 5): friction and control of a firm-month."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from poarta_contabila import runtime as runtime_module
from poarta_contabila.answers import proposed, record
from poarta_contabila.evidence import judged, verdict
from poarta_contabila.jobs import InMemoryJobStore
from poarta_contabila.period_diff import InMemoryPeriodStore
from poarta_contabila.triage import EmitDecision, InMemoryBatchIndex, Pack
from poarta_contabila.types import ControlRun, PeriodDiff

CUI = "1000009"
DECISION = EmitDecision(emit=True, job_kind="job_ro_efactura", aisle="x")


def _pack(n: int = 0, period: str = "2026-09") -> Pack:
    return Pack(
        tenant_cui=CUI,
        saga_firm_folder="0001",
        period=period,
        source_hash=f"{n:064x}",
        source_doc_id="ro_efactura_ubl",
        kinds=["ubl_spv"],
        our_role="inbound",
        counterparty_cui="20000005",
    )


# ----- what an answer did to the proposal -----


@pytest.mark.parametrize(
    "kind, answer, meta, want",
    [
        ("v3_approve", {"decision": "approve"}, {}, "as_proposed"),
        ("v3_approve", {"decision": "reject"}, {}, "refused"),
        ("v3_approve", {"decision": "edit", "edit": {"a": 1}}, {}, "changed"),
        (
            "v3_approve",
            {"decision": "edit", "edit": {"a": 1}},
            {"proposed_edit": {"a": 1}},
            "as_proposed",
        ),
        (
            "v3_approve",
            {"decision": "edit", "edit": {"a": 2}},
            {"proposed_edit": {"a": 1}},
            "changed",
        ),
        ("v2_close", {"action": "file"}, {}, "as_proposed"),
        ("v2_close", {"action": "hold"}, {}, "held"),
        ("v2_close", {"action": "reopen"}, {}, "changed"),
        ("v4_codit", {"accept": True, "skip": False}, {}, "as_proposed"),
        ("v4_codit", {"accept": False, "skip": True}, {}, "refused"),
        ("wait_validare", {"validated": False}, {}, "refused"),
        ("decont_split", {"parts": []}, {}, "answered"),
    ],
)
def test_the_verdict_of_an_answer(kind, answer, meta, want):
    assert verdict(kind, answer, meta) == want


def test_jev_agreed_overridden_or_silent():
    clean = {"judge": {"accounts_ok": True, "risk": "low", "needs_human": False}}
    doubt = {"judge": {"accounts_ok": False, "risk": "high", "needs_human": True}}
    silent = {"judge": {"accounts_ok": False, "risk": "unknown", "needs_human": True}}
    assert judged(clean, "as_proposed") == "agreed"
    assert judged(clean, "refused") == "overridden"
    assert judged(doubt, "as_proposed") == "overridden"
    assert judged(doubt, "changed") == "agreed"
    assert judged(silent, "as_proposed") is None and judged({}, "refused") is None


def test_an_answer_keeps_what_the_question_proposed():
    q = {
        "kind": "v3_approve",
        "judge": {"accounts_ok": True, "risk": "low", "needs_human": False, "judge": "why"},
        "proposal": {"candidates": [], "edit": {"partner": {"cui": "20000005"}}},
    }
    assert proposed(q) == {
        "judge": {"accounts_ok": True, "risk": "low", "needs_human": False},
        "proposed_edit": {"partner": {"cui": "20000005"}},
    }
    row = record(
        graph_id="ingest_source_doc",
        thread_id="job:1",
        tenant_cui=CUI,
        before=q,
        after=None,
        answer={"decision": "approve"},
        operator=None,
    )
    assert row.meta == proposed(q)


# ----- what the stores now keep -----


def test_a_job_keeps_every_status_it_took():
    jobs = InMemoryJobStore()
    job = jobs.emit(_pack(), DECISION).job
    jobs.emit(_pack(), DECISION)  # the same source again: no new job, no event
    jobs.update(job.job_id, status="bound")
    jobs.update(job.job_id, error="note")  # same status: no event
    jobs.update(job.job_id, status="acked")
    jobs.emit(_pack(1, "2026-10"), DECISION)
    assert [e.status for e in jobs.events_for(CUI, "2026-09")] == ["ingested", "bound", "acked"]


def test_control_runs_and_batches_of_a_month():
    periods = InMemoryPeriodStore()
    for sid, status in (("s1", "FAIL"), ("s2", "PASS")):
        periods.save(
            PeriodDiff(cui=CUI, period="2026-09", snapshot_id=sid),
            [ControlRun(control_id="C1_outbound_complete", status=status)],
        )
    runs = periods.runs_for(CUI, "2026-09")
    assert [(s, r.status) for s, r in runs] == [("s1", "FAIL"), ("s2", "PASS")]
    assert periods.runs_for(CUI, "2026-10") == []
    batches = InMemoryBatchIndex()
    batches.add(CUI, "b1", "2026-09")
    batches.add(CUI, "b2", "2026-10")
    assert batches.for_period(CUI, "2026-09") == ["b1"]


# ----- the ledger over a scenario run -----


@pytest.fixture(scope="module")
def run():
    """``platitor_clean`` run locally; the runtime behind it, and its firm-month."""
    from poarta_contabila.scenarios import local_clients, run_one, scenarios
    from poarta_contabila.synthetic.firms import firm

    seen = {}
    build = runtime_module.build_runtime

    def spy(*a, **k):
        seen["rt"] = build(*a, **k)
        return seen["rt"]

    with mock.patch.object(runtime_module, "build_runtime", spy):
        client, agent = local_clients()
    sc = scenarios(["platitor_clean"])[0]
    assert run_one(sc, client, agent).passed
    return client, seen["rt"], firm(sc.firm).cui, sc.period


def test_the_ledger_of_a_clean_month(run):
    client, _rt, cui, period = run
    led = client.get(f"/evidence/{cui}/{period}").json()
    assert set(led["friction"]) == {
        "questions_asked",
        "asked_again",
        "proposals_changed_or_refused",
        "documents_held_for_a_person",
    }
    assert set(led["control"]) == {
        "stopped_at_a_gate",
        "controls_failed_then_passed",
        "caught_late_by_post",
        "got_through_reopened_after_ack",
    }
    ingest = led["graphs"]["ingest_source_doc"]
    assert ingest["threads"] == led["month"]["documents"] > 0
    assert ingest["nodes"]["bind"] == ingest["threads"]
    assert "approve → package" in ingest["edges"]
    for kind, q in led["questions"].items():
        assert q["asked"] == q.get("answered_total", 0) + q.get("waiting", 0), kind
    assert led["questions"]["wait_validare"]["as_proposed"] == led["month"]["acked"]
    assert led["control"]["got_through_reopened_after_ack"] == 0
    assert led["controls"]["C1_outbound_complete"]["last"] == "PASS"
    assert led["model_roles"]["jev_v3_judge"]["calls"] > 0
    assert any("minutes" in x for x in led["not_measured"])
    assert "minutes" not in str(led["friction"]) + str(led["month"])


def test_a_job_reopened_after_ack_got_through(run):
    client, rt, cui, period = run
    acked = next(j for j in rt.jobs.for_period(cui, period) if j.status == "acked")
    rt.jobs.update(acked.job_id, status="reopened")
    led = client.get(f"/evidence/{cui}/{period}").json()
    assert led["control"]["got_through_reopened_after_ack"] == 1
    assert led["articole"][acked.articol_id]["reopened_after_ack"] == 1


def test_the_ledger_needs_a_registered_tenant_and_a_period(run):
    client, _rt, cui, _period = run
    assert client.get(f"/evidence/{cui}/2026-9").status_code == 422
    assert client.get("/evidence/1000017/2026-09").status_code == 404


def test_the_cli_prints_a_scenarios_ledger(capsys):
    from poarta_contabila.evidence import main

    assert main(["--scenario", "platitor_clean"]) == 0
    out = capsys.readouterr().out
    assert "friction:" in out and "control:" in out and "not measured:" in out


# ----- Postgres -----


def test_postgres_job_events_and_control_runs():
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    from poarta_contabila.jobs import PostgresJobStore
    from poarta_contabila.period_diff import PostgresPeriodStore
    from poarta_contabila.triage import PostgresBatchIndex

    jobs = PostgresJobStore(dsn, reset=True)
    job = jobs.emit(_pack(), DECISION).job
    jobs.emit(_pack(), DECISION)
    jobs.update(job.job_id, status="bound")
    jobs.update(job.job_id, error="note")
    jobs.update(job.job_id, status="acked")
    assert [e.status for e in jobs.events_for(CUI, "2026-09")] == ["ingested", "bound", "acked"]

    periods = PostgresPeriodStore(dsn)
    for sid, status in (("s1", "FAIL"), ("s2", "PASS")):
        periods.save(
            PeriodDiff(cui=CUI, period="2026-09", snapshot_id=sid),
            [ControlRun(control_id="C1_outbound_complete", status=status)],
        )
    assert [(s, r.status) for s, r in periods.runs_for(CUI, "2026-09")] == [
        ("s1", "FAIL"),
        ("s2", "PASS"),
    ]
    batches = PostgresBatchIndex(dsn)
    batches.add(CUI, "b1", "2026-09")
    batches.add(CUI, "b2", "2026-10")
    assert batches.for_period(CUI, "2026-09") == ["b1"]
