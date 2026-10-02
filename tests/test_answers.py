"""WP-33: the answer log — every answer a person submits, what became of it, and who sent it."""

from __future__ import annotations

import os

import pytest

from poarta_contabila.answers import InMemoryAnswerLog, judge, question_hash, record
from poarta_contabila.catalog import load_catalog
from tests.test_runtime import CUI, Ops, _runtime

PERIOD = "2026-09"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _ops(cat):
    o = Ops(_runtime(cat))
    o.tenant()
    o.upload_rj()
    return o


def _log(o, **params):
    return o.http.get("/answers", params=params, headers=o.op).json()


def test_a_job_answer_is_logged_with_its_outcome_and_its_author(cat):
    o = _ops(cat)
    job_id = o.ingest().json()["job"]["job_id"]
    me = {**o.op, "X-Operator-Name": "A. Popescu"}
    bad = o.http.post(f"/jobs/{job_id}/resume", json={"decision": "maybe"}, headers=me).json()
    assert bad["question"]["kind"] == "v3_approve" and "error" in bad["question"]
    o.http.post(
        f"/jobs/{job_id}/resume", json={"decision": "approve", "edit": None}, headers=me
    ).json()

    accepted, refused = _log(o, thread=f"job:{job_id}")  # newest first
    assert refused["outcome"] == "asked_again" and refused["answer"] == {"decision": "maybe"}
    assert refused["error"] and refused["kind"] == "v3_approve"
    assert accepted["outcome"] == "accepted" and accepted["next_kind"] == "wait_validare"
    assert accepted["question_hash"] == refused["question_hash"]  # the same question
    assert {r["operator"] for r in (accepted, refused)} == {"A. Popescu"}
    assert accepted["graph_id"] == "ingest_source_doc" and accepted["tenant_cui"] == CUI


def test_an_answer_with_nothing_waiting_changes_nothing_and_is_logged_as_such(cat):
    o = _ops(cat)
    resp = o.http.post(f"/recon/{CUI}/2026-07/resume", json={"export_id": "x"}, headers=o.op)
    assert resp.status_code == 200 and resp.json()["question"] is None  # was a 500 before WP-33
    (row,) = _log(o, thread=f"recon:{CUI}:2026-07")
    assert row["outcome"] == "no_question" and row["kind"] is None and row["operator"] is None
    assert o.http.get(f"/recon/{CUI}/2026-07", headers=o.op).json()["settled"] == []


@pytest.mark.parametrize("name", ["", " ", "x" * 65, "a\x00b"])
def test_a_bad_operator_name_is_refused_before_anything_happens(cat, name):
    o = _ops(cat)
    job_id = o.ingest().json()["job"]["job_id"]
    resp = o.http.post(
        f"/jobs/{job_id}/resume",
        json={"decision": "approve", "edit": None},
        headers={**o.op, "X-Operator-Name": name},
    )
    assert resp.status_code == 422
    assert _log(o) == [] and o.rt.view(job_id)["question"]["kind"] == "v3_approve"


def test_close_and_expense_report_answers_are_logged_per_tenant(cat):
    import base64

    o = _ops(cat)
    o.http.post(f"/close/{CUI}/{PERIOD}", params={"tva": "tva_platitor"}, headers=o.op)
    o.http.post(
        f"/close/{CUI}/{PERIOD}/resume",
        json={"action": "hold", "explained_rule": None},
        headers=o.op,
    )
    batch = o.http.post(
        f"/decont/{CUI}",
        headers=o.op,
        json={
            "filename": "d.pdf",
            "period": PERIOD,
            "file_b64": base64.b64encode(b"%PDF-1.4 x").decode(),
            "tenant_on_doc": True,
        },
    ).json()["batch_id"]
    o.http.post(f"/triage/{batch}/resume", json={"parts": []}, headers=o.op)
    rows = _log(o, cui=CUI)
    assert [(r["graph_id"], r["kind"]) for r in rows] == [
        ("folder_triage", "decont_split"),
        ("monthly_close", "v2_close"),
    ]
    assert rows[1]["outcome"] == "accepted" and rows[1]["thread_id"] == f"close:{CUI}:{PERIOD}"
    assert _log(o, cui="20000005") == []


def test_the_same_question_coming_back_without_an_error_is_a_new_question():
    q = {"kind": "recon_ambiguous", "job_id": "a"}
    assert judge(q, {**q, "error": "x"}) == ("asked_again", "x")
    assert judge(q, {"kind": "recon_ambiguous", "job_id": "b"})[0] == "accepted"
    assert judge(q, None)[0] == "accepted"
    assert judge(None, q)[0] == "no_question"
    assert question_hash(q) == question_hash({**q, "error": "x"})


def test_the_log_only_grows():
    log = InMemoryAnswerLog()
    for i in range(3):
        log.add(
            record(
                graph_id="g",
                thread_id=f"t{i % 2}",
                tenant_cui=CUI,
                before={"kind": "k"},
                after=None,
                answer={"n": i},
                operator=None,
            )
        )
    assert [r.answer["n"] for r in log.recent()] == [2, 1, 0]
    assert [r.answer["n"] for r in log.recent(thread_id="t0", limit=1)] == [2]
    assert not hasattr(log, "delete") and not hasattr(log, "update")


def test_postgres_answer_log(cat):
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    from poarta_contabila.answers import PostgresAnswerLog
    from poarta_contabila.jobs import PostgresJobStore

    PostgresJobStore(dsn, reset=True)
    log = PostgresAnswerLog(dsn)
    for i in range(3):
        log.add(
            record(
                graph_id="ingest_source_doc",
                thread_id=f"job:{i % 2}",
                tenant_cui=CUI if i else "20000005",
                before={"kind": "v3_approve"},
                after={"kind": "v3_approve", "error": "no"} if i == 2 else None,
                answer={"decision": "approve", "n": i},
                operator="A. Popescu",
            )
        )
    rows = log.recent(cui=CUI)
    assert [r.answer["n"] for r in rows] == [2, 1]
    assert rows[0].outcome == "asked_again" and rows[0].error == "no"
    assert [r.answer["n"] for r in log.recent(thread_id="job:0")] == [2, 0]
