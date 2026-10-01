"""SAGA C "Import facturi XML" mouths: ``iesire_factura_xml`` and ``intrare_factura_xml`` (WP-03).

One ``<Facturi><Factura><Antet/><Detalii><Continut><Linie/>…`` file per invoice. SAGA picks
the journal from the CIFs: our CUI as ``FurnizorCIF`` → Ieșiri, as ``ClientCIF`` → Intrări.

The tag vocabulary below is the whole of what this module may write. It follows SAGA's
documented import format and stays unproven until a fixture imports green on a copy firm;
until then both WriteModules stay ``status: draft`` (AGENTS.md: do not invent tags; extend
only from a successful copy-firm import). Money is read from the document's strings, checked
(line net + VAT = gross, lines sum to totals) and never recomputed from floats.

Open points, all ``[de confirmat]`` against a copy-firm import: CIF with or without ``RO``
for VAT payers; price precision; non-RON invoices (refused here until FX lands).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from xml.etree import ElementTree as ET

from poarta_contabila.types import (
    CanonicalDocument,
    Line,
    PartnerRef,
    SourceRef,
    TenantRef,
    Totals,
    WriteModule,
)

ANTET_TAGS: tuple[str, ...] = (
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
    "FacturaCotaTVA",
)

LINIE_TAGS: tuple[str, ...] = (
    "LinieNrCrt",
    "Descriere",
    "UM",
    "Cantitate",
    "Pret",
    "Valoare",
    "TVA",
)

# module_id -> (doc_class it accepts, which side the tenant is on, batch folder)
_MOUTHS = {
    "iesire_factura_xml": ("iesire", "furnizor", "iesiri"),
    "intrare_factura_xml": ("intrare", "client", "intrari"),
}

_CENT = Decimal("0.01")


class SagaXmlError(ValueError):
    """The document cannot be written through this mouth; nothing is emitted."""


@dataclass(frozen=True)
class RenderedInvoice:
    xml: bytes
    filename: str
    folder: str  # "iesiri" | "intrari" inside the import batch


def export_key(module_id: str, job_id: str, schema_version: str) -> str:
    """Write-once key for a package (IDEMPOTENCY.md)."""
    return f"{module_id}:{job_id}:{schema_version}"


def _d(value: str) -> Decimal:
    return Decimal(value)


def _ro_date(iso: str, sep: str = ".") -> str:
    return date.fromisoformat(iso).strftime(f"%d{sep}%m{sep}%Y")


def _price(net: Decimal, qty: Decimal) -> str:
    unit = (net / qty).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if unit == unit.quantize(_CENT):
        return str(unit.quantize(_CENT))
    return str(unit)


def _check_money(doc: CanonicalDocument) -> None:
    if not doc.lines:
        raise SagaXmlError("invoice has no lines")
    net = vat = gross = Decimal(0)
    for n, line in enumerate(doc.lines, 1):
        if line.vat is None:
            raise SagaXmlError(f"line {n}: vat amount missing")
        if _d(line.net) + _d(line.vat) != _d(line.gross):
            raise SagaXmlError(f"line {n}: net + vat != gross")
        if line.qty is not None and _d(line.qty) <= 0:
            raise SagaXmlError(f"line {n}: quantity must be positive")
        net, vat, gross = net + _d(line.net), vat + _d(line.vat), gross + _d(line.gross)
    for name, lines_sum in (("net", net), ("vat", vat), ("gross", gross)):
        if lines_sum != _d(getattr(doc.totals, name)):
            raise SagaXmlError(f"totals.{name} {getattr(doc.totals, name)} != lines {lines_sum}")


def _filename(furnizor_cif: str, number: str, iso_date: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "-", number).strip("-")
    return f"F_{furnizor_cif}_{safe}_{_ro_date(iso_date, '-')}.xml"


def render_invoice(
    doc: CanonicalDocument, module: WriteModule, *, tenant_name: str
) -> RenderedInvoice:
    """The SAGA import file for *doc* through *module*.

    Raises:
        SagaXmlError: wrong module or side, storno, non-RON, missing VAT, or totals that do
            not tie to the lines.
    """
    if module.module_id not in _MOUTHS or module.saga_path != "import_xml":
        raise SagaXmlError(f"module {module.module_id!r} is not an invoice XML mouth")
    doc_class, tenant_side, folder = _MOUTHS[module.module_id]
    if doc.is_storno:
        raise SagaXmlError("storno documents go through the storno_* mouths")
    if doc.doc_class != doc_class:
        raise SagaXmlError(f"doc_class {doc.doc_class!r} does not match {module.module_id}")
    if doc.currency != "RON":
        raise SagaXmlError(f"currency {doc.currency!r} not supported until FX is built")
    if not doc.partner.cui:
        raise SagaXmlError("partner CUI is required on an invoice")
    _check_money(doc)

    tenant = (tenant_name, doc.tenant.cui)
    partner = (doc.partner.name, doc.partner.cui)
    furnizor, client = (tenant, partner) if tenant_side == "furnizor" else (partner, tenant)
    rates = {line.vat_rate for line in doc.lines}
    maps = doc.maps

    antet = {
        "FurnizorNume": furnizor[0],
        "FurnizorCIF": furnizor[1],
        "FurnizorNrRegCom": maps.get("furnizor_nr_reg_com", ""),
        "FurnizorIBAN": maps.get("furnizor_iban", ""),
        "ClientNume": client[0],
        "ClientCIF": client[1],
        "FacturaNumar": doc.number,
        "FacturaData": _ro_date(doc.date),
        "FacturaScadenta": _ro_date(maps["scadenta"]) if maps.get("scadenta") else "",
        "FacturaTaxareInversa": "Da" if maps.get("taxare_inversa") == "da" else "Nu",
        "FacturaTVAIncasare": "Da" if maps.get("tva_incasare") == "da" else "Nu",
        "FacturaMoneda": doc.currency,
        "FacturaCotaTVA": next(iter(rates)) or "" if len(rates) == 1 else "",
    }
    assert tuple(antet) == ANTET_TAGS

    root = ET.Element("Facturi")
    factura = ET.SubElement(root, "Factura")
    head = ET.SubElement(factura, "Antet")
    for tag in ANTET_TAGS:
        ET.SubElement(head, tag).text = antet[tag]
    continut = ET.SubElement(ET.SubElement(factura, "Detalii"), "Continut")
    for n, line in enumerate(doc.lines, 1):
        qty = _d(line.qty) if line.qty is not None else Decimal(1)
        values = {
            "LinieNrCrt": str(n),
            "Descriere": line.desc,
            "UM": line.unit or "",
            "Cantitate": str(qty),
            "Pret": _price(_d(line.net), qty),
            "Valoare": line.net,
            "TVA": line.vat,
        }
        item = ET.SubElement(continut, "Linie")
        for tag in LINIE_TAGS:
            ET.SubElement(item, tag).text = values[tag]
    ET.indent(root)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
    return RenderedInvoice(
        xml=xml, filename=_filename(furnizor[1], doc.number, doc.date), folder=folder
    )


def fixture_documents() -> dict[str, CanonicalDocument]:
    """Synthetic invoices behind ``fixtures/saga/{iesire,intrare}.xml`` (invented CUIs)."""
    tenant = TenantRef(cui="1000009", saga_firm_folder="0001")

    def source(n: str) -> SourceRef:
        return SourceRef(
            kind="ubl_spv",
            bucket_key=f"fixtures/saga/{n}.ubl.xml",
            content_type="application/xml",
            source_hash=n[0] * 64 if n[0] in "abcdef" else "e" * 64,
        )

    iesire = CanonicalDocument(
        job_id="fixture-iesire",
        tenant=tenant,
        period="2026-09",
        doc_class="iesire",
        number="FX-101",
        date="2026-09-15",
        partner=PartnerRef(cui="20000005", name="Client Test SRL", role="customer"),
        totals=Totals(net="150.50", vat="31.61", gross="182.11"),
        lines=[
            Line(
                desc="Servicii test",
                qty="2",
                unit="buc",
                net="100.00",
                vat_rate="21",
                vat="21.00",
                gross="121.00",
            ),
            Line(
                desc="Material test",
                qty="1",
                unit="buc",
                net="50.50",
                vat_rate="21",
                vat="10.61",
                gross="61.11",
            ),
        ],
        source=source("iesire"),
    )
    intrare = CanonicalDocument(
        job_id="fixture-intrare",
        tenant=tenant,
        period="2026-09",
        doc_class="intrare",
        number="A-77",
        date="2026-09-20",
        partner=PartnerRef(cui="20000005", name="Furnizor Test SRL", role="supplier"),
        totals=Totals(net="200.00", vat="42.00", gross="242.00"),
        lines=[
            Line(
                desc="Consumabile test",
                qty="4",
                unit="buc",
                net="200.00",
                vat_rate="21",
                vat="42.00",
                gross="242.00",
            ),
        ],
        source=source("intrare"),
    )
    return {"iesire": iesire, "intrare": intrare}
