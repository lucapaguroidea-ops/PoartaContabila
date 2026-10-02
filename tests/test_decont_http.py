"""WP-28: expense reports over HTTP — triage splits the container; a person names the parts."""

from __future__ import annotations

import base64
import hashlib

import pytest

from poarta_contabila.catalog import load_catalog
from tests.test_runtime import CUI, NEW_INVOICE, Ops, _runtime

PERIOD = "2026-09"
REPORT = b"%PDF-1.4 synthetic expense report"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _ops(cat, **over):
    o = Ops(_runtime(cat, **over))
    o.tenant()
    o.upload_rj()
    return o


def _upload(o, data=REPORT, filename="decont.pdf", tenant_on_doc=True):
    return o.http.post(
        f"/decont/{CUI}",
        headers=o.op,
        json={
            "filename": filename,
            "period": PERIOD,
            "file_b64": base64.b64encode(data).decode(),
            "tenant_on_doc": tenant_on_doc,
        },
    )


def _resume(o, batch_id, body):
    return o.http.post(f"/triage/{batch_id}/resume", json=body, headers=o.op).json()


INVOICE_PART = {
    "part_hash": hashlib.sha256(NEW_INVOICE).hexdigest(),  # the SPV zip of the invoice inside
    "source_doc_id": "ro_efactura_ubl",
    "kinds": ["ubl_spv"],
    "bon_our_cui_on_doc": None,
    "counterparty_cui": "20000005",
}
WORKINGS_PART = {
    "part_hash": "b" * 64,
    "source_doc_id": "workings",
    "kinds": ["pdf"],
    "bon_our_cui_on_doc": None,
    "counterparty_cui": None,
}


def test_an_expense_report_asks_for_its_parts_and_never_becomes_a_job(cat):
    o = _ops(cat)
    out = _upload(o).json()
    assert out["created"] is True and out["batch_id"].startswith("decont-")
    q = out["question"]
    assert q["kind"] == "decont_split" and "ro_efactura_ubl" in q["children"]
    assert o.rt.jobs.jobs == {}  # the container is evidence, never a Job
    again = _upload(o).json()
    assert again["created"] is False and again["batch_id"] == out["batch_id"]
    assert again["question"] == q


def test_without_the_tenant_on_the_report_nothing_is_split(cat):
    o = _ops(cat)
    out = _upload(o, tenant_on_doc=False).json()
    assert out["question"] is None and "identity_gate" in out["decision"]["failed"]
    assert o.rt.jobs.jobs == {}


def test_only_report_formats_are_taken(cat):
    o = _ops(cat)
    assert _upload(o, filename="decont.zip").status_code == 422
    assert _upload(o, data=b"").status_code == 422
    other = o.http.post(
        "/decont/20000005",
        headers=o.op,
        json={"filename": "d.pdf", "period": PERIOD, "file_b64": "", "tenant_on_doc": True},
    )
    assert other.status_code == 422  # tenant not registered


def test_a_part_that_breaks_the_rules_is_asked_again(cat):
    o = _ops(cat)
    batch = _upload(o).json()["batch_id"]
    pdf_with_xml = {**INVOICE_PART, "source_doc_id": "ro_efactura_pdf"}
    q = _resume(o, batch, {"parts": [pdf_with_xml]})["question"]
    assert "the invoice XML exists" in q["error"]
    q = _resume(o, batch, {"parts": [{**WORKINGS_PART, "source_doc_id": "stat_salarii"}]})[
        "question"
    ]
    assert "is not one of" in q["error"]


def test_the_invoice_part_becomes_a_job_whose_thread_starts_when_its_xml_arrives(cat):
    o = _ops(cat)
    batch = _upload(o).json()["batch_id"]
    view = _resume(o, batch, {"parts": [INVOICE_PART, WORKINGS_PART]})
    assert view["question"] is None
    kids = {c["source_doc_id"]: c for c in view["children"]}
    assert kids["ro_efactura_ubl"]["emit"] is True and kids["ro_efactura_ubl"]["job_id"]
    assert kids["workings"]["emit"] is False and kids["workings"]["job_id"] is None
    job_id = kids["ro_efactura_ubl"]["job_id"]
    assert o.http.get(f"/triage/{batch}", headers=o.op).json()["children"] == view["children"]
    # the part's SPV zip is uploaded: same (tenant, hash) → the same Job, and its thread starts
    out = o.ingest(NEW_INVOICE).json()
    assert out["created"] is False and out["job"]["job_id"] == job_id
    assert out["question"]["kind"] == "v3_approve"
    again = o.ingest(NEW_INVOICE).json()  # a second upload changes nothing
    assert again["question"] == out["question"]


def test_an_unknown_batch_is_404(cat):
    o = _ops(cat)
    assert o.http.get("/triage/decont-nope", headers=o.op).status_code == 404
    assert _resume_status(o) == 404


def _resume_status(o):
    return o.http.post("/triage/decont-nope/resume", json={}, headers=o.op).status_code


def test_the_split_role_is_recorded_in_shadow(cat):
    import dataclasses

    roles = {
        rid: r.model_copy(update={"model": "vendor/model-2026-09-15"})
        for rid, r in cat.model_roles.items()
    }
    o = Ops(_runtime(dataclasses.replace(cat, model_roles=roles), model_mode="dry"))
    o.http.put(
        f"/tenants/{CUI}",
        json={"cui": CUI, "name": "F", "saga_firm_folder": "0001", "data_class": "synthetic"},
        headers=o.op,
    )
    _upload(o)
    (call,) = [
        c
        for c in o.http.get("/model-calls", headers=o.op).json()
        if c["role_id"] == "ocr_decont_split"
    ]
    assert call["status"] == "recorded" and call["input"]["file"]["kind"] == "pdf"
    assert call["input"]["file"]["sha256"] == hashlib.sha256(REPORT).hexdigest()


def test_the_same_report_for_another_tenant_is_its_own_batch(cat):
    o = _ops(cat)
    other = "20000005"
    o.http.put(
        f"/tenants/{other}",
        json={"cui": other, "name": "G", "saga_firm_folder": "0002"},
        headers=o.op,
    )
    a = _upload(o).json()["batch_id"]
    b = o.http.post(
        f"/decont/{other}",
        headers=o.op,
        json={
            "filename": "decont.pdf",
            "period": PERIOD,
            "file_b64": base64.b64encode(REPORT).decode(),
            "tenant_on_doc": True,
        },
    ).json()
    assert b["created"] is True and b["batch_id"] != a
