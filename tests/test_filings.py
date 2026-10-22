"""filings — due from CO.DiT, closed only by a stored receipt, never by the calendar. An item
records what the calendar said when it was opened: its due date with the lock set, or the
calendar's refusal; a refusal is information and blocks nothing (L43)."""

from __future__ import annotations

import copy
import os
from datetime import date, timedelta

import pytest

from poarta_contabila.calendar import obligations
from poarta_contabila.catalog import load_catalog
from poarta_contabila.codit import InMemoryCoditStore
from poarta_contabila.filings import InMemoryFilingStore, books_gate, due_filings
from poarta_contabila.lockset import lock_set
from tests.test_controls import CUI, PERIOD

WINDOW = 90  # an invented freshness window for the tests; the catalog leaves it to the owner
LOCK = {"core": "0.0.0", "library": "f" * 40, "corpus": None}  # a stored lock set's shape


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _ids(cat, axes):
    return {r["filing_id"] for r in due_filings(cat, axes)}


def test_due_items_follow_codit(cat):
    payer = {
        "tva": "tva_platitor",
        "exig": "tva_exig_livrare",
        "forma": "srl",
        "impozit": "micro_1",
    }
    assert _ids(cat, payer) == {"d300_platitor", "d394_platitor", "d406_saft", "d100_micro"}
    rc = {"tva": "tva_neplatitor", "cross_border": "inbound_eu_services", "employees": "has"}
    assert _ids(cat, rc) == {"d301_neplatitor_rc", "d390_rc", "d406_saft", "d112_payroll"}
    assert "d112_payroll" not in _ids(cat, {"employees": "none"})
    assert "d390_rc" not in _ids(cat, {"cross_border": "none"})
    assert "d300_platitor" not in _ids(cat, {})  # an empty profile owes no VAT return


def test_books_gate_needs_every_named_control_passed(cat):
    row = next(r for r in due_filings(cat, {"tva": "tva_platitor"}) if r["form"] == "D394")
    gate, ok = books_gate(row, {"C1_outbound_complete": "PASS", "C2_unexplained_empty": "FAIL"})
    assert gate == {"C1_outbound_complete": "PASS", "C2_unexplained_empty": "FAIL"} and not ok
    assert books_gate(row, {})[0] == {
        "C1_outbound_complete": "not run",
        "C2_unexplained_empty": "not run",
    }


def dated(cat):
    """*cat* with an invented freshness window and an invented non-working year for 2026, so
    the calendar can date this period's items (neither is in the catalog: the owner sets the
    window, and no year is pinned)."""
    other = copy.deepcopy(cat)
    other.docs["ArticoleTerms"]["register"]["max_age_days"] = WINDOW
    other.docs["ArticoleNonWorking"]["years"] = [
        {
            "year_id": "nonworking_synthetic_2026",
            "year": 2026,
            "weekly_rest": ["saturday", "sunday"],
            "days": [],
            "provenance": {"source": "synthetic test year (invented)", "certainty": "de_confirmat"},
        }
    ]
    return other


def verified(cat) -> date:
    return date.fromisoformat(cat.docs["ArticoleTerms"]["register"]["verified_at"])


def test_an_open_item_records_its_due_date_or_its_refusal():
    store = InMemoryFilingStore()
    store.open(CUI, PERIOD, "d300_platitor", due="2026-10-26", due_lock=LOCK)
    store.open(CUI, PERIOD, "d394_platitor", due_refused="no term for D394")
    items = store.items(CUI, PERIOD)
    assert items["d300_platitor"]["due"] == "2026-10-26"
    assert items["d300_platitor"]["due_lock"] == LOCK
    assert items["d300_platitor"]["due_refused"] is None
    assert items["d394_platitor"]["due"] is None
    assert items["d394_platitor"]["due_refused"] == "no term for D394"


def test_reopening_keeps_a_recorded_due_date_and_fills_a_missing_one():
    store = InMemoryFilingStore()
    store.open(CUI, PERIOD, "d300_platitor", due="2026-10-26", due_lock=LOCK)
    store.open(CUI, PERIOD, "d300_platitor", due="2026-10-27", due_lock=None)  # not overwritten
    store.open(CUI, PERIOD, "d394_platitor", due_refused="stale")
    store.open(CUI, PERIOD, "d394_platitor", due="2026-10-30", due_lock=LOCK)  # a refusal clears
    store.open(CUI, PERIOD, "d406_saft", due_refused="stale")
    store.receipt(CUI, PERIOD, "d406_saft", "k.pdf", "contabil@test")
    store.open(CUI, PERIOD, "d406_saft", due="2026-10-31", due_lock=LOCK)  # filed: untouched
    items = store.items(CUI, PERIOD)
    assert (items["d300_platitor"]["due"], items["d300_platitor"]["due_lock"]) == (
        "2026-10-26",
        LOCK,
    )
    assert items["d394_platitor"]["due"] == "2026-10-30"
    assert items["d394_platitor"]["due_refused"] is None
    assert items["d406_saft"]["due"] is None and items["d406_saft"]["state"] == "filed"


def test_only_a_receipt_closes_an_item():
    store = InMemoryFilingStore()
    store.open(CUI, PERIOD, "d300_platitor")
    store.open(CUI, PERIOD, "d300_platitor")  # idempotent
    # nothing here reads a clock: a due date passing has no code path that closes an item
    assert store.items(CUI, PERIOD)["d300_platitor"]["state"] == "open"
    assert not store.has_receipt(CUI, PERIOD)
    store.receipt(CUI, PERIOD, "d300_platitor", "tenants/x/receipt.pdf", "contabil@test")
    assert store.items(CUI, PERIOD)["d300_platitor"]["state"] == "filed"
    assert store.has_receipt(CUI, PERIOD)
    with pytest.raises(KeyError):
        store.receipt(CUI, PERIOD, "d112_payroll", "k", "x")  # not opened → not due


# ----- runtime -----


def _ops(cat, today=None):
    from tests.test_runtime import Ops, _runtime

    o = Ops(_runtime(cat, codits=InMemoryCoditStore(), filings=InMemoryFilingStore(), today=today))
    o.tenant()
    o.upload_rj()
    return o


def _codit(o, **extra):
    axes = {
        "tva": {"value": "tva_platitor", "certainty": "confirmed"},
        "forma": {"value": "srl", "certainty": "confirmed"},
        "impozit": {"value": "micro_1", "certainty": "confirmed"},
        **{k: {"value": v, "certainty": "confirmed"} for k, v in extra.items()},
    }
    r = o.http.put(f"/codit/{CUI}/{PERIOD}", headers=o.op, json={"axes": axes})
    assert r.status_code == 200, r.text


def _receipt(o, filing_id, data=b"%PDF-1.4 recipisa", by="contabil@test"):
    return o.http.post(
        f"/filings/{CUI}/{PERIOD}/{filing_id}/receipt",
        params={"filename": "recipisa.pdf", "submitted_by": by},
        content=data,
        headers={**o.op, "Content-Type": "application/octet-stream"},
    )


def test_filings_over_http(cat):
    o = _ops(cat)
    no = o.http.post(f"/filings/{CUI}/{PERIOD}", headers=o.op)
    assert no.status_code == 422 and "nothing is assumed due" in no.json()["detail"]
    _codit(o)
    items = {
        i["filing_id"]: i for i in o.http.post(f"/filings/{CUI}/{PERIOD}", headers=o.op).json()
    }
    assert set(items) == {"d300_platitor", "d394_platitor", "d406_saft", "d100_micro"}
    d300 = items["d300_platitor"]
    assert d300["state"] == "open" and d300["due"] is None  # the window is the owner's: unset
    assert "freshness window is not set" in d300["due_refused"]
    assert d300["books_support"] is False  # the sample books do not support it yet
    assert _receipt(o, "d300_platitor", data=b"").status_code == 422
    assert _receipt(o, "d112_payroll").status_code == 422  # not due for this profile
    after = {i["filing_id"]: i for i in _receipt(o, "d300_platitor").json()}
    assert after["d300_platitor"]["state"] == "filed"
    assert after["d300_platitor"]["submitted_by"] == "contabil@test"
    key = after["d300_platitor"]["receipt_key"]
    assert key.startswith(f"tenants/{CUI}/default/{PERIOD}/receipts/d300_platitor/")
    assert o.rt.blobs.get(key) == b"%PDF-1.4 recipisa"
    assert after["d394_platitor"]["state"] == "open"  # one receipt closes one item


FREQS = {"tva_period": "lunar", "d100_period": "lunar"}


def _open(o):
    r = o.http.post(f"/filings/{CUI}/{PERIOD}", headers=o.op)
    assert r.status_code == 200, r.text
    return {i["filing_id"]: i for i in r.json()}


def test_open_filings_records_each_due_date_with_its_lock_set(cat):
    other = dated(cat)
    day = verified(other) + timedelta(days=1)
    o = _ops(other, today=lambda: day)
    _codit(o, **FREQS)
    items = _open(o)
    axes = o.rt.codits.get(CUI, PERIOD).derive()
    want = {x.filing_id: x for x in obligations(other, axes, PERIOD, as_of=day).items}
    assert set(items) == set(want) and want
    for fid, item in items.items():
        assert item["due"] == want[fid].due and item["due_refused"] is None
        assert item["due_lock"] == lock_set(other).as_dict()


def test_open_filings_judges_freshness_on_the_runtimes_today(cat):
    other = dated(cat)
    stale = verified(other) + timedelta(days=WINDOW + 1)
    o = _ops(other, today=lambda: stale)
    _codit(o, **FREQS)
    items = _open(o)
    assert items and all(i["state"] == "open" and i["due"] is None for i in items.values())
    assert all(i["due_refused"].startswith("the register pin is stale") for i in items.values())
    o.rt.today = lambda: verified(other)  # the pin is fresh again: re-opening dates them
    again = _open(o)
    assert all(i["due"] and i["due_refused"] is None for i in again.values())
    o.rt.today = lambda: stale  # stale once more: a recorded due date is kept
    assert _open(o) == again


def test_a_refused_due_date_blocks_neither_opening_nor_receipts_nor_close(cat):
    o = _ops(cat)  # the catalog as it is: the window is unset, so every due date is refused
    _codit(o, **FREQS)
    items = _open(o)
    assert set(items) == {"d300_platitor", "d394_platitor", "d406_saft", "d100_micro"}
    assert all(i["due"] is None and i["due_refused"] for i in items.values())
    assert _receipt(o, "d300_platitor").status_code == 200
    out = o.http.post(f"/close/{CUI}/{PERIOD}", headers=o.op).json()
    blockers = " ".join(out["question"]["blockers"] if out.get("question") else [])
    assert out["run"]["status"] == "v2_ready", out  # the close reaches its question as before
    assert "register" not in blockers and "due" not in blockers  # no gate was added (L43)


def test_a_period_with_a_receipt_gets_no_new_package(cat):
    from tests.test_runtime import NEW_INVOICE

    o = _ops(cat)
    _codit(o)
    o.http.post(f"/filings/{CUI}/{PERIOD}", headers=o.op)
    _receipt(o, "d300_platitor")
    out = o.ingest(NEW_INVOICE).json()
    job_id = out["job"]["job_id"]
    view = o.resume(job_id, {"decision": "approve", "edit": None})
    assert view["job"]["status"] == "needs_human"
    assert "has a filing receipt" in view["job"]["error"]
    assert not o.rt.packages.rows


def test_postgres_filing_store(cat):
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    import psycopg

    from poarta_contabila.filings import PostgresFilingStore
    from poarta_contabila.jobs import PostgresJobStore

    PostgresJobStore(dsn, reset=True)
    store = PostgresFilingStore(dsn)
    store.open(CUI, PERIOD, "d300_platitor", due="2026-10-26", due_lock=LOCK)
    store.open(
        CUI, PERIOD, "d300_platitor", due="2026-10-27", due_lock=None
    )  # kept, not overwritten
    d300 = store.items(CUI, PERIOD)["d300_platitor"]
    assert d300["state"] == "open" and d300["due"] == "2026-10-26" and d300["due_lock"] == LOCK
    store.open(CUI, PERIOD, "d394_platitor", due_refused="stale")
    assert store.items(CUI, PERIOD)["d394_platitor"]["due_refused"] == "stale"
    store.open(CUI, PERIOD, "d394_platitor", due="2026-10-30", due_lock=LOCK)  # a refusal clears
    d394 = store.items(CUI, PERIOD)["d394_platitor"]
    assert (d394["due"], d394["due_lock"], d394["due_refused"]) == ("2026-10-30", LOCK, None)
    with (
        psycopg.connect(dsn, autocommit=True) as conn,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        conn.execute(
            "UPDATE domain.filing_items SET state = 'filed' WHERE filing_id = 'd300_platitor'"
        )
    store.receipt(CUI, PERIOD, "d300_platitor", "k.pdf", "contabil@test")
    assert store.has_receipt(CUI, PERIOD)
    assert store.items(CUI, PERIOD)["d300_platitor"]["submitted_by"] == "contabil@test"
