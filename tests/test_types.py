"""domain types are closed (extra=forbid) and keep money/dates as strings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from poarta_contabila.types import (
    CanonicalDocument,
    ExpectedItem,
    JobRecord,
    PartnerRef,
    PeriodDiff,
    SinkDoc,
    SourceRef,
    TenantRef,
    WriteModule,
    cui_is_valid,
)

# Invented CUIs with a valid check digit (key 753217532). Not real firms.
CUI_A = "1000009"
CUI_B = "20000005"


def _tenant() -> TenantRef:
    return TenantRef(cui=CUI_A, saga_firm_folder="0001")


def _source() -> SourceRef:
    return SourceRef(
        kind="ubl_spv",
        bucket_key=f"tenants/{CUI_A}/default/2026-09/ubl/job-1/f.xml",
        content_type="application/xml",
        source_hash="a" * 64,
    )


def _doc(**over):
    base = dict(
        job_id="job-1",
        tenant=_tenant(),
        period="2026-09",
        doc_class="intrare",
        number="F-1",
        date="2026-09-15",
        partner=PartnerRef(cui=CUI_B, name="Furnizor Test", role="supplier"),
        totals={"net": "100.00", "vat": "21.00", "gross": "121.00"},
        lines=[],
        source=_source(),
    )
    base.update(over)
    return CanonicalDocument(**base)


def test_check_digit():
    assert cui_is_valid(CUI_A)
    assert cui_is_valid(CUI_B)
    assert not cui_is_valid("1000004")
    assert not cui_is_valid("RO1000009")  # keys carry no RO prefix
    assert not cui_is_valid("1")


def test_tenant_rejects_bad_cui():
    with pytest.raises(ValidationError):
        TenantRef(cui="12345678", saga_firm_folder="0001")


def test_canonical_document_round_trip():
    doc = _doc()
    assert doc.totals.gross == "121.00"
    assert doc.schema_version == "1"


@pytest.mark.parametrize(
    "model, payload",
    [
        (TenantRef, {"cui": CUI_A, "saga_firm_folder": "0001", "extra": 1}),
        (PartnerRef, {"cui": None, "name": "x", "role": "unknown", "tva": "full"}),
    ],
)
def test_extra_keys_forbidden(model, payload):
    with pytest.raises(ValidationError):
        model(**payload)


def test_canonical_extra_key_forbidden():
    with pytest.raises(ValidationError):
        _doc(tva_deducere="full")


@pytest.mark.parametrize("bad", [121.0, 121, "121", "121.0", "1,21", "1.234"])
def test_money_must_be_two_decimal_string(bad):
    with pytest.raises(ValidationError):
        _doc(totals={"net": "100.00", "vat": "21.00", "gross": bad})


@pytest.mark.parametrize("bad", ["15.09.2026", "2026-9-15", "2026-09-15T00:00:00"])
def test_dates_are_iso_strings(bad):
    with pytest.raises(ValidationError):
        _doc(date=bad)


def test_period_format():
    with pytest.raises(ValidationError):
        _doc(period="2026-9")


def test_job_status_is_closed_and_has_reopened():
    job = JobRecord(job_id="job-1", tenant=_tenant(), period="2026-09", status="reopened")
    assert job.status == "reopened"
    with pytest.raises(ValidationError):
        JobRecord(job_id="job-1", tenant=_tenant(), period="2026-09", status="posted")


def test_expected_and_sink_money_are_strings():
    item = ExpectedItem(
        job_id="job-1",
        doc_class="intrare",
        number="F-1",
        date="2026-09-15",
        partner_cui=CUI_B,
        gross="121.00",
        net="100.00",
        vat="21.00",
    )
    sink = SinkDoc(
        saga_key="RJ-1",
        doc_class="intrare",
        number="F-1",
        date="2026-09-15",
        partner_cui=CUI_B,
        gross="121.00",
        net="100.00",
        vat="21.00",
        validated=True,
    )
    assert item.gross == sink.gross


def test_period_diff_material_defaults_closed():
    diff = PeriodDiff(cui=CUI_A, period="2026-09", snapshot_id="snap-1")
    assert diff.material is False and diff.hard_failures == 0


def test_write_module_cannot_name_fdb_insert():
    with pytest.raises(ValidationError):
        WriteModule(
            module_id="x",
            schema_version="1",
            status="draft",
            saga_path="fdb_insert",
            validare="human",
            backup="before_each",
            hitl="always",
            max_docs_per_run=1,
        )
