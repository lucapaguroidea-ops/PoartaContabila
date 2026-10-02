"""WP-03: SAGA "Import facturi XML" mouths for iesire / intrare invoices."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.sinks.saga_xml import (
    ANTET_TAGS,
    FACTURA_TAGS,
    LINIE_TAGS,
    SagaXmlError,
    export_key,
    fixture_documents,
    render_invoice,
)
from poarta_contabila.types import CanonicalDocument

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "saga"
TENANT = "1000009"  # invented, valid check digit
PARTNER = "20000005"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture(scope="module")
def docs():
    return fixture_documents()


def _tree(xml: bytes) -> ET.Element:
    return ET.fromstring(xml)


def test_tag_vocabulary_is_closed():
    # Changing these lists is a WP of its own: every tag is quoted in RESEARCH_LOG R1 (the SAGA
    # manual's "Import date"), in the manual's order, and proven by a green copy-firm import.
    assert FACTURA_TAGS == ("Antet", "Detalii", "FacturaID")
    assert ANTET_TAGS == (
        "FurnizorNume",
        "FurnizorCIF",
        "FurnizorNrRegCom",
        "FurnizorIBAN",
        "ClientNume",
        "ClientCIF",
        "FacturaNumar",
        "FacturaData",
        "FacturaScadenta",
        "FacturaTaxareInversa",
        "FacturaTVAIncasare",
        "FacturaMoneda",
    )
    assert LINIE_TAGS == (
        "LinieNrCrt",
        "Descriere",
        "UM",
        "Cantitate",
        "Pret",
        "Valoare",
        "ProcTVA",
        "TVA",
    )


def test_no_invented_tag_reaches_the_file(cat, docs):
    # FacturaCotaTVA was written before R1 was read; the manual has no such tag.
    for kind, module_id in (("iesire", "iesire_factura_xml"), ("intrare", "intrare_factura_xml")):
        root = _tree(render_invoice(docs[kind], cat.write_modules[module_id], tenant_name="X").xml)
        assert root.tag == "Facturi"
        for factura in root:
            assert tuple(child.tag for child in factura) == FACTURA_TAGS
            assert tuple(child.tag for child in factura.find("Antet")) == ANTET_TAGS
        assert root.find(".//FacturaCotaTVA") is None


def test_each_line_carries_its_vat_rate(cat):
    doc = fixture_documents()["iesire"]
    lines = [
        doc.lines[0],
        doc.lines[1].model_copy(update={"vat_rate": "11", "vat": "5.56", "gross": "56.06"}),
    ]
    doc = doc.model_copy(
        update={
            "lines": lines,
            "totals": doc.totals.model_copy(update={"vat": "26.56", "gross": "177.06"}),
        }
    )
    rendered = render_invoice(doc, cat.write_modules["iesire_factura_xml"], tenant_name="X")
    found = _tree(rendered.xml).findall("Factura/Detalii/Continut/Linie")
    assert [line.findtext("ProcTVA") for line in found] == ["21", "11"]


def test_line_without_vat_rate_is_refused(cat, docs):
    line = docs["iesire"].lines[0].model_copy(update={"vat_rate": None})
    bad = docs["iesire"].model_copy(update={"lines": [line, docs["iesire"].lines[1]]})
    with pytest.raises(SagaXmlError, match="vat rate"):
        render_invoice(bad, cat.write_modules["iesire_factura_xml"], tenant_name="X")


def test_factura_id_is_the_job_id(cat, docs):
    # SAGA keeps it with its own id, so a receipt or payment can name the invoice (R1).
    rendered = render_invoice(
        docs["intrare"], cat.write_modules["intrare_factura_xml"], tenant_name="X"
    )
    assert _tree(rendered.xml).findtext("Factura/FacturaID") == "fixture-intrare"


def test_iesire_routes_tenant_as_furnizor(cat, docs):
    rendered = render_invoice(
        docs["iesire"], cat.write_modules["iesire_factura_xml"], tenant_name="Firma Test"
    )
    head = _tree(rendered.xml).find("Factura/Antet")
    assert head.findtext("FurnizorCIF") == TENANT
    assert head.findtext("ClientCIF") == PARTNER
    assert head.findtext("FacturaData") == "15.09.2026"
    assert rendered.filename == "F_1000009_FX-101_15-09-2026.xml"
    assert rendered.folder == "iesiri"


def test_intrare_routes_tenant_as_client(cat, docs):
    rendered = render_invoice(
        docs["intrare"], cat.write_modules["intrare_factura_xml"], tenant_name="Firma Test"
    )
    head = _tree(rendered.xml).find("Factura/Antet")
    assert head.findtext("FurnizorCIF") == PARTNER
    assert head.findtext("ClientCIF") == TENANT
    assert rendered.folder == "intrari"


def test_lines_carry_string_money_exactly(cat, docs):
    rendered = render_invoice(
        docs["iesire"], cat.write_modules["iesire_factura_xml"], tenant_name="Firma Test"
    )
    lines = _tree(rendered.xml).findall("Factura/Detalii/Continut/Linie")
    assert [line.findtext("Valoare") for line in lines] == ["100.00", "50.50"]
    assert [line.findtext("TVA") for line in lines] == ["21.00", "10.61"]
    assert [line.findtext("Pret") for line in lines] == ["50.00", "50.50"]
    for line in lines:
        assert tuple(child.tag for child in line) == LINIE_TAGS


def test_wrong_side_is_refused(cat, docs):
    with pytest.raises(SagaXmlError, match="doc_class"):
        render_invoice(docs["intrare"], cat.write_modules["iesire_factura_xml"], tenant_name="X")


def test_totals_must_tie_to_lines(cat, docs):
    bad = docs["iesire"].model_copy(
        update={"totals": docs["iesire"].totals.model_copy(update={"net": "150.49"})}
    )
    with pytest.raises(SagaXmlError, match="net"):
        render_invoice(bad, cat.write_modules["iesire_factura_xml"], tenant_name="X")


def test_line_without_vat_amount_is_refused(cat, docs):
    line = docs["iesire"].lines[0].model_copy(update={"vat": None})
    bad = docs["iesire"].model_copy(update={"lines": [line]})
    with pytest.raises(SagaXmlError, match="vat"):
        render_invoice(bad, cat.write_modules["iesire_factura_xml"], tenant_name="X")


def test_storno_is_not_this_mouth(cat, docs):
    bad = docs["iesire"].model_copy(update={"is_storno": True, "storno_of": "job-0"})
    with pytest.raises(SagaXmlError, match="storno"):
        render_invoice(bad, cat.write_modules["iesire_factura_xml"], tenant_name="X")


def test_other_modules_are_refused(cat, docs):
    with pytest.raises(SagaXmlError, match="nota_nc_dbf"):
        render_invoice(docs["iesire"], cat.write_modules["nota_nc_dbf"], tenant_name="X")


def test_rendering_is_deterministic(cat, docs):
    module = cat.write_modules["iesire_factura_xml"]
    assert (
        render_invoice(docs["iesire"], module, tenant_name="X").xml
        == render_invoice(docs["iesire"], module, tenant_name="X").xml
    )


def test_export_key_is_stable(cat, docs):
    assert export_key("iesire_factura_xml", "job-1", "1") == "iesire_factura_xml:job-1:1"


@pytest.mark.parametrize(
    "module_id, kind", [("iesire_factura_xml", "iesire"), ("intrare_factura_xml", "intrare")]
)
def test_committed_fixture_matches_renderer(cat, docs, module_id, kind):
    """The file a human imports into the copy firm is exactly what the code emits."""
    module = cat.write_modules[module_id]
    assert module.fixture == f"fixtures/saga/{kind}.xml"
    rendered = render_invoice(docs[kind], module, tenant_name="Firma Test")
    assert (FIXTURES / f"{kind}.xml").read_bytes() == rendered.xml


def test_modules_stay_draft_until_copy_firm_green(cat):
    for module_id in ("iesire_factura_xml", "intrare_factura_xml"):
        module = cat.write_modules[module_id]
        assert module.status == "draft" or module.approved_at is not None


def test_fixture_documents_are_valid_canonical(docs):
    for doc in docs.values():
        assert isinstance(doc, CanonicalDocument)
