"""XML first (LAW L14): SPV zips and UBL CIUS-RO invoices → CanonicalDocument fields.

An SPV download is a zip holding the invoice XML and its signature companion
(``semnatura_*.xml``). Members are told apart by their root element, never by file name.
The invoice XML is the primary; a PDF of the same document is not parsed.

Every total is checked against the lines (fail closed):

- invoice lines sum to ``LineExtensionAmount``;
- ``LineExtension − AllowanceTotal + ChargeTotal = TaxExclusive``;
- each VAT subtotal's taxable amount equals its lines, and the subtotals sum to the VAT;
- ``TaxExclusive + VAT = TaxInclusive`` and ``TaxInclusive − Prepaid + Rounding = Payable``.

Document-level allowances and charges become their own lines, so the lines always
sum to the document. Line VAT is the line's net × rate, with the subtotal's cents
handed to the largest lines so each subtotal adds up exactly.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree as ET

from pydantic import Field

from poarta_contabila.types import (
    CanonicalDocument,
    Closed,
    Cui,
    FiscalDate,
    JobRecord,
    Line,
    Money,
    PartnerRef,
    Rate,
    SourceRef,
    Totals,
    cui_key,
)

INVOICE_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
CREDIT_NOTE_NS = "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"
SIGNATURE_NS = "http://www.w3.org/2000/09/xmldsig#"
NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}
_ROOTS = {
    f"{{{INVOICE_NS}}}Invoice": "Invoice",
    f"{{{CREDIT_NOTE_NS}}}CreditNote": "CreditNote",
}
_SIGNATURE = f"{{{SIGNATURE_NS}}}Signature"
_CREDIT_TYPE_CODES = {"381"}
_MAX_MEMBER = 20 * 1024 * 1024
_CENT = Decimal("0.01")


class UblError(ValueError):
    """The XML is not a readable, self-consistent UBL invoice. Nothing is guessed."""


@dataclass(frozen=True)
class SpvZip:
    """An SPV download: one invoice XML plus, usually, its signature companion."""

    invoice_name: str
    invoice: bytes
    signature_name: str | None
    signature: bytes | None
    other_members: tuple[str, ...] = ()


class UblParty(Closed):
    cui: Cui | None
    vat_id: str | None
    name: str
    country: str | None


class UblLine(Closed):
    desc: str
    qty: str | None
    unit: str | None
    net: Money
    category: str
    rate: Rate
    document_level: bool = False


class UblSubtotal(Closed):
    category: str
    rate: Rate
    taxable: Money
    vat: Money


class UblInvoice(Closed):
    root: Literal["Invoice", "CreditNote"]
    type_code: str
    number: str
    issue_date: FiscalDate
    due_date: FiscalDate | None
    currency: str
    supplier: UblParty
    customer: UblParty
    net: Money
    vat: Money
    gross: Money
    payable: Money
    lines: list[UblLine]
    subtotals: list[UblSubtotal]
    billing_ref: str | None = None
    note: list[str] = Field(default_factory=list)

    @property
    def is_credit_note(self) -> bool:
        return self.root == "CreditNote" or self.type_code in _CREDIT_TYPE_CODES


# ----- zip -----


def _parse_xml(data: bytes, where: str) -> ET.Element:
    head = data.upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise UblError(f"{where}: DTDs and entities are refused")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise UblError(f"{where}: not well-formed XML ({exc})") from exc


def read_spv_zip(source: str | Path | bytes) -> SpvZip:
    """Split an SPV zip by root element: exactly one UBL invoice, at most one signature."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, bytes) else source)
    except zipfile.BadZipFile as exc:
        raise UblError(f"not a zip: {exc}") from exc
    invoices: list[tuple[str, bytes]] = []
    signatures: list[tuple[str, bytes]] = []
    others: list[str] = []
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if info.file_size > _MAX_MEMBER:
                raise UblError(f"{info.filename}: member larger than {_MAX_MEMBER} bytes")
            if not info.filename.lower().endswith(".xml"):
                others.append(info.filename)
                continue
            data = zf.read(info)
            tag = _parse_xml(data, info.filename).tag
            if tag in _ROOTS:
                invoices.append((info.filename, data))
            elif tag == _SIGNATURE:
                signatures.append((info.filename, data))
            else:
                raise UblError(f"{info.filename}: unknown root element {tag}")
    if len(invoices) != 1:
        raise UblError(f"expected one invoice XML in the zip, found {len(invoices)}")
    if len(signatures) > 1:
        raise UblError(f"expected at most one signature XML, found {len(signatures)}")
    sig_name, sig = signatures[0] if signatures else (None, None)
    return SpvZip(invoices[0][0], invoices[0][1], sig_name, sig, tuple(others))


# ----- invoice -----


def _text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    found = el.find(path, NS)
    if found is None or found.text is None:
        return None
    return found.text.strip() or None


def _need(el: ET.Element, path: str, where: str) -> str:
    value = _text(el, path)
    if value is None:
        raise UblError(f"{where}: missing {path}")
    return value


def _dec(raw: str | None, where: str) -> Decimal:
    try:
        return Decimal(raw or "")
    except InvalidOperation as exc:
        raise UblError(f"{where}: not a number: {raw!r}") from exc


def _money(d: Decimal) -> str:
    return str(d.quantize(_CENT))


def _amount(el: ET.Element, path: str, currency: str, where: str, *, required: bool = True):
    node = el.find(path, NS)
    if node is None or not (node.text or "").strip():
        if required:
            raise UblError(f"{where}: missing {path}")
        return Decimal(0)
    cur = node.get("currencyID")
    if cur is not None and cur != currency:
        raise UblError(f"{where}: {path} in {cur}, document is in {currency}")
    value = _dec(node.text.strip(), f"{where} {path}")
    if value.quantize(_CENT) != value:
        raise UblError(f"{where}: {path} has more than two decimals")
    return value


def _rate(raw: str | None, where: str) -> str:
    value = _dec(raw or "0", where)
    if value < 0:
        raise UblError(f"{where}: negative VAT rate")
    return format(value.normalize(), "f")


def _party(root: ET.Element, path: str, where: str) -> UblParty:
    party = root.find(f"{path}/cac:Party", NS)
    if party is None:
        raise UblError(f"{where}: missing {path}")
    vat_id = _text(party, "cac:PartyTaxScheme/cbc:CompanyID")
    legal_id = _text(party, "cac:PartyLegalEntity/cbc:CompanyID")
    cui = cui_key(vat_id)
    if cui is None and legal_id and legal_id.upper().removeprefix("RO").strip().isdigit():
        cui = cui_key(legal_id)  # non-VAT payers carry the CUI as the legal id
    name = _text(party, "cac:PartyLegalEntity/cbc:RegistrationName") or _text(
        party, "cac:PartyName/cbc:Name"
    )
    if not name:
        raise UblError(f"{where}: {path} has no name")
    return UblParty(
        cui=cui,
        vat_id=vat_id,
        name=name,
        country=_text(party, "cac:PostalAddress/cac:Country/cbc:IdentificationCode"),
    )


def parse_ubl(data: bytes, *, where: str = "invoice") -> UblInvoice:
    """Read a UBL Invoice or CreditNote and check its totals. Raises :class:`UblError`."""
    root = _parse_xml(data, where)
    kind = _ROOTS.get(root.tag)
    if kind is None:
        raise UblError(f"{where}: root {root.tag} is not a UBL Invoice or CreditNote")
    line_tag, qty_tag = (
        ("cac:InvoiceLine", "cbc:InvoicedQuantity")
        if kind == "Invoice"
        else ("cac:CreditNoteLine", "cbc:CreditedQuantity")
    )
    type_code = _need(root, f"cbc:{kind}TypeCode", where)
    currency = _need(root, "cbc:DocumentCurrencyCode", where)

    lines: list[UblLine] = []
    for i, el in enumerate(root.findall(line_tag, NS), start=1):
        at = f"{where} line {i}"
        qty_el = el.find(qty_tag, NS)
        lines.append(
            UblLine(
                desc=_text(el, "cac:Item/cbc:Name") or _text(el, "cac:Item/cbc:Description") or "",
                qty=(qty_el.text or "").strip() or None if qty_el is not None else None,
                unit=qty_el.get("unitCode") if qty_el is not None else None,
                net=_money(_amount(el, "cbc:LineExtensionAmount", currency, at)),
                category=_need(el, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID", at),
                rate=_rate(_text(el, "cac:Item/cac:ClassifiedTaxCategory/cbc:Percent"), at),
            )
        )
    if not lines:
        raise UblError(f"{where}: no {line_tag} lines")

    for i, el in enumerate(root.findall("cac:AllowanceCharge", NS), start=1):
        at = f"{where} allowance/charge {i}"
        charge = _need(el, "cbc:ChargeIndicator", at).lower()
        if charge not in ("true", "false"):
            raise UblError(f"{at}: ChargeIndicator must be true or false")
        amount = _amount(el, "cbc:Amount", currency, at)
        reason = _text(el, "cbc:AllowanceChargeReason")
        lines.append(
            UblLine(
                desc=reason or ("Taxă" if charge == "true" else "Reducere"),
                qty=None,
                unit=None,
                net=_money(amount if charge == "true" else -amount),
                category=_need(el, "cac:TaxCategory/cbc:ID", at),
                rate=_rate(_text(el, "cac:TaxCategory/cbc:Percent"), at),
                document_level=True,
            )
        )

    totals = root.find("cac:LegalMonetaryTotal", NS)
    if totals is None:
        raise UblError(f"{where}: missing LegalMonetaryTotal")
    line_ext = _amount(totals, "cbc:LineExtensionAmount", currency, where)
    allowance = _amount(totals, "cbc:AllowanceTotalAmount", currency, where, required=False)
    charges = _amount(totals, "cbc:ChargeTotalAmount", currency, where, required=False)
    net = _amount(totals, "cbc:TaxExclusiveAmount", currency, where)
    gross = _amount(totals, "cbc:TaxInclusiveAmount", currency, where)
    prepaid = _amount(totals, "cbc:PrepaidAmount", currency, where, required=False)
    rounding = _amount(totals, "cbc:PayableRoundingAmount", currency, where, required=False)
    payable = _amount(totals, "cbc:PayableAmount", currency, where)

    item_sum = sum((Decimal(ln.net) for ln in lines if not ln.document_level), Decimal(0))
    doc_level = sum((Decimal(ln.net) for ln in lines if ln.document_level), Decimal(0))
    if item_sum != line_ext:
        raise UblError(f"{where}: lines sum to {item_sum}, LineExtensionAmount is {line_ext}")
    if doc_level != charges - allowance:
        raise UblError(f"{where}: allowances/charges {doc_level} ≠ totals {charges - allowance}")
    if line_ext + doc_level != net:
        raise UblError(f"{where}: LineExtension {line_ext} {doc_level:+} ≠ TaxExclusive {net}")

    tax_totals = [
        t
        for t in root.findall("cac:TaxTotal", NS)
        if (t.find("cbc:TaxAmount", NS) is not None)
        and t.find("cbc:TaxAmount", NS).get("currencyID", currency) == currency
    ]
    if len(tax_totals) != 1:
        raise UblError(f"{where}: expected one TaxTotal in {currency}, found {len(tax_totals)}")
    vat = _amount(tax_totals[0], "cbc:TaxAmount", currency, where)
    subtotals = []
    for i, st in enumerate(tax_totals[0].findall("cac:TaxSubtotal", NS), start=1):
        at = f"{where} VAT subtotal {i}"
        subtotals.append(
            UblSubtotal(
                category=_need(st, "cac:TaxCategory/cbc:ID", at),
                rate=_rate(_text(st, "cac:TaxCategory/cbc:Percent"), at),
                taxable=_money(_amount(st, "cbc:TaxableAmount", currency, at)),
                vat=_money(_amount(st, "cbc:TaxAmount", currency, at)),
            )
        )
    if sum((Decimal(s.vat) for s in subtotals), Decimal(0)) != vat:
        raise UblError(f"{where}: VAT subtotals do not sum to TaxAmount {vat}")
    if net + vat != gross:
        raise UblError(f"{where}: TaxExclusive {net} + VAT {vat} ≠ TaxInclusive {gross}")
    if gross - prepaid + rounding != payable:
        raise UblError(f"{where}: TaxInclusive − Prepaid + Rounding ≠ PayableAmount {payable}")

    invoice = UblInvoice(
        root=kind,
        type_code=type_code,
        number=_need(root, "cbc:ID", where),
        issue_date=_need(root, "cbc:IssueDate", where),
        due_date=_text(root, "cbc:DueDate"),
        currency=currency,
        supplier=_party(root, "cac:AccountingSupplierParty", where),
        customer=_party(root, "cac:AccountingCustomerParty", where),
        net=_money(net),
        vat=_money(vat),
        gross=_money(gross),
        payable=_money(payable),
        lines=lines,
        subtotals=subtotals,
        billing_ref=_text(root, "cac:BillingReference/cac:InvoiceDocumentReference/cbc:ID"),
        note=[n.text.strip() for n in root.findall("cbc:Note", NS) if (n.text or "").strip()],
    )
    line_vats(invoice)  # every line group must have a subtotal that adds up
    return invoice


def line_vats(invoice: UblInvoice) -> list[str]:
    """VAT per line: net × rate, with each subtotal's remaining cents on its largest lines."""
    out = [Decimal(0)] * len(invoice.lines)
    groups: dict[tuple[str, str], list[int]] = {}
    for i, ln in enumerate(invoice.lines):
        groups.setdefault((ln.category, ln.rate), []).append(i)
    subtotals = {(s.category, s.rate): s for s in invoice.subtotals}
    if set(groups) != set(subtotals):
        raise UblError(
            f"VAT subtotals {sorted(subtotals)} do not match line categories {sorted(groups)}"
        )
    for key, idxs in groups.items():
        st = subtotals[key]
        nets = [Decimal(invoice.lines[i].net) for i in idxs]
        if sum(nets, Decimal(0)) != Decimal(st.taxable):
            raise UblError(f"VAT subtotal {key}: taxable {st.taxable} ≠ lines {sum(nets)}")
        rate = Decimal(st.rate) / 100
        vats = [(n * rate).quantize(_CENT, rounding=ROUND_HALF_UP) for n in nets]
        cents = int((Decimal(st.vat) - sum(vats, Decimal(0))) / _CENT)
        if abs(cents) > len(idxs):
            raise UblError(f"VAT subtotal {key}: {st.vat} is not {st.rate}% of {st.taxable}")
        order = sorted(range(len(idxs)), key=lambda j: (-abs(nets[j]), j))
        for j in order[: abs(cents)]:
            vats[j] += _CENT if cents > 0 else -_CENT
        for j, i in enumerate(idxs):
            out[i] = vats[j]
    return [_money(v) for v in out]


def to_canonical(invoice: UblInvoice, *, job: JobRecord, source: SourceRef) -> CanonicalDocument:
    """The tenant's view of the invoice: side, partner, signed totals and lines.

    A credit note (``CreditNote`` root or type 381) carries positive amounts that mean a
    reduction, so they are negated; an invoice with negative totals is a storno as sent.
    """
    tenant = job.tenant.cui
    sup, cus = invoice.supplier.cui == tenant, invoice.customer.cui == tenant
    if sup == cus:
        raise UblError(
            "tenant is "
            + ("both supplier and customer" if sup else "neither supplier nor customer")
            + " on the invoice"
        )
    sign = Decimal(-1) if invoice.is_credit_note else Decimal(1)
    storno = invoice.is_credit_note or Decimal(invoice.gross) < 0
    side = "iesire" if sup else "intrare"
    other = invoice.customer if sup else invoice.supplier
    vats = line_vats(invoice)
    lines = []
    for ln, vat in zip(invoice.lines, vats, strict=True):
        net, v = Decimal(ln.net) * sign, Decimal(vat) * sign
        qty = ln.qty
        if qty is not None and sign < 0 and not qty.startswith("-"):
            qty = "-" + qty
        lines.append(
            Line(
                desc=ln.desc,
                qty=qty,
                unit=ln.unit,
                net=_money(net),
                vat_rate=ln.rate,
                vat=_money(v),
                gross=_money(net + v),
            )
        )
    return CanonicalDocument(
        job_id=job.job_id,
        tenant=job.tenant,
        period=invoice.issue_date[:7],
        doc_class=f"storn_{side}" if storno else side,
        number=invoice.number,
        date=invoice.issue_date,
        partner=PartnerRef(cui=other.cui, name=other.name, role="customer" if sup else "supplier"),
        currency=invoice.currency,
        totals=Totals(
            net=_money(Decimal(invoice.net) * sign),
            vat=_money(Decimal(invoice.vat) * sign),
            gross=_money(Decimal(invoice.gross) * sign),
        ),
        lines=lines,
        is_storno=storno,
        storno_of=invoice.billing_ref,
        source=source,
    )
