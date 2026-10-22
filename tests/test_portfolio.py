"""The portfolio calendar (R45): a read-only page and route over every tenant's filing items
by due date. The tenant key is the only client field; an item with no date is never hidden,
and refused, later and unrecorded items are listed apart from the dated ones."""

from __future__ import annotations

import copy
import os
import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from poarta_contabila.app import create_app
from poarta_contabila.catalog import load_catalog
from poarta_contabila.codit import InMemoryCoditStore
from poarta_contabila.filings import (
    GROUPS,
    PORTFOLIO_FIELDS,
    InMemoryFilingStore,
    PostgresFilingStore,
    portfolio,
)
from poarta_contabila.lockset import lock_set
from poarta_contabila.registry import Tenant
from poarta_contabila.types import cui_is_valid
from tests.test_filings import dated, verified
from tests.test_runtime import CUI, OP, Ops, _runtime

OTHER = "20000005"  # a second invented tenant key, passes the check digit (L36)
NAMES = {CUI: "FIRMA TEST SRL", OTHER: "ALTA FIRMA TEST SRL"}
FIELDS = {
    "tenant",
    "filing_id",
    "form",
    "period",
    "due",
    "dating",
    "reason",
    "mode",
    "frequency",
    "state",
    "lock",
}


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _ops(cat, today=None):
    o = Ops(_runtime(cat, codits=InMemoryCoditStore(), filings=InMemoryFilingStore(), today=today))
    for cui, name in NAMES.items():
        body = {"cui": cui, "name": name, "saga_firm_folder": f"F{cui[-3:]}"}
        assert o.http.put(f"/tenants/{cui}", json=body, headers=o.op).status_code == 200
    return o


def _codit(o, cui, period, **axes):
    base = {"tva": "tva_platitor", "forma": "srl", "impozit": "micro_1", **axes}
    body = {"axes": {k: {"value": v, "certainty": "confirmed"} for k, v in base.items()}}
    r = o.http.put(f"/codit/{cui}/{period}", headers=o.op, json=body)
    assert r.status_code == 200, r.text


def _open(o, cui, period):
    r = o.http.post(f"/filings/{cui}/{period}", headers=o.op)
    assert r.status_code == 200, r.text
    return r.json()


def _calendar(o, headers=None):
    r = o.http.get("/calendar", headers=headers or o.op)
    assert r.status_code == 200, r.text
    return r.json()


def _all(data):
    return [row for g in GROUPS for row in data[g]]


def test_the_page_is_served_without_a_token_and_shows_exactly_the_routes_fields(cat):
    http = TestClient(create_app(None, runtime=None, operator_token=OP, agent_token="a"))
    page = http.get("/portfolio")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    csp = page.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp
    assert page.headers["cache-control"] == "no-store"
    assert '<script src="/portfolio/portfolio.js"' in page.text and "<script>" not in page.text
    js = http.get("/portfolio/portfolio.js")
    assert js.status_code == 200 and "innerHTML" not in js.text  # values are written as text
    assert http.get("/portfolio/other.js").status_code == 404
    # the page reads the calendar route only, and sends nothing (read-only)
    assert re.findall(r'fetch\("([^"]+)"', js.text) == ["/calendar"]
    assert 'method: "GET"' in js.text and "POST" not in js.text and "PUT" not in js.text
    # its columns are exactly the route's fields: nothing else of a client is shown
    columns = re.findall(r'^\s*\["(\w+)", "[^"]+"\],$', js.text, flags=re.M)
    assert set(columns) == FIELDS == set(PORTFOLIO_FIELDS) and len(columns) == len(FIELDS)
    groups = re.findall(r'^\s*\["(\w+)", "[^"]+", "', js.text, flags=re.M)
    assert set(groups) == set(GROUPS) and groups[0] == "dated"  # every group, the dated first


def test_every_tenants_items_by_due_date_with_the_undated_apart(cat):
    other = dated(cat)
    day = verified(other) + timedelta(days=1)
    o = _ops(other, today=lambda: day)
    _codit(o, CUI, "2026-09", engagement="going_concern", tva_period="lunar", d100_period="lunar")
    _codit(o, OTHER, "2026-08", engagement="catch_up", tva_period="trimestrial")
    _codit(o, OTHER, "2026-09", tva_period="trimestrial", d100_period="trimestrial")
    for cui, period in ((CUI, "2026-09"), (OTHER, "2026-08"), (OTHER, "2026-09")):
        _open(o, cui, period)
    data = _calendar(o)

    assert tuple(data) == GROUPS
    rows = _all(data)
    assert all(set(r) == FIELDS for r in rows)  # exactly these fields, no other client data
    text = str(data)
    for name in NAMES.values():
        assert name not in text
    assert "saga_firm_folder" not in text and "receipt" not in text and "submitted" not in text

    # nothing stored is dropped: one row per filing item, across tenants
    stored = o.rt.filings.every_item()
    assert sorted((r["tenant"], r["period"], r["filing_id"]) for r in rows) == sorted(stored)

    dated_rows = data["dated"]
    assert dated_rows and [r["due"] for r in dated_rows] == sorted(r["due"] for r in dated_rows)
    assert {r["tenant"] for r in dated_rows} == {CUI, OTHER}
    assert all(r["dating"] == "dated" and r["reason"] is None for r in dated_rows)
    assert all(r["lock"] == lock_set(other).key for r in dated_rows)
    mine = next(r for r in dated_rows if r["tenant"] == CUI and r["form"] == "D300")
    assert (mine["mode"], mine["frequency"], mine["state"]) == ("going_concern", "lunar", "open")

    # a quarterly filing mid-quarter is later, not refused, and keeps its reason
    (later,) = [r for r in data["later"] if r["form"] == "D300"]
    assert (later["tenant"], later["period"], later["due"]) == (OTHER, "2026-08", None)
    assert later["reason"] == "its quarter does not end in 2026-08" and later["lock"] is None
    assert (later["mode"], later["frequency"]) == ("catch_up", "trimestrial")
    # the calendar's refusal (an unset frequency axis) is listed with its reason
    (refused,) = [r for r in data["refused"] if r["form"] == "D100"]
    assert (refused["tenant"], refused["period"]) == (OTHER, "2026-08")
    assert refused["reason"] == "CO.DiT axis d100_period is not set"
    assert refused["due"] is None and refused["frequency"] is None


def test_while_no_non_working_year_is_pinned_everything_refuses_and_is_shown(cat):
    other = dated(cat)
    other.docs["ArticoleNonWorking"]["years"] = []  # as the catalog stands: no year pinned
    o = _ops(other, today=lambda: verified(other) + timedelta(days=1))
    _codit(o, CUI, "2026-09", tva_period="lunar", d100_period="lunar")
    _codit(o, OTHER, "2026-09", tva_period="lunar", d100_period="lunar")
    opened = len(_open(o, CUI, "2026-09")) + len(_open(o, OTHER, "2026-09"))
    data = _calendar(o)
    assert data["dated"] == [] and data["later"] == [] and data["unrecorded"] == []
    assert len(data["refused"]) == opened > 0
    assert all(r["reason"] == "no non-working days pinned for 2026" for r in data["refused"])
    assert all(r["dating"] == "refused" and r["due"] is None for r in data["refused"])

    # the catalog as it is (no freshness window either): every item refuses, none is hidden
    o = _ops(cat)
    _codit(o, CUI, "2026-09", tva_period="lunar", d100_period="lunar")
    opened = len(_open(o, CUI, "2026-09"))
    data = _calendar(o)
    assert data["dated"] == [] and len(data["refused"]) == opened > 0
    assert all("freshness window is not set" in r["reason"] for r in data["refused"])


def test_an_item_with_no_answer_recorded_is_listed_as_unrecorded(cat):
    items = {(CUI, "2026-09", "d300_platitor"): {"state": "open"}}
    data = portfolio(cat, items, lambda cui, period: {})
    (row,) = data["unrecorded"]
    assert row["dating"] == "unrecorded" and row["reason"] and row["due"] is None
    assert row["form"] == "D300" and row["mode"] is None and row["frequency"] is None
    assert all(data[g] == [] for g in GROUPS if g != "unrecorded")


def test_the_route_is_read_only(cat):
    o = _ops(dated(cat), today=lambda: verified(cat) + timedelta(days=1))
    _codit(o, CUI, "2026-09", tva_period="lunar", d100_period="lunar")
    _open(o, CUI, "2026-09")
    o.rt.filings.receipt(CUI, "2026-09", "d300_platitor", "k.pdf", "contabil@test")
    before = (copy.deepcopy(o.rt.filings.rows), copy.deepcopy(o.rt.codits.rows))
    data = _calendar(o)
    assert _calendar(o) == data
    assert (o.rt.filings.rows, o.rt.codits.rows) == before  # no store was written
    (filed,) = [r for r in _all(data) if r["filing_id"] == "d300_platitor"]
    assert filed["state"] == "filed"
    for method in ("post", "put", "patch", "delete"):
        assert getattr(o.http, method)("/calendar", headers=o.op).status_code == 405
    assert o.http.get("/calendar").status_code == 401  # the operator token is required


def test_the_build_agent_sees_synthetic_tenants_only(cat):
    sb = "s" * 40
    rt = _runtime(cat, filings=InMemoryFilingStore())
    rt.registry.put_tenant(
        Tenant(cui=CUI, name=NAMES[CUI], saga_firm_folder="F1", data_class="synthetic")
    )
    rt.registry.put_tenant(Tenant(cui=OTHER, name=NAMES[OTHER], saga_firm_folder="F2"))
    for cui in (CUI, OTHER):
        rt.filings.open(cui, "2026-09", "d300_platitor", due_refused="no term for D300")
    http = TestClient(
        create_app(
            None, runtime=rt, operator_token="o" * 40, agent_token="a" * 40, sysbuilder_token=sb
        )
    )
    owner = http.get("/calendar", headers={"Authorization": f"Bearer {'o' * 40}"}).json()
    assert {r["tenant"] for r in owner["refused"]} == {CUI, OTHER}
    builder = http.get("/calendar", headers={"Authorization": f"Bearer {sb}"}).json()
    assert {r["tenant"] for r in _all(builder)} == {CUI}


def test_postgres_every_item_reads_each_tenants_items_without_the_receipt(cat):
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    import psycopg

    from poarta_contabila.jobs import PostgresJobStore
    from tests.test_provenance import _invented_cui

    PostgresJobStore(dsn)  # applies the schema
    a, b = _invented_cui(), _invented_cui()
    assert cui_is_valid(a) and cui_is_valid(b) and a != b
    store = PostgresFilingStore(dsn)
    lock = lock_set(cat).as_dict()
    try:
        store.open(a, "2026-09", "d300_platitor", due="2026-10-26", due_lock=lock)
        store.receipt(a, "2026-09", "d300_platitor", "k.pdf", "contabil@test")
        store.open(b, "2026-08", "d300_platitor", due_later="its quarter does not end in 2026-08")
        store.open(b, "2026-09", "d100_micro", due_refused="stale")
        mine = {k: v for k, v in store.every_item().items() if k[0] in (a, b)}
        assert set(mine) == {
            (a, "2026-09", "d300_platitor"),
            (b, "2026-08", "d300_platitor"),
            (b, "2026-09", "d100_micro"),
        }
        assert all(
            set(v) == {"state", "due", "due_lock", "due_refused", "due_later"}
            for v in mine.values()
        )
        assert mine[(a, "2026-09", "d300_platitor")]["state"] == "filed"
        assert mine[(a, "2026-09", "d300_platitor")]["due_lock"] == lock
        data = portfolio(cat, mine, lambda cui, period: {})
        assert [len(data[g]) for g in GROUPS] == [1, 1, 1, 0]
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("DELETE FROM domain.filing_items WHERE cui = ANY(%s)", ([a, b],))
