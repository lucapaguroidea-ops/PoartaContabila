"""WP-07: SAGA report pack (purchase/sales journals) as the eye, and intent_check."""

from __future__ import annotations

from pathlib import Path

import pytest
import xlwt
from langgraph.types import Command

from poarta_contabila.catalog import load_catalog
from poarta_contabila.recon.pre import Witnesses, make_pre_check
from poarta_contabila.sinks.exports import ExportError, read_firm_cui
from poarta_contabila.sinks.saga_eye import ReportPackEye, SagaEye, read_saga_tva_journal
from tests.test_agent import CUI, FOLDER, LABEL, World, _sdoc
from tests.test_recon_pre import _doc, _job

SINK = Path(__file__).resolve().parents[1] / "fixtures" / "sink"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def journals():
    return read_saga_tva_journal(SINK / "saga_jurnal_cumparari.xls", "cumparari") + (
        read_saga_tva_journal(SINK / "saga_jurnal_vanzari.xls", "vanzari")
    )


# ----- reader -----


def test_journals_give_documents_with_partner_cuis(journals):
    by = {d.number: d for d in journals}
    assert set(by) == {"1427", "AB0058", "FX-101"}  # the total row is not a document
    assert (by["1427"].partner_cui, by["1427"].net, by["1427"].vat) == (
        "40000000",
        "1000.00",
        "210.00",
    )
    assert by["AB0058"].partner_cui == "20000005"  # RO prefix stripped
    assert by["FX-101"].doc_class == "iesire" and by["FX-101"].gross == "182.11"
    assert read_firm_cui(SINK / "saga_jurnal_cumparari.xls") == CUI


def _journal(tmp_path, rows, head=None):
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Sheet")
    head = head or [
        "Nr. crt",
        "Data",
        "Nr. doc",
        "Denumire partener",
        "Cod fiscal",
        "Total document",
        "Baza 21%",
        "TVA 21%",
    ]
    for c, v in enumerate(head):
        ws.write(6, c, v)
    for r, row in enumerate(rows, start=7):
        for c, v in enumerate(row):
            ws.write(r, c, v)
    path = tmp_path / "j.xls"
    wb.save(str(path))
    return path


def test_a_row_that_does_not_add_up_is_refused(tmp_path):
    path = _journal(tmp_path, [[1, "03.09.2026", "7", "X SRL", "RO40000000", 121.0, 100.0, 20.0]])
    with pytest.raises(ExportError, match="≠ total"):
        read_saga_tva_journal(path, "cumparari")


def test_missing_header_is_refused(tmp_path):
    path = _journal(tmp_path, [], head=["Nr. crt", "Data", "Explicatie"])
    with pytest.raises(ExportError, match="header not found"):
        read_saga_tva_journal(path, "cumparari")


def test_report_pack_eye(journals):
    eye = ReportPackEye(documents=journals, cui=CUI, periods=["2026-09"])
    assert isinstance(eye, SagaEye)
    assert eye.covers(CUI, "2026-09") and not eye.covers(CUI, "2026-08")
    assert not ReportPackEye(documents=journals, cui=None, periods=["2026-09"]).covers(
        CUI, "2026-09"
    )
    assert [d.number for d in eye.documents(CUI, "2026-09")] == ["1427", "AB0058", "FX-101"]


def test_pre_with_journals_matches_on_partner_cui(cat, journals):
    eye = ReportPackEye(documents=journals, cui=CUI, periods=["2026-09"])
    pre = make_pre_check(cat, lambda job: Witnesses(eye=eye))
    # only the digits match, but the journal names the same partner CUI: decisive
    out = pre(
        _job(),
        _doc("58", "2026-09-10", "167.06", partner_cui="20000005"),
        fiscal_class="ro_efactura",
    )
    assert (out.verdict, out.level) == ("already_posted", "digits_core")


# ----- intent_check -----


def _waiting(cat):
    w = World(cat)
    job_id, doc = w.packaged()
    w.post("/agent/ack-backup", {"label": LABEL, "cui": CUI, "folder": FOLDER})
    w.import_all()
    return w, job_id, doc


def test_intent_check_passes_when_saga_shows_what_was_packaged(cat):
    w, job_id, doc = _waiting(cat)
    out = w.snapshot(
        [_sdoc(doc, net=doc.totals.net, vat=doc.totals.vat, partner_cui=doc.partner.cui)]
    )
    assert out["acked"] == [job_id] and w.status(job_id) == "acked"


@pytest.mark.parametrize(
    ("over", "said"),
    [
        ({"vat": "30.00"}, "vat 30.00 in SAGA"),
        ({"net": "151.50"}, "net 151.50 in SAGA"),
        ({"partner_cui": "40000000"}, "partner 40000000 in SAGA"),
    ],
)
def test_intent_mismatch_goes_to_a_person(cat, over, said):
    w, job_id, doc = _waiting(cat)
    out = w.snapshot([_sdoc(doc, **over)])
    assert out["intent_mismatch"] == [job_id]
    job = w.jobs.get(job_id)
    assert job.status == "needs_human" and said in job.error
    assert job.saga["saga_doc_key"] == "SAGA-IES-1"  # kept, for the person's Devalidare


def test_intent_check_reads_the_snapshot_not_the_answer(cat):
    w, job_id, doc = _waiting(cat)
    w.snapshot([_sdoc(doc, validated=False)])  # stored, not validated yet
    w.graph.invoke(Command(resume={"validated": True, "saga_doc_key": "SAGA-IES-1"}), w.cfg(job_id))
    assert w.status(job_id) == "wait_validare"  # asked again: no validated snapshot


def test_runtime_prefers_uploaded_journals(cat):
    from tests.test_runtime import NEW_INVOICE, Ops, _runtime

    o = Ops(_runtime(cat))
    o.tenant()
    for side in ("cumparari", "vanzari"):
        up = o.http.post(
            f"/tenants/{CUI}/exports/jurnal_{side}",
            params={"filename": f"j_{side}.xls", "product": "saga"},
            content=(SINK / f"saga_jurnal_{side}.xls").read_bytes(),
            headers={**o.op, "Content-Type": "application/octet-stream"},
        )
        assert up.status_code == 200 and up.json()["periods"] == ["2026-09"]
    nextup = o.http.post(
        f"/tenants/{CUI}/exports/jurnal_cumparari",
        params={"filename": "j.xls", "product": "nextup"},
        content=(SINK / "saga_jurnal_cumparari.xls").read_bytes(),
        headers={**o.op, "Content-Type": "application/octet-stream"},
    )
    assert nextup.status_code == 422
    out = o.ingest(NEW_INVOICE).json()  # AB 0099 is not in the journals: covered, absent
    assert out["question"]["kind"] == "v3_approve"
