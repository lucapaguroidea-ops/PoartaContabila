"""WP-42: a statement no model can read now waits and is read later (00_LAW §8 A5)."""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from poarta_contabila.reading_waits import InMemoryReadingWaitStore, ReadingWait
from tests.test_extras import CUI
from tests.test_gemini_reader import (
    LITE,
    LITE2,
    STRONG,
    STRONG2,
    UNTIED,
    ByModel,
    Google,
    _model_of,
    _ops,
    _upload,
    cat,  # noqa: F401  (the catalog fixture)
)


class Switch(Google):
    """Google answering 429 to every model until *open* is set."""

    def __init__(self, answers=None):
        super().__init__()
        self.open, self.answers = False, answers or {}

    def __call__(self, request):
        if not self.open:
            self.requests.append(request)
            return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})
        self.answer = self.answers.get(_model_of(request), self.answer)
        return super().__call__(request)


def _later(minutes=2):
    return datetime.now(UTC) + timedelta(minutes=minutes)


def test_a_statement_no_model_can_read_waits_and_is_read_later(cat):  # noqa: F811
    google = Switch()
    o = _ops(cat, google, tiers=True)
    resp = _upload(o)
    assert resp.status_code == 202, resp.text
    out = resp.json()
    assert out["status"] == "waiting" and "429" in out["reason"]
    assert {_model_of(r) for r in google.requests} == {LITE, LITE2, STRONG, STRONG2}
    waiting = o.http.get(f"/reading/{CUI}/waiting", headers=o.op).json()
    assert [w["status"] for w in waiting] == ["waiting"]

    again = _upload(o)  # the same PDF while it waits: still one row
    assert again.status_code == 202
    assert len(o.http.get(f"/reading/{CUI}/waiting", headers=o.op).json()) == 1

    assert o.rt.retry_waiting(now=datetime.now(UTC)) == []  # not before its time
    google.open = True
    (done,) = o.rt.retry_waiting(now=_later())
    assert done["status"] == "read" and done["result"]["lines"] == 2
    assert [j["created"] for j in done["result"]["jobs"]] == [True, True]  # minted only now
    assert done["attempts"] == 1
    (row,) = o.http.get(f"/reading/{CUI}/waiting", headers=o.op).json()
    assert row["status"] == "read"
    assert _upload(o).json()["lines"] == 2  # minted once: the stored extract, same jobs
    assert [j["created"] for j in _upload(o).json()["jobs"]] == [False, False]


def test_a_second_run_with_the_strong_tier_spent_waits(cat):  # noqa: F811
    class StrongSpent(ByModel):
        def __call__(self, request):
            if _model_of(request) in (STRONG, STRONG2):
                self.requests.append(request)
                return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})
            return super().__call__(request)

    google = StrongSpent({LITE: UNTIED})
    o = _ops(cat, google, tiers=True)
    resp = _upload(o)
    assert resp.status_code == 202 and resp.json()["status"] == "waiting"
    assert [_model_of(r) for r in google.requests] == [LITE, STRONG, STRONG2]


def test_a_read_that_is_wrong_is_refused_not_parked(cat):  # noqa: F811
    o = _ops(cat, ByModel({LITE: UNTIED, STRONG: UNTIED}), tiers=True)
    assert _upload(o).status_code == 422
    assert o.http.get(f"/reading/{CUI}/waiting", headers=o.op).json() == []


def test_a_parked_statement_still_refused_later_is_marked_refused(cat):  # noqa: F811
    google = Switch(answers={LITE: UNTIED, STRONG: UNTIED})
    o = _ops(cat, google, tiers=True)
    assert _upload(o).status_code == 202
    google.open = True
    assert o.http.post(f"/reading/{CUI}/retry", headers=o.op).json() == []  # not yet due
    (done,) = o.rt.retry_waiting(now=_later(10))
    assert done["status"] == "refused"
    assert f"read by {LITE}, then {STRONG}" in done["reason"]


def test_still_no_quota_moves_its_time_on(cat):  # noqa: F811
    o = _ops(cat, Switch(), tiers=True)
    first = _upload(o).json()["not_before"]
    (done,) = o.rt.retry_waiting(now=_later())
    assert done["status"] == "waiting" and done["attempts"] == 1
    assert done["not_before"] > first


def test_the_budget_shows_what_is_left_and_warns_before_a_batch(cat):  # noqa: F811
    google = Google()
    o = _ops(cat, google, tiers=True)
    _upload(o)
    budget = o.http.get(f"/reading/{CUI}/budget", headers=o.op).json()
    rows = {m["model"]: m for m in budget["models"]}
    assert rows[LITE]["used_today"] == 1 and rows[STRONG]["left_today"] == 20
    assert budget["strong_left"] == 40 and budget["everyday_left"] is None  # test Lite: no rpd
    assert budget["warnings"] == [] and budget["waiting"] == []
    assert 0 < budget["resets_in_seconds"] <= 24 * 3600
    big = o.http.get(f"/reading/{CUI}/budget", params={"documents": 50}, headers=o.op).json()
    assert any("40 strong reads left" in w for w in big["warnings"])


def test_the_budget_needs_the_reader(cat):  # noqa: F811
    o = _ops(cat, Google(), tiers=True)
    o.rt.gemini_reader = None
    resp = o.http.get(f"/reading/{CUI}/budget", headers=o.op)
    assert resp.status_code == 422 and "not wired" in resp.json()["detail"]


def _wait(i, status="waiting", minutes=0):
    at = (datetime(2026, 10, 2, 21, 0, tzinfo=UTC) + timedelta(minutes=minutes)).isoformat()
    return ReadingWait(
        wait_id=f"{CUI}:{i}",
        tenant_cui=CUI,
        meta={"iban": "x"},
        pdf_key=f"k{i}",
        status=status,
        reason="429",
        not_before=at,
        created_at=at,
    )


def _store_contract(store):
    assert store.put(_wait(1)).wait_id == f"{CUI}:1"
    kept = store.put(_wait(1, minutes=30))  # already waiting: kept as it is
    assert kept.not_before == _wait(1).not_before
    store.put(_wait(2, minutes=10))
    now = datetime(2026, 10, 2, 21, 5, tzinfo=UTC)
    assert [w.wait_id for w in store.due(now)] == [f"{CUI}:1"]
    store.update(_wait(1).model_copy(update={"status": "read"}))
    assert store.due(now + timedelta(hours=1))[0].wait_id == f"{CUI}:2"
    assert [w.status for w in store.list(CUI)] == ["read", "waiting"]
    assert [w.wait_id for w in store.list(CUI, "read")] == [f"{CUI}:1"]
    again = store.put(_wait(1, minutes=40))  # read before: the same PDF may wait again
    assert again.status == "waiting"


def test_in_memory_reading_waits():
    _store_contract(InMemoryReadingWaitStore())


def test_postgres_reading_waits():
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    from poarta_contabila.jobs import PostgresJobStore
    from poarta_contabila.reading_waits import PostgresReadingWaitStore

    PostgresJobStore(dsn, reset=True)
    _store_contract(PostgresReadingWaitStore(dsn))


def test_the_background_retry_reads_what_is_due_and_can_be_turned_off(monkeypatch):
    from poarta_contabila.app import _retry_parked_reads

    monkeypatch.setenv("READING_RETRY_SECONDS", "0")
    asyncio.run(asyncio.wait_for(_retry_parked_reads(lambda: None), 1))  # off: returns

    class Rt:
        gemini_reader, rounds = object(), 0

        def retry_waiting(self):
            Rt.rounds += 1

    async def run_briefly():
        task = asyncio.create_task(_retry_parked_reads(Rt))
        await asyncio.sleep(0.2)
        task.cancel()

    monkeypatch.setenv("READING_RETRY_SECONDS", "0.05")
    asyncio.run(run_briefly())
    assert Rt.rounds >= 2
