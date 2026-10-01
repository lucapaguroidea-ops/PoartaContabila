"""WP-12: filings — due from CO.DiT, closed only by a stored receipt, never by the calendar."""

from __future__ import annotations

import os

import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.codit import InMemoryCoditStore
from poarta_contabila.filings import DUE_UNPINNED, InMemoryFilingStore, books_gate, due_filings
from tests.test_controls import CUI, PERIOD


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


def _ops(cat):
    from tests.test_runtime import Ops, _runtime

    o = Ops(_runtime(cat, codits=InMemoryCoditStore(), filings=InMemoryFilingStore()))
    o.tenant()
    o.upload_rj()
    return o


def _codit(o):
    o.http.put(
        f"/codit/{CUI}/{PERIOD}",
        headers=o.op,
        json={
            "axes": {
                "tva": {"value": "tva_platitor", "certainty": "confirmed"},
                "forma": {"value": "srl", "certainty": "confirmed"},
                "impozit": {"value": "micro_1", "certainty": "confirmed"},
            }
        },
    )


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
    assert d300["state"] == "open" and d300["due"] == DUE_UNPINNED
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
    store.open(CUI, PERIOD, "d300_platitor")
    store.open(CUI, PERIOD, "d300_platitor")
    assert store.items(CUI, PERIOD)["d300_platitor"]["state"] == "open"
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
