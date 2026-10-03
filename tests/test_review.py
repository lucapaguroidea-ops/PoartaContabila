"""WP-66 (00_LAW §8 A8): the review page and its inbox — a thin page over the resume routes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from poarta_contabila.app import create_app
from poarta_contabila.catalog import load_catalog
from tests.test_runtime import CUI, FOLDER, INVOICE, NEW_INVOICE, OP, Ops, _runtime, _spv_zip

PERIOD = "2026-09"
SB = "s" * 40


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _items(o, period=PERIOD):
    resp = o.http.get(f"/inbox/{CUI}/{period}", headers=o.op)
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def test_the_page_is_served_without_a_token_and_loads_nothing_from_outside(cat):
    http = TestClient(create_app(None, runtime=None, operator_token=OP, agent_token="a"))
    page = http.get("/review")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    csp = page.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp and page.headers["cache-control"] == "no-store"
    assert '<script src="/review/review.js"' in page.text and "<script>" not in page.text
    js = http.get("/review/review.js")
    assert js.status_code == 200 and "innerHTML" not in js.text  # values are written as text
    assert http.get("/review/review.css").status_code == 200
    assert http.get("/review/icon.svg").headers["content-type"] == "image/svg+xml"
    assert http.get("/review/other.js").status_code == 404


def test_the_inbox_lists_what_waits_on_an_accountant_with_where_to_answer(cat):
    o = Ops(_runtime(cat))
    o.tenant()
    o.upload_rj()
    job_id = o.ingest(NEW_INVOICE).json()["job"]["job_id"]
    (item,) = _items(o)
    assert item["kind"] == "v3_approve" and item["actor"] == "accountant"
    assert item["answer_path"] == f"/jobs/{job_id}/resume"
    assert set(item["answer_schema"]) == {"decision", "edit"}
    assert item["question"]["document"]["number"] and item["job"]["status"] == "reconcile_pre"

    # the page sends the answer unchanged to that route, signed by the person
    resp = o.http.post(
        item["answer_path"],
        json={"decision": "approve", "edit": None},
        headers={**o.op, "X-Operator-Name": "Ioana Pop"},
    )
    assert resp.status_code == 200
    (logged,) = o.http.get("/answers", headers=o.op).json()
    assert logged["operator"] == "Ioana Pop"
    # packaged: it now waits on the SAGA agent (wait_validare), not on an accountant
    assert _items(o) == []

    o.http.post(f"/close/{CUI}/{PERIOD}", params={"tva": "tva_platitor"}, headers=o.op)
    (close,) = _items(o)
    assert close["kind"] == "v2_close" and close["answer_path"] == f"/close/{CUI}/{PERIOD}/resume"
    assert close["job"] is None and "action" in close["answer_schema"]
    assert _items(o, "2026-08") == []  # the close is of September


def test_a_job_that_needs_a_person_but_asks_nothing_is_listed_with_its_error(cat):
    o = Ops(_runtime(cat))
    o.tenant()
    o.upload_rj()  # covers September only
    october = INVOICE.replace(b"<cbc:IssueDate>2026-09-10<", b"<cbc:IssueDate>2026-10-02<")
    o.ingest(_spv_zip(october))
    (item,) = _items(o)
    assert item["question"] is None and item["answer_path"] is None
    assert item["job"]["status"] == "needs_human" and "need_rj_export" in item["job"]["error"]


def test_the_inbox_refuses_a_bad_month_or_an_unknown_firm(cat):
    o = Ops(_runtime(cat))
    assert o.http.get(f"/inbox/{CUI}/{PERIOD}", headers=o.op).status_code == 422
    o.tenant()
    assert o.http.get(f"/inbox/{CUI}/2026-13", headers=o.op).status_code == 422
    assert o.http.get(f"/inbox/{CUI}/{PERIOD}").status_code == 401


def test_the_build_agent_sees_synthetic_firms_only(cat):
    rt = _runtime(cat)
    o = Ops(rt)
    o.tenant()  # client data
    app = create_app(None, runtime=rt, operator_token=OP, agent_token="a" * 40, sysbuilder_token=SB)
    builder = TestClient(app, headers={"Authorization": f"Bearer {SB}"})
    assert builder.get(f"/inbox/{CUI}/{PERIOD}").status_code == 403
    body = {"cui": CUI, "name": "F", "saga_firm_folder": FOLDER, "data_class": "synthetic"}
    o.http.put(f"/tenants/{CUI}", json=body, headers=o.op)
    assert builder.get(f"/inbox/{CUI}/{PERIOD}").status_code == 200
