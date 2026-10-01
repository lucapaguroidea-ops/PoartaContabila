"""A2 XML first: SPV zips are split by root element; UBL totals are checked, never guessed."""

from __future__ import annotations

import hashlib
import io
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from poarta_contabila.extract.ubl import (
    UblError,
    line_vats,
    parse_ubl,
    read_spv_zip,
    to_canonical,
)
from poarta_contabila.sinks.saga_xml import render_invoice
from poarta_contabila.types import JobRecord, SourceRef, TenantRef

UBL = Path(__file__).resolve().parents[1] / "fixtures" / "ubl"
INVOICE = (UBL / "invoice_inbound.xml").read_bytes()
CREDIT = (UBL / "credit_note_outbound.xml").read_bytes()
SIGNATURE = (UBL / "semnatura.xml").read_bytes()


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _job(cui="1000009") -> JobRecord:
    return JobRecord(
        job_id="job-1",
        tenant=TenantRef(cui=cui, saga_firm_folder="FIRMA"),
        period="2026-09",
        status="extracted",
    )


def _source(data: bytes) -> SourceRef:
    return SourceRef(
        kind="ubl_spv",
        bucket_key="tenants/1000009/default/2026-09/source/x.xml",
        content_type="application/xml",
        source_hash=hashlib.sha256(data).hexdigest(),
    )


# ----- zip -----


def test_zip_is_split_by_root_element_not_by_name():
    # names swapped on purpose: the signature is called invoice.xml and vice versa
    spv = read_spv_zip(_zip({"invoice.xml": SIGNATURE, "semnatura_123.xml": INVOICE}))
    assert spv.invoice == INVOICE and spv.invoice_name == "semnatura_123.xml"
    assert spv.signature == SIGNATURE


def test_zip_ignores_a_pdf_and_keeps_its_name():
    spv = read_spv_zip(_zip({"f.xml": INVOICE, "f.pdf": b"%PDF-1.4"}))
    assert spv.other_members == ("f.pdf",) and spv.signature is None


def test_zip_with_two_invoices_or_unknown_xml_is_refused():
    with pytest.raises(UblError, match="one invoice"):
        read_spv_zip(_zip({"a.xml": INVOICE, "b.xml": CREDIT}))
    with pytest.raises(UblError, match="unknown root"):
        read_spv_zip(_zip({"a.xml": INVOICE, "b.xml": b"<Other/>"}))
    with pytest.raises(UblError, match="one invoice"):
        read_spv_zip(_zip({"s.xml": SIGNATURE}))


def test_dtd_is_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
    with pytest.raises(UblError, match="DTD"):
        read_spv_zip(_zip({"a.xml": bomb}))


# ----- invoice -----


def test_invoice_fields_and_parties():
    inv = parse_ubl(INVOICE)
    assert (inv.number, inv.issue_date, inv.currency) == ("AB 0058", "2026-09-10", "RON")
    assert inv.supplier.cui == "20000005" and inv.customer.cui == "1000009"
    assert inv.supplier.name == "ALT FURNIZOR SRL"
    assert (inv.net, inv.vat, inv.gross) == ("675.50", "132.31", "807.81")
    assert inv.lines[-1].document_level and inv.lines[-1].net == "-30.00"
    assert {(s.rate, s.vat) for s in inv.subtotals} == {("21", "121.80"), ("11", "10.51")}


def test_line_vat_adds_up_to_each_subtotal():
    inv = parse_ubl(INVOICE)
    assert line_vats(inv) == ["52.50", "75.60", "10.51", "-6.30"]


def test_inbound_canonical_and_saga_render():
    inv = parse_ubl(INVOICE)
    doc = to_canonical(inv, job=_job(), source=_source(INVOICE))
    assert (doc.doc_class, doc.partner.cui, doc.partner.role) == ("intrare", "20000005", "supplier")
    assert doc.totals.gross == "807.81" and not doc.is_storno
    assert sum(Decimal(ln.gross) for ln in doc.lines) == Decimal("807.81")
    assert doc.lines[-1].qty is None and doc.lines[-1].desc == "Discount comercial"


def test_credit_note_is_a_signed_storno():
    inv = parse_ubl(CREDIT)
    assert inv.is_credit_note and inv.supplier.cui == "1000009"
    assert inv.customer.cui == "30000002"  # non-payer: CUI as the legal id
    doc = to_canonical(inv, job=_job(), source=_source(CREDIT))
    assert (doc.doc_class, doc.is_storno, doc.storno_of) == ("storn_iesire", True, "FX-101")
    assert (doc.totals.net, doc.totals.vat, doc.totals.gross) == ("-100.00", "-21.00", "-121.00")
    assert doc.lines[0].qty == "-1.000"


def test_tenant_must_be_exactly_one_party():
    inv = parse_ubl(INVOICE)
    with pytest.raises(UblError, match="neither"):
        to_canonical(inv, job=_job("40000000"), source=_source(INVOICE))


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        (
            b'<cbc:TaxAmount currencyID="RON">132.31',
            b'<cbc:TaxAmount currencyID="RON">132.30',
            "subtotals",
        ),
        (b"807.81</cbc:TaxInclusiveAmount>", b"807.80</cbc:TaxInclusiveAmount>", "TaxInclusive"),
        (b"705.50</cbc:LineExtensionAmount>", b"705.51</cbc:LineExtensionAmount>", "lines sum"),
        (b">250.00<", b">250.005<", "two decimals"),
        (b'<cbc:Amount currencyID="RON">30.00', b'<cbc:Amount currencyID="EUR">30.00', "EUR"),
        (
            b"<cbc:Percent>11.00</cbc:Percent>\n        <cac:TaxScheme><cbc:ID>VAT</cbc:ID>"
            b"</cac:TaxScheme>\n      </cac:TaxCategory>\n    </cac:TaxSubtotal>",
            b"<cbc:Percent>9.00</cbc:Percent>\n        <cac:TaxScheme><cbc:ID>VAT</cbc:ID>"
            b"</cac:TaxScheme>\n      </cac:TaxCategory>\n    </cac:TaxSubtotal>",
            "do not match",
        ),
    ],
)
def test_inconsistent_totals_are_refused(old, new, match):
    assert old in INVOICE
    with pytest.raises(UblError, match=match):
        parse_ubl(INVOICE.replace(old, new, 1))


def test_subtotal_vat_far_from_rate_is_refused():
    bad = CREDIT.replace(b">21.00</cbc:TaxAmount>", b">25.00</cbc:TaxAmount>")
    bad = bad.replace(b">121.00</cbc:TaxInclusiveAmount>", b">125.00</cbc:TaxInclusiveAmount>")
    bad = bad.replace(b">121.00</cbc:PayableAmount>", b">125.00</cbc:PayableAmount>")
    with pytest.raises(UblError, match="is not 21%"):
        parse_ubl(bad)


def test_rendered_saga_xml_from_ubl_balances():
    from poarta_contabila.catalog import load_catalog

    cat = load_catalog()
    inv = parse_ubl(INVOICE)
    doc = to_canonical(inv, job=_job(), source=_source(INVOICE))
    rendered = render_invoice(
        doc, cat.write_modules["intrare_factura_xml"], tenant_name="FIRMA TEST SRL"
    )
    assert rendered.folder == "intrari"
    assert b"<FacturaNumar>AB 0058</FacturaNumar>" in rendered.xml
    assert b"<FurnizorCIF>20000005</FurnizorCIF>" in rendered.xml
