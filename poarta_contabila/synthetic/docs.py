"""Synthetic documents: the files a path reads, built from a seed.

Each document is a small frozen record (what it says) with methods that render the bytes a
person would upload: an SPV zip or UBL XML (CIUS-RO, the tags of ``fixtures/ubl``), a PDF
(``synthetic_docs.text_pdf``), a statement's ``POST /extras`` body, an expense report and
its ``decont_split`` answer. :class:`Gen` draws them for one firm-month from a seed and
numbers them so no two documents of a month share a number.

Amounts are integer cents. VAT is per (category, rate) group, half up, as UBL subtotals.
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import io
import itertools
import random
import zipfile
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal
from xml.sax.saxutils import escape

from poarta_contabila.synthetic.firms import Firm, Party
from poarta_contabila.synthetic_docs import text_pdf

ZIP_TIME = (2026, 10, 1, 0, 0, 0)  # every member of every zip: the same bytes on every run
SIGNATURE = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b"<!-- Synthetic signature companion: only the root element matters to the reader. -->\n"
    b'<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">'
    b"<ds:SignedInfo/><ds:SignatureValue>AAAA</ds:SignatureValue></ds:Signature>\n"
)
BANK = "BANCA SINTETICA SA"


def money(cents: int) -> str:
    """``1234.56`` / ``-0.50``: the system's Money string."""
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def ro_money(cents: int) -> str:
    """``1.234,56``: how a Romanian bank prints an amount."""
    whole = f"{abs(cents) // 100:,}".replace(",", ".")
    return f"{'-' if cents < 0 else ''}{whole},{abs(cents) % 100:02d}"


def ro_date(day: str) -> str:
    return f"{day[8:10]}.{day[5:7]}.{day[:4]}"


def vat_of(taxable: int, rate: int) -> int:
    return int((Decimal(taxable) * rate / 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def stable_zip(members: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members:
            zf.writestr(zipfile.ZipInfo(name, date_time=ZIP_TIME), data)
    return buf.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ----- invoices -----


@dataclass(frozen=True)
class Item:
    desc: str
    net: int  # cents, positive
    rate: int = 21  # percent
    account: str = "604"  # where SAGA posts the net (expense or income account)
    category: str = "S"  # UBL tax category: S standard, AE reverse charge, O not subject
    qty: int = 1


@dataclass(frozen=True)
class Invoice:
    """An invoice or a credit note (``credit_of`` = the number it reverses)."""

    ref: str
    side: Literal["in", "out"]
    number: str
    issued: str
    partner: Party
    items: tuple[Item, ...]
    due: str | None = None
    currency: str = "RON"
    credit_of: str | None = None
    spv_id: str = "5000000001"

    @property
    def is_credit(self) -> bool:
        return self.credit_of is not None

    @property
    def doc_class(self) -> str:
        side = "intrare" if self.side == "in" else "iesire"
        return f"storn_{side}" if self.is_credit else side

    @property
    def foreign(self) -> bool:
        return self.partner.cui is None

    @property
    def period(self) -> str:
        return self.issued[:7]

    def groups(self) -> dict[tuple[str, int], tuple[int, int]]:
        """(category, rate) → (taxable, VAT), in cents, positive."""
        taxable: dict[tuple[str, int], int] = {}
        for it in self.items:
            taxable[(it.category, it.rate)] = taxable.get((it.category, it.rate), 0) + it.net
        return {k: (v, vat_of(v, k[1])) for k, v in taxable.items()}

    @property
    def net(self) -> int:
        return sum(it.net for it in self.items)

    @property
    def vat(self) -> int:
        return sum(v for _, v in self.groups().values())

    @property
    def gross(self) -> int:
        return self.net + self.vat

    @property
    def signed(self) -> int:
        """The gross as the books carry it: a credit note is negative."""
        return -self.gross if self.is_credit else self.gross

    def parties(self, firm: Firm) -> tuple[Party, Party]:
        me = Party(key="self", name=firm.name, analytic="", cui=firm.cui, vat_payer=firm.vat_payer)
        return (self.partner, me) if self.side == "in" else (me, self.partner)

    def xml(self, firm: Firm) -> bytes:
        """The UBL Invoice / CreditNote (CIUS-RO), as SPV would hold it."""
        root = "CreditNote" if self.is_credit else "Invoice"
        line_tag, qty_tag = (
            ("CreditNoteLine", "CreditedQuantity")
            if self.is_credit
            else ("InvoiceLine", "InvoicedQuantity")
        )
        cur = self.currency
        supplier, customer = self.parties(firm)
        out = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<!-- Synthetic CIUS-RO document. Firms, CUIs and amounts are invented. -->",
            f'<{root} xmlns="urn:oasis:names:specification:ubl:schema:xsd:{root}-2"',
            '  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:'
            'CommonAggregateComponents-2"',
            '  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">',
            "  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#"
            "urn:efactura.mfinante.ro:CIUS-RO:1.0.1</cbc:CustomizationID>",
            f"  <cbc:ID>{escape(self.number)}</cbc:ID>",
            f"  <cbc:IssueDate>{self.issued}</cbc:IssueDate>",
        ]
        if self.due and not self.is_credit:
            out.append(f"  <cbc:DueDate>{self.due}</cbc:DueDate>")
        out.append(
            f"  <cbc:{root}TypeCode>{'381' if self.is_credit else '380'}</cbc:{root}TypeCode>"
        )
        out.append(f"  <cbc:DocumentCurrencyCode>{cur}</cbc:DocumentCurrencyCode>")
        if self.is_credit:
            out.append(
                "  <cac:BillingReference><cac:InvoiceDocumentReference>"
                f"<cbc:ID>{escape(self.credit_of or '')}</cbc:ID>"
                "</cac:InvoiceDocumentReference></cac:BillingReference>"
            )
        for tag, party in (
            ("AccountingSupplierParty", supplier),
            ("AccountingCustomerParty", customer),
        ):
            out.append(f"  <cac:{tag}>{_party_xml(party)}</cac:{tag}>")
        out.append(
            f'  <cac:TaxTotal><cbc:TaxAmount currencyID="{cur}">{money(self.vat)}</cbc:TaxAmount>'
        )
        for (cat, rate), (taxable, vat) in self.groups().items():
            out.append(
                f'    <cac:TaxSubtotal><cbc:TaxableAmount currencyID="{cur}">{money(taxable)}'
                f'</cbc:TaxableAmount><cbc:TaxAmount currencyID="{cur}">{money(vat)}'
                f"</cbc:TaxAmount>{_category('TaxCategory', cat, rate)}</cac:TaxSubtotal>"
            )
        out.append("  </cac:TaxTotal>")
        out.append(
            "  <cac:LegalMonetaryTotal>"
            f'<cbc:LineExtensionAmount currencyID="{cur}">{money(self.net)}'
            "</cbc:LineExtensionAmount>"
            f'<cbc:TaxExclusiveAmount currencyID="{cur}">{money(self.net)}'
            "</cbc:TaxExclusiveAmount>"
            f'<cbc:TaxInclusiveAmount currencyID="{cur}">{money(self.gross)}'
            "</cbc:TaxInclusiveAmount>"
            f'<cbc:PayableAmount currencyID="{cur}">{money(self.gross)}</cbc:PayableAmount>'
            "</cac:LegalMonetaryTotal>"
        )
        for i, it in enumerate(self.items, start=1):
            price = Decimal(it.net) / 100 / it.qty
            out.append(
                f"  <cac:{line_tag}><cbc:ID>{i}</cbc:ID>"
                f'<cbc:{qty_tag} unitCode="H87">{it.qty}.000</cbc:{qty_tag}>'
                f'<cbc:LineExtensionAmount currencyID="{cur}">{money(it.net)}'
                "</cbc:LineExtensionAmount>"
                f"<cac:Item><cbc:Name>{escape(it.desc)}</cbc:Name>"
                f"{_category('ClassifiedTaxCategory', it.category, it.rate)}</cac:Item>"
                f'<cac:Price><cbc:PriceAmount currencyID="{cur}">{price:.4f}</cbc:PriceAmount>'
                f"</cac:Price></cac:{line_tag}>"
            )
        out.append(f"</{root}>")
        return ("\n".join(out) + "\n").encode("utf-8")

    def spv_zip(self, firm: Firm) -> bytes:
        """The SPV download: ``<id>.xml`` and ``semnatura_<id>.xml``, fixed timestamps."""
        return stable_zip(
            [(f"{self.spv_id}.xml", self.xml(firm)), (f"semnatura_{self.spv_id}.xml", SIGNATURE)]
        )

    def pdf(self, firm: Firm) -> bytes:
        """A printed copy (a companion when the XML exists; the document from abroad)."""
        supplier, customer = self.parties(firm)
        title = "FACTURA STORNO" if self.is_credit else "FACTURA"
        lines = [
            f"{title} {self.number}" + (f" (storno la {self.credit_of})" if self.credit_of else ""),
            f"Data emiterii: {ro_date(self.issued)}"
            + (f"   Scadenta: {ro_date(self.due)}" if self.due else ""),
            f"Furnizor: {supplier.name}   CIF: {supplier.tax_id}   Tara: {supplier.country}",
            f"Client: {customer.name}   CIF: {customer.tax_id}   Tara: {customer.country}",
            "",
            "Nr  Denumire                         Valoare      Cota",
        ]
        for i, it in enumerate(self.items, start=1):
            lines.append(f"{i:<3} {it.desc[:32]:<32} {ro_money(it.net):>12} {it.rate:>4}%")
        lines += [
            "",
            f"Total fara TVA: {ro_money(self.net)} {self.currency}",
            f"TVA: {ro_money(self.vat)} {self.currency}",
            f"Total de plata: {ro_money(self.gross)} {self.currency}",
        ]
        return text_pdf([[_latin1(x) for x in lines]])


def _party_xml(p: Party) -> str:
    address = "<cac:PostalAddress><cbc:StreetName>Strada Sintetica 1</cbc:StreetName>"
    if p.country == "RO":
        address += "<cbc:CityName>Sector 1</cbc:CityName><cbc:CountrySubentity>RO-B"
        address += "</cbc:CountrySubentity>"
    else:
        address += "<cbc:CityName>Exempla</cbc:CityName>"
    address += f"<cac:Country><cbc:IdentificationCode>{p.country}</cbc:IdentificationCode>"
    address += "</cac:Country></cac:PostalAddress>"
    tax = ""
    if p.cui is None or p.vat_payer:
        tax = (
            f"<cac:PartyTaxScheme><cbc:CompanyID>{escape(p.tax_id)}</cbc:CompanyID>"
            "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"
        )
    legal_id = (
        p.cui if (p.cui and not p.vat_payer) else ("HRB 0001" if p.cui is None else "J00/1/2021")
    )
    legal = (
        f"<cac:PartyLegalEntity><cbc:RegistrationName>{escape(p.name)}"
        f"</cbc:RegistrationName><cbc:CompanyID>{legal_id}</cbc:CompanyID>"
        "</cac:PartyLegalEntity>"
    )
    return f"<cac:Party>{address}{tax}{legal}</cac:Party>"


def _category(tag: str, cat: str, rate: int) -> str:
    return (
        f"<cac:{tag}><cbc:ID>{cat}</cbc:ID><cbc:Percent>{rate}.00</cbc:Percent>"
        f"<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:{tag}>"
    )


def _latin1(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")


# ----- receipts, workings, payroll -----


@dataclass(frozen=True)
class Bon:
    """A bon fiscal (receipt); our CUI printed on it or not (TVA deductibility needs it)."""

    ref: str
    number: str
    day: str
    merchant: Party
    items: tuple[Item, ...]
    our_cui: str | None = None
    paid: Literal["numerar", "card"] = "numerar"

    @property
    def gross(self) -> int:
        return sum(it.net + vat_of(it.net, it.rate) for it in self.items)

    @property
    def vat(self) -> int:
        return sum(vat_of(it.net, it.rate) for it in self.items)

    def pdf(self) -> bytes:
        lines = [
            self.merchant.name,
            f"CIF: {self.merchant.tax_id}",
            "BON FISCAL",
        ]
        if self.our_cui:
            lines.append(f"CIF CLIENT: RO{self.our_cui}")
        for it in self.items:
            gross = it.net + vat_of(it.net, it.rate)
            lines.append(
                f"{it.desc[:24]:<24} {ro_money(gross):>10} {'A' if it.rate == 21 else 'B'}"
            )
        lines += [
            f"TOTAL {ro_money(self.gross)} LEI",
            f"TVA {ro_money(self.vat)}",
            f"{self.paid.upper()} {ro_money(self.gross)}",
            f"BF {self.number}   {ro_date(self.day)}",
        ]
        return text_pdf([[_latin1(x) for x in lines]])


@dataclass(frozen=True)
class Workings:
    """A calculation sheet: evidence, never a posting source."""

    ref: str
    title: str
    rows: tuple[str, ...]

    def pdf(self) -> bytes:
        return text_pdf([[_latin1(self.title), "", *(_latin1(r) for r in self.rows)]])


@dataclass(frozen=True)
class Payroll:
    """A stat de salarii (evidence, LAW L17): the books post it; nothing here posts it."""

    ref: str
    period: str
    day: str  # the day net pay leaves the bank
    employees: int
    gross: int

    @property
    def cas(self) -> int:
        return vat_of(self.gross, 25)

    @property
    def cass(self) -> int:
        return vat_of(self.gross, 10)

    @property
    def tax(self) -> int:
        return vat_of(self.gross - self.cas - self.cass, 10)

    @property
    def net(self) -> int:
        return self.gross - self.cas - self.cass - self.tax

    @property
    def cam(self) -> int:
        return int((Decimal(self.gross) * Decimal("0.0225")).quantize(Decimal(1), ROUND_HALF_UP))

    def pdf(self, firm: Firm) -> bytes:
        return text_pdf(
            [
                [
                    _latin1(x)
                    for x in (
                        f"STAT DE SALARII  {self.period}",
                        f"{firm.name}   CUI {firm.cui}",
                        f"Numar salariati: {self.employees}",
                        f"Salarii brute: {ro_money(self.gross)}",
                        f"CAS 25%: {ro_money(self.cas)}   CASS 10%: {ro_money(self.cass)}",
                        f"Impozit 10%: {ro_money(self.tax)}   CAM 2,25%: {ro_money(self.cam)}",
                        f"Rest de plata: {ro_money(self.net)}",
                    )
                ]
            ]
        )


# ----- bank -----


@dataclass(frozen=True)
class BankLine:
    """A statement movement. ``debit`` = money out (plată), ``credit`` = money in (încasare).

    ``settles``: the invoices it pays or collects, (invoice ref, cents); ``kind`` says what
    the books post it against."""

    day: str
    side: Literal["debit", "credit"]
    amount: int
    description: str
    reference: str | None = None
    partner: Party | None = None
    settles: tuple[tuple[str, int], ...] = ()
    kind: Literal["invoice", "fee", "salary", "other"] = "invoice"


@dataclass(frozen=True)
class Statement:
    ref: str
    holder_cui: str
    holder_name: str
    iban: str
    day: str  # statement date
    opening: int
    lines: tuple[BankLine, ...]

    @property
    def closing(self) -> int:
        out = sum(ln.amount for ln in self.lines if ln.side == "debit")
        into = sum(ln.amount for ln in self.lines if ln.side == "credit")
        return self.opening - out + into

    def meta(self) -> dict[str, str]:
        return {
            "iban": self.iban,
            "holder_cui": f"RO{self.holder_cui}",
            "currency": "RON",
            "opening": money(self.opening),
            "closing": money(self.closing),
            "statement_date": self.day,
        }

    def tables(self) -> list[dict[str, Any]]:
        rows = [
            [
                ro_date(ln.day),
                ln.description,
                ln.reference or "",
                ro_money(ln.amount) if ln.side == "debit" else "",
                ro_money(ln.amount) if ln.side == "credit" else "",
            ]
            for ln in self.lines
        ]
        out = sum(ln.amount for ln in self.lines if ln.side == "debit")
        into = sum(ln.amount for ln in self.lines if ln.side == "credit")
        rows.append(["", "Total rulaje", "", ro_money(out), ro_money(into)])
        return [
            {
                "headers": ["Extras de cont", "", ""],
                "rows": [["Sold initial", "", ro_money(self.opening)]],
            },
            {"headers": ["Data", "Descriere", "Referinta", "Debit", "Credit"], "rows": rows},
        ]

    def pdf(self) -> bytes:
        iban = " ".join(self.iban[i : i + 4] for i in range(0, len(self.iban), 4))
        lines = [
            f"{BANK} - EXTRAS DE CONT",
            f"Titular: {self.holder_name}   CUI: RO{self.holder_cui}",
            f"IBAN: {iban}   Moneda: RON",
            f"Data extras: {ro_date(self.day)}",
            f"Sold initial: {ro_money(self.opening)}",
            "",
            "Data        Descriere                          Referinta   Debit      Credit",
        ]
        for ln in self.lines:
            debit = ro_money(ln.amount) if ln.side == "debit" else ""
            credit = ro_money(ln.amount) if ln.side == "credit" else ""
            lines.append(
                f"{ro_date(ln.day)}  {ln.description[:34]:<34} "
                f"{(ln.reference or '')[:10]:<10} {debit:>10} {credit:>10}"
            )
        lines += ["", f"Sold final: {ro_money(self.closing)}"]
        pages = [lines[i : i + 50] for i in range(0, len(lines), 50)]
        return text_pdf([[_latin1(x) for x in p] for p in pages])

    def upload(self, *, tables: bool = True) -> dict[str, Any]:
        """The body of ``POST /extras/{cui}``; without *tables* the server's reader reads."""
        body: dict[str, Any] = {
            "meta": self.meta(),
            "pdf_b64": base64.b64encode(self.pdf()).decode(),
        }
        if tables:
            body["tables"] = self.tables()
        return body


# ----- expense reports -----


PartFormat = Literal["xml", "pdf"]


@dataclass(frozen=True)
class ExpenseReport:
    """A decont de cheltuieli: a container whose parts a person names (``decont_split``)."""

    ref: str
    period: str
    employee: str
    parts: tuple[tuple[Bon | Invoice | Workings, PartFormat], ...]

    def pdf(self, firm: Firm) -> bytes:
        lines = [
            f"DECONT DE CHELTUIELI  {self.period}",
            f"{firm.name}   CUI {firm.cui}",
            f"Titular avans: {self.employee}",
            "",
        ]
        total = 0
        for i, (doc, _) in enumerate(self.parts, start=1):
            if isinstance(doc, Workings):
                lines.append(f"{i}. {doc.title}")
                continue
            gross = doc.gross
            total += gross
            label = doc.number if isinstance(doc, Invoice) else f"BF {doc.number}"
            lines.append(f"{i}. {label:<20} {ro_money(gross):>12}")
        lines += ["", f"Total decont: {ro_money(total)}"]
        return text_pdf([[_latin1(x) for x in lines]])

    def part_bytes(self, i: int, firm: Firm) -> bytes:
        doc, fmt = self.parts[i]
        if isinstance(doc, Invoice):
            return doc.spv_zip(firm) if fmt == "xml" else doc.pdf(firm)
        if isinstance(doc, Bon):
            return doc.pdf()
        return doc.pdf()

    def split_answer(self, firm: Firm) -> dict[str, Any]:
        """The ``decont_split`` answer that names every part as the catalog's children."""
        parts = []
        for i, (doc, fmt) in enumerate(self.parts):
            part: dict[str, Any] = {
                "part_hash": sha256(self.part_bytes(i, firm)),
                "bon_our_cui_on_doc": None,
                "counterparty_cui": None,
            }
            if isinstance(doc, Bon):  # evidence of the 542 settlement
                part.update(
                    source_doc_id="decont_part_evidence",
                    kinds=["pdf"],
                    bon_our_cui_on_doc=doc.our_cui is not None,
                )
            elif isinstance(doc, Invoice) and doc.foreign:
                part.update(source_doc_id="decont_part_evidence", kinds=[fmt])
            elif isinstance(doc, Invoice):
                part.update(
                    source_doc_id="ro_efactura_ubl" if fmt == "xml" else "ro_efactura_pdf",
                    kinds=["ubl_spv"] if fmt == "xml" else ["pdf"],
                    counterparty_cui=doc.partner.cui,
                )
            else:
                part.update(source_doc_id="workings", kinds=["pdf"])
            parts.append(part)
        return {"parts": parts}

    def upload(self, firm: Firm) -> dict[str, Any]:
        """The body of ``POST /decont/{cui}``."""
        return {
            "filename": f"{self.ref}.pdf",
            "period": self.period,
            "file_b64": base64.b64encode(self.pdf(firm)).decode(),
            "tenant_on_doc": True,
        }


# ----- the generator -----

PURCHASES = (
    ("Hartie copiator A4", "604", 21),
    ("Toner imprimanta", "604", 21),
    ("Servicii consultanta", "628", 21),
    ("Chirie birou", "612", 21),
    ("Carti tehnice", "604", 11),
    ("Servicii curierat", "624", 21),
    ("Abonament telefonie", "626", 21),
    ("Mentenanta echipamente", "611", 21),
)
SALES = (
    ("Servicii programare", "704", 21),
    ("Mentenanta aplicatie", "704", 21),
    ("Instruire personal", "704", 21),
    ("Carte tiparita", "707", 11),
)
ABROAD = (("Software subscription", "628"), ("Cloud hosting", "628"), ("Consulting", "628"))
RECEIPTS = (
    ("Carburant", "6022", 21),
    ("Rechizite", "604", 21),
    ("Masa protocol", "623", 21),
    ("Parcare", "628", 21),
)
_PREFIX = {"s1": "FA", "s2": "FB", "s3": "FG", "s4": "FD", "x1": "DE", "x2": "ES"}


@dataclass
class Gen:
    """Draws one firm-month's documents from a seed; numbers never repeat inside it."""

    firm: Firm
    period: str
    seed: int = 0
    rng: random.Random = field(init=False)
    _seq: Any = field(init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(f"{self.firm.key}:{self.firm.cui}:{self.period}:{self.seed}")
        self._seq = itertools.count(1)

    @property
    def yymm(self) -> str:
        return self.period[2:4] + self.period[5:7]

    @property
    def last_day(self) -> str:
        y, m = int(self.period[:4]), int(self.period[5:])
        return f"{self.period}-{calendar.monthrange(y, m)[1]:02d}"

    def day(self, d: int | None = None) -> str:
        return f"{self.period}-{d if d is not None else self.rng.randint(1, 26):02d}"

    def _n(self) -> int:
        return next(self._seq)

    def _amount(self, low: int = 50_00, high: int = 3_000_00) -> int:
        return self.rng.randint(low // 100, high // 100) * 100 + self.rng.choice((0, 50, 99))

    def _items(self, table, n: int | None, rates: tuple[int, ...] | None, vat: bool):
        n = n or self.rng.randint(1, 3)
        out = []
        for _ in range(n):
            desc, account, rate = self.rng.choice(table)
            if rates is not None:
                rate = self.rng.choice(rates)
            out.append(Item(desc, self._amount(), rate if vat else 0, account, "S" if vat else "O"))
        return tuple(out)

    def purchase(
        self,
        ref: str,
        *,
        partner: str = "s1",
        items: int | None = None,
        rates: tuple[int, ...] | None = None,
        day: int | None = None,
        number: str | None = None,
    ) -> Invoice:
        """An SPV invoice from a RO supplier (a neplătitor supplier charges no VAT)."""
        p = self.firm.party(partner)
        issued = self.day(day)
        n = self._n()
        return Invoice(
            ref=ref,
            side="in",
            number=number or f"{_PREFIX.get(p.key, 'F')} {self.yymm}{n:02d}",
            issued=issued,
            due=_plus_days(issued, 30),
            partner=p,
            items=self._items(PURCHASES, items, rates, p.vat_payer),
            spv_id=f"5{self.firm.folder}{self.yymm}{n:03d}",
        )

    def sale(
        self,
        ref: str,
        *,
        partner: str = "c1",
        items: int | None = None,
        rates: tuple[int, ...] | None = None,
        day: int | None = None,
        number: str | None = None,
    ) -> Invoice:
        """An invoice the firm issues (a neplătitor firm charges no VAT)."""
        p = self.firm.party(partner)
        issued = self.day(day)
        n = self._n()
        return Invoice(
            ref=ref,
            side="out",
            number=number or f"SN{self.firm.folder[-1]} {self.yymm}{n:03d}",
            issued=issued,
            due=_plus_days(issued, 15),
            partner=p,
            items=self._items(SALES, items, rates, self.firm.vat_payer),
            spv_id=f"6{self.firm.folder}{self.yymm}{n:03d}",
        )

    def export_sale(self, ref: str, *, partner: str = "y1", day: int | None = None) -> Invoice:
        """A service to an EU business customer, invoiced in RON: reverse charge (AE, 0 %)."""
        p = self.firm.party(partner)
        issued = self.day(day)
        n = self._n()
        desc, account, _ = self.rng.choice(SALES)
        return Invoice(
            ref=ref,
            side="out",
            number=f"SN{self.firm.folder[-1]} {self.yymm}{n:03d}",
            issued=issued,
            due=_plus_days(issued, 30),
            partner=p,
            items=(Item(desc, self._amount(), 0, account, "AE"),),
            spv_id=f"6{self.firm.folder}{self.yymm}{n:03d}",
        )

    def credit_note(
        self, ref: str, of: Invoice, *, day: int | None = None, share: int = 100
    ) -> Invoice:
        """A credit note reversing *share* percent of each item of *of*."""
        n = self._n()
        items = tuple(
            Item(it.desc, it.net * share // 100, it.rate, it.account, it.category, it.qty)
            for it in of.items
        )
        prefix = of.number.split(" ")[0]
        return Invoice(
            ref=ref,
            side=of.side,
            number=f"{prefix}C {self.yymm}{n:02d}",
            issued=self.day(day),
            partner=of.partner,
            items=items,
            credit_of=of.number,
            spv_id=f"7{self.firm.folder}{self.yymm}{n:03d}",
        )

    def foreign_purchase(
        self,
        ref: str,
        *,
        partner: str = "x1",
        items: int | None = None,
        day: int | None = None,
        currency: str = "EUR",
    ) -> Invoice:
        """Services from abroad: reverse charge (AE, 0 %) as the supplier invoices them."""
        p = self.firm.party(partner)
        n = self._n()
        chosen = [self.rng.choice(ABROAD) for _ in range(items or self.rng.randint(1, 2))]
        return Invoice(
            ref=ref,
            side="in",
            number=f"{_PREFIX.get(p.key, 'X')}-{self.yymm}{n:03d}",
            issued=self.day(day),
            partner=p,
            currency=currency,
            items=tuple(Item(d, self._amount(20_00, 900_00), 0, a, "AE") for d, a in chosen),
            spv_id=f"8{self.firm.folder}{self.yymm}{n:03d}",
        )

    def bon(
        self,
        ref: str,
        *,
        our_cui: bool = True,
        merchant: str = "s3",
        day: int | None = None,
        items: int | None = None,
    ) -> Bon:
        n = self._n()
        return Bon(
            ref=ref,
            number=f"{self.yymm}{n:03d}",
            day=self.day(day),
            merchant=self.firm.party(merchant),
            items=tuple(
                Item(d, self._amount(10_00, 400_00), r, a)
                for d, a, r in (self.rng.choice(RECEIPTS) for _ in range(items or 1))
            ),
            our_cui=self.firm.cui if our_cui else None,
        )

    def workings(self, ref: str, title: str = "Calcul diurna deplasare") -> Workings:
        return Workings(ref, title, (f"Zile: {self.rng.randint(1, 5)}", "Suma pe zi: 50,00"))

    def payroll(self, ref: str, *, employees: int = 2, day: int = 10) -> Payroll:
        gross = sum(self.rng.randint(4_500, 9_000) * 100 for _ in range(employees))
        return Payroll(ref, self.period, self.day(day), employees, gross)

    # bank lines

    def payment(
        self,
        inv: Invoice,
        *,
        amount: int | None = None,
        day: int | None = None,
        also: tuple[Invoice, ...] = (),
    ) -> BankLine:
        """The firm pays *inv* (and *also*: one line for several invoices)."""
        amount = inv.gross if amount is None else amount
        settles = ((inv.ref, amount), *((o.ref, o.gross) for o in also))
        total = sum(a for _, a in settles)
        numbers = " ".join(i.number for i in (inv, *also))
        return BankLine(
            self.day(day),
            "debit",
            total,
            f"Plata {inv.partner.name} fact {numbers}",
            f"OP{self.yymm}{self._n():02d}",
            inv.partner,
            settles,
        )

    def receipt(
        self,
        inv: Invoice,
        *,
        amount: int | None = None,
        day: int | None = None,
        also: tuple[Invoice, ...] = (),
    ) -> BankLine:
        """A customer pays *inv* (and *also*)."""
        amount = inv.gross if amount is None else amount
        settles = ((inv.ref, amount), *((o.ref, o.gross) for o in also))
        total = sum(a for _, a in settles)
        numbers = " ".join(i.number for i in (inv, *also))
        return BankLine(
            self.day(day),
            "credit",
            total,
            f"Incasare {inv.partner.name} {numbers}",
            f"IN{self.yymm}{self._n():02d}",
            inv.partner,
            settles,
        )

    def fee(self, *, amount: int = 1_250, day: int | None = None) -> BankLine:
        return BankLine(
            self.day(day or 28),
            "debit",
            amount,
            "Comision administrare cont",
            f"COM{self.yymm}",
            kind="fee",
        )

    def salaries(self, pay: Payroll) -> BankLine:
        return BankLine(
            pay.day,
            "debit",
            pay.net,
            f"Plata salarii {self.period}",
            f"SAL{self.yymm}",
            kind="salary",
        )

    def statement(self, ref: str, lines: list[BankLine], *, opening: int = 2_500_000) -> Statement:
        return Statement(
            ref=ref,
            holder_cui=self.firm.cui,
            holder_name=self.firm.name,
            iban=self.firm.iban,
            day=self.last_day,
            opening=opening,
            lines=tuple(sorted(lines, key=lambda ln: (ln.day, ln.reference or ""))),
        )

    def expense_report(
        self,
        ref: str,
        parts: list[tuple[Bon | Invoice | Workings, PartFormat]],
        *,
        employee: str = "ANGAJAT SINTETIC",
    ) -> ExpenseReport:
        return ExpenseReport(ref, self.period, employee, tuple(parts))


def _plus_days(day: str, n: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()
