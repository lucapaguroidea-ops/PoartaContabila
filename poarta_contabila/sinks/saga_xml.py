"""SAGA C "Import date" XML mouths: invoices (WP-03) and bank receipts / payments (WP-19).

Invoices go through ``iesire_factura_xml`` / ``intrare_factura_xml``.

One ``<Facturi><Factura><Antet/><Detalii><Continut><Linie/>…</Detalii><FacturaID/>`` file per
invoice. SAGA picks the journal from the CIFs: our CUI as ``FurnizorCIF`` → Ieșiri, as
``ClientCIF`` → Intrări.

The tag vocabulary below is the whole of what this module may write. Every tag is quoted from
SAGA's manual, "Import date" (RESEARCH_LOG R1), in the manual's order; the set stays unproven
until a fixture imports green on a copy firm, and until then both WriteModules stay
``status: draft`` (AGENTS.md: do not invent tags). ``FacturaID`` is the job id: SAGA keeps it
so a receipt or payment can name the invoice. Money is read from the document's strings,
checked (line net + VAT = gross, lines sum to totals, a VAT rate on every line) and never
recomputed from floats.

Open points, all ``[de confirmat]`` against a copy-firm import (SAGA's own sample XML from
Ieșiri → Formular PDF settles the formats): date and decimal formats; a partner CIF with or
without ``RO`` (SAGA stores the firm's own code without it); price precision; empty tags;
non-RON invoices (refused here until FX lands).

Bank lines go through ``incasare_xml`` (``I_<data>.xml``, ``<Incasari>``) and ``plata_xml``
(``P_<data>.xml``, ``<Plati>``), one ``<Linie>`` per Job. A line takes this mouth only when it
names its partner (CUI, bound by a person), the invoice it settles (``FacturaID`` or
``FacturaNumar``) and the treasury account its IBAN maps to; anything else (fees, taxes,
salaries, transfers, an unknown payer) is posted in SAGA by a person. ``ContClient`` /
``ContFurnizor`` are not written: SAGA owns the partner analytics. An optional tag is
written only with a value. ``[de confirmat]`` as for invoices, plus what SAGA does with
``Numar``. ``Numar`` is the bank's reference when the statement gives one that no other line
shares, else the line's own number (``EXT-…``).
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
)

LINIE_TAGS: tuple[str, ...] = (
    "LinieNrCrt",
    "Descriere",
    "UM",
    "Cantitate",
    "Pret",
    "Valoare",
    "ProcTVA",
    "TVA",
)

FACTURA_TAGS: tuple[str, ...] = ("Antet", "Detalii", "FacturaID")

BANK_TAGS: tuple[str, ...] = (
    "Data",
    "Numar",
    "Suma",
    "Cont",
    "Explicatie",
    "FacturaID",
    "FacturaNumar",
    "CodFiscal",
)
_BANK_OPTIONAL = frozenset({"FacturaID", "FacturaNumar"})

# module_id -> (doc_class it accepts, which side the tenant is on, batch folder)
_MOUTHS = {
    "iesire_factura_xml": ("iesire", "furnizor", "iesiri"),
    "intrare_factura_xml": ("intrare", "client", "intrari"),
}

# module_id -> (doc_class it accepts, root tag, file prefix, batch folder)
_BANK_MOUTHS = {
    "incasare_xml": ("incasare", "Incasari", "I", "incasari"),
    "plata_xml": ("plata", "Plati", "P", "plati"),
}

_TREASURY = re.compile(r"^5\d{3}(\.[0-9A-Za-z]+)*$")  # "Cont de trezorerie din clasa 5"

_CENT = Decimal("0.01")


class SagaXmlError(ValueError):
    """The document cannot be written through this mouth; nothing is emitted."""


@dataclass(frozen=True)
class RenderedFile:
    xml: bytes
    filename: str
    folder: str  # "iesiri" | "intrari" | "incasari" | "plati" inside the import batch


RenderedInvoice = RenderedFile


def mouth_doc_class(module_id: str) -> str | None:
    """The document class a rendered mouth accepts, or None for a mouth not rendered here."""
    if module_id in _MOUTHS:
        return _MOUTHS[module_id][0]
    if module_id in _BANK_MOUTHS:
        return _BANK_MOUTHS[module_id][0]
    return None


def is_bank_mouth(module_id: str) -> bool:
    return module_id in _BANK_MOUTHS


def packaged_number(doc: CanonicalDocument) -> str:
    """The number SAGA is given for *doc*: a bank line goes in under the bank's reference
    when the statement names it once (``render_bank_line``'s ``Numar``), else its number."""
    if doc.doc_class in ("incasare", "plata"):
        return doc.maps.get("referinta") or doc.number
    return doc.number


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
        if line.vat_rate is None:
            raise SagaXmlError(f"line {n}: vat rate missing")
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
) -> RenderedFile:
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
            "ProcTVA": line.vat_rate,
            "TVA": line.vat,
        }
        item = ET.SubElement(continut, "Linie")
        for tag in LINIE_TAGS:
            ET.SubElement(item, tag).text = values[tag]
    ET.SubElement(factura, "FacturaID").text = doc.job_id
    assert tuple(child.tag for child in factura) == FACTURA_TAGS
    ET.indent(root)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
    return RenderedFile(
        xml=xml, filename=_filename(furnizor[1], doc.number, doc.date), folder=folder
    )


def render_bank_line(
    doc: CanonicalDocument, module: WriteModule, *, cont: str | None
) -> RenderedFile:
    """The SAGA receipts / payments import file for one bank line through *module*.

    *cont* is the treasury account the tenant maps the line's IBAN to (``5121.01``).

    Raises:
        SagaXmlError: wrong module or side, storno, non-RON, VAT on a bank line, no partner
            CUI, no invoice named, or no class-5 treasury account.
    """
    if module.module_id not in _BANK_MOUTHS or module.saga_path != "import_xml":
        raise SagaXmlError(f"module {module.module_id!r} is not a bank XML mouth")
    doc_class, root_tag, prefix, folder = _BANK_MOUTHS[module.module_id]
    if doc.is_storno:
        raise SagaXmlError("a bank line is never a storno")
    if doc.doc_class != doc_class:
        raise SagaXmlError(f"doc_class {doc.doc_class!r} does not match {module.module_id}")
    if doc.currency != "RON":
        raise SagaXmlError(f"currency {doc.currency!r} not supported until FX is built")
    gross = _d(doc.totals.gross)
    if gross <= 0 or _d(doc.totals.vat) != 0 or _d(doc.totals.net) != gross:
        raise SagaXmlError("a bank line moves one positive amount, without VAT")
    if not doc.partner.cui:
        raise SagaXmlError(
            "bind the partner (CUI) first: a bank line with no partner is posted in SAGA"
        )
    maps = doc.maps
    factura_id, factura_numar = maps.get("factura_id", ""), maps.get("factura_numar", "")
    if not (factura_id or factura_numar):
        raise SagaXmlError(
            "name the invoice it settles (factura_id or factura_numar): otherwise post it in SAGA"
        )
    if not cont or not _TREASURY.match(cont):
        raise SagaXmlError(
            f"no class-5 treasury account mapped for IBAN {maps.get('iban') or '?'}"
            f" (got {cont!r}): set the tenant's bank_accounts"
        )

    values = {
        "Data": _ro_date(doc.date),
        "Numar": packaged_number(doc),
        "Suma": str(gross.quantize(_CENT)),
        "Cont": cont,
        "Explicatie": doc.lines[0].desc if doc.lines else doc.number,
        "FacturaID": factura_id,
        "FacturaNumar": factura_numar,
        "CodFiscal": doc.partner.cui,
    }
    assert tuple(values) == BANK_TAGS
    root = ET.Element(root_tag)
    item = ET.SubElement(root, "Linie")
    for tag in BANK_TAGS:
        if tag in _BANK_OPTIONAL and not values[tag]:
            continue
        ET.SubElement(item, tag).text = values[tag]
    ET.indent(root)
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"
    return RenderedFile(xml=xml, filename=f"{prefix}_{_ro_date(doc.date, '-')}.xml", folder=folder)


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


FIXTURE_TREASURY = "5121.01"


def bank_fixture_documents() -> dict[str, CanonicalDocument]:
    """Synthetic bank lines behind ``fixtures/saga/{incasare,plata}.xml`` (invented CUIs; the
    IBAN is the textbook example, not a client's), already bound to partner and invoice."""
    tenant = TenantRef(cui="1000009", saga_firm_folder="0001")

    def line(kind: str, n: int, date_: str, amount: str, desc: str, partner: PartnerRef, maps):
        return CanonicalDocument(
            job_id=f"fixture-{kind}",
            tenant=tenant,
            period=date_[:7],
            doc_class=kind,
            number=f"EXT-0f0f0f0f-{n}",
            date=date_,
            partner=partner,
            totals=Totals(net=amount, vat="0.00", gross=amount),
            lines=[Line(desc=desc, net=amount, vat_rate="0", vat="0.00", gross=amount)],
            source=SourceRef(
                kind="pdf",
                bucket_key=f"fixtures/saga/{kind}.statement.pdf",
                content_type="application/pdf",
                source_hash=("c" if kind == "incasare" else "d") * 64,
            ),
            maps={"iban": "RO49AAAA1B31007593840000", "statement_id": "0f0f0f0f", **maps},
        )

    incasare = line(
        "incasare",
        2,
        "2026-09-20",
        "182.11",
        "Incasare CLIENT TEST SRL FX-101",
        PartnerRef(cui="20000005", name="Client Test SRL", role="customer"),
        {"factura_id": "fixture-iesire", "factura_numar": "FX-101"},
    )
    plata = line(
        "plata",
        1,
        "2026-09-25",
        "242.00",
        "Plata FURNIZOR TEST SRL fact A-77",
        PartnerRef(cui="20000005", name="Furnizor Test SRL", role="supplier"),
        {"factura_numar": "A-77", "referinta": "OP-77"},
    )
    return {"incasare": incasare, "plata": plata}
