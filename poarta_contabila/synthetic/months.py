"""A firm-month of synthetic data (WP-70): what is uploaded, and the books SAGA would hold.

:func:`month` draws a standard month for a firm — purchases and sales on SPV, a bank
statement that pays and collects some of them (and a fee), plus what the firm's profile
adds (services from abroad, receipts in an expense report, payroll) — posts every document
into a :class:`~poarta_contabila.synthetic.books.Book`, and lists the uploads in order.

A named defect (:data:`DEFECTS`) changes one thing about a clean month, so a run shows what
the pipeline does with it:

    missing_from_books      a purchase was never posted in SAGA
    in_books_no_document    SAGA holds a purchase no one uploaded
    amount_differs          a sale is booked 1.00 higher than its invoice
    vat_differs             a purchase's VAT is booked 1.00 higher
    posted_another_way      a purchase's VAT went into the cost (not 4426 / 4428)
    duplicate_upload        the same SPV zip is uploaded twice
    late_prior_month        a purchase of the month before arrives now (booked in its month)
    storno_of_acked         a credit note reverses a sale of the month
    bank_line_two_invoices  one payment settles two purchases
    partial_payment         a customer pays half of a sale

The same ``(firm, period, seed, defect)`` gives the same documents and the same bytes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from poarta_contabila.synthetic.books import Book
from poarta_contabila.synthetic.docs import (
    BankLine,
    ExpenseReport,
    Gen,
    Invoice,
    Payroll,
    Statement,
)
from poarta_contabila.synthetic.firms import Firm

Route = Literal["ingest", "extras", "decont"]


@dataclass
class Upload:
    """One thing a person uploads: an SPV zip (``/ingest``), a statement (``/extras``) or an
    expense report (``/decont``)."""

    ref: str
    route: Route
    doc: Invoice | Statement | ExpenseReport


@dataclass
class Month:
    firm: Firm
    period: str
    gen: Gen
    book: Book
    docs: dict[str, Any] = field(default_factory=dict)
    uploads: list[Upload] = field(default_factory=list)
    bank: list[BankLine] = field(default_factory=list)
    defect: str | None = None

    def add(self, doc: Any, *, upload: bool = True, post: bool = True, via: str | None = None):
        self.docs[doc.ref] = doc
        if post:
            self.book.post(doc, via=via)
        if upload and isinstance(doc, Invoice):
            self.uploads.append(Upload(doc.ref, "ingest", doc))
        return doc

    def statement(self, ref: str = "extras") -> Statement:
        """The month's statement over every bank line, opening at the books' bank balance
        (so it closes where the books do); its lines are posted as they settle."""
        bal = self.book.balances(self.period).get(self.firm.bank_account, {})
        opening = bal.get("open_d", 0) + bal.get("prev_d", 0)
        opening -= bal.get("open_c", 0) + bal.get("prev_c", 0)
        stmt = self.gen.statement(ref, list(self.bank), opening=opening)
        self.docs[ref] = stmt
        self.uploads.append(Upload(ref, "extras", stmt))
        return stmt

    def invoices(self) -> list[Invoice]:
        return [d for d in self.docs.values() if isinstance(d, Invoice)]

    def exports(self) -> dict[str, tuple[str, bytes, str | None]]:
        """``kind → (filename, bytes, product)`` for ``POST /tenants/{cui}/exports/{kind}``:
        the journal and balance of the firm's book of record, the report pack's journals
        (SAGA only) and the SPV register."""
        p = self.period
        if self.firm.book_of_record == "nextup":
            return {
                "rj": (f"rj-{p}.xlsx", self.book.nextup_rj(), "nextup"),
                "balanta": (f"balanta-{p}.xlsx", self.book.nextup_balanta(p), "nextup"),
                "spv_register": (f"spv-{p}.xlsx", self.book.spv_register(self.invoices(), p), None),
            }
        return {
            "rj": (f"rj-{p}.xls", self.book.saga_rj(), "saga"),
            "balanta": (f"balanta-{p}.xlsx", self.book.saga_balanta(p), "saga"),
            "jurnal_cumparari": (
                f"cumparari-{p}.xls",
                self.book.tva_journal(p, "cumparari"),
                "saga",
            ),
            "jurnal_vanzari": (f"vanzari-{p}.xls", self.book.tva_journal(p, "vanzari"), "saga"),
            "spv_register": (f"spv-{p}.xlsx", self.book.spv_register(self.invoices(), p), None),
        }


def previous(period: str) -> str:
    y, m = int(period[:4]), int(period[5:])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def month(firm: Firm, period: str, *, seed: int = 0, defect: str | None = None) -> Month:
    """A standard month for *firm*; with *defect*, that one named defect (:data:`DEFECTS`)."""
    if defect is not None and defect not in DEFECTS:
        raise KeyError(f"unknown defect {defect!r}; one of {sorted(DEFECTS)}")
    g = Gen(firm, period, seed)
    m = Month(firm, period, g, Book(firm), defect=defect)
    if defect == "late_prior_month":
        late = Gen(firm, previous(period), seed).purchase("late", partner="s3", day=27)
        m.add(late)  # booked in its own month, uploaded now

    p1 = m.add(g.purchase("p1", partner="s1", day=3))
    p2 = m.add(g.purchase("p2", partner="s2", day=6, rates=(21, 11), items=2))
    p3 = m.add(g.purchase("p3", partner="s4", day=8, items=1))  # supplier not a VAT payer
    s1 = m.add(g.sale("s1", partner="c1", day=9))
    s2 = m.add(g.sale("s2", partner="c2", day=12))

    if firm.key in ("neplatitor", "abroad"):
        for i, x in enumerate(firm.foreign, start=1):
            m.add(g.foreign_purchase(f"x{i}", partner=x.key, day=14 + i), upload=False)
            # the XML arrives by e-mail, not SPV: uploaded only by a scenario that asks
    if firm.key == "bonuri":
        _expense_report(m)
        pay = m.add(g.payroll("payroll", employees=2, day=10), upload=False)
        m.bank.append(g.salaries(pay))
    if firm.axes.get("employees") == "has" and firm.key != "bonuri":
        pay = m.add(g.payroll("payroll", employees=1, day=10), upload=False)
        m.bank.append(g.salaries(pay))

    if defect == "bank_line_two_invoices":
        m.bank.append(g.payment(p1, day=20, also=(_same_supplier(m, p1),)))
    else:
        m.bank.append(g.payment(p1, day=20))
    if defect == "partial_payment":
        m.bank.append(g.receipt(s1, amount=s1.gross // 2, day=22))
    else:
        m.bank.append(g.receipt(s1, day=22))
    m.bank.append(g.fee(day=28))
    for ln in m.bank:
        m.book.post(ln)

    if defect is not None:
        DEFECTS[defect](m, {"p1": p1, "p2": p2, "p3": p3, "s1": s1, "s2": s2})
    m.statement()
    return m


def _same_supplier(m: Month, p1: Invoice) -> Invoice:
    """A second purchase from p1's supplier, so one payment can settle both."""
    return m.add(m.gen.purchase("p1b", partner=p1.partner.key, day=4))


def _expense_report(m: Month) -> ExpenseReport:
    g = m.gen
    with_cui = g.bon("bon1", our_cui=True, merchant="s3", day=5)
    without = g.bon("bon2", our_cui=False, merchant="s3", day=7)
    xml_part = g.purchase("dec_inv", partner="s2", day=11, items=1)
    report = g.expense_report(
        "decont",
        [(with_cui, "pdf"), (without, "pdf"), (xml_part, "xml"), (g.workings("calc"), "pdf")],
    )
    for doc in (with_cui, without):
        m.add(doc, via="542")
    m.add(xml_part, upload=False)  # a part of the report; its zip is uploaded by a scenario
    m.docs["decont"] = report
    m.uploads.append(Upload("decont", "decont", report))
    return report


# ----- the named defects -----


def _missing(m: Month, d: dict[str, Invoice]) -> None:
    m.book.missing("p2")


def _no_document(m: Month, d: dict[str, Invoice]) -> None:
    m.add(m.gen.purchase("hidden", partner="s3", day=17), upload=False)


def _amount(m: Month, d: dict[str, Invoice]) -> None:
    m.book.amount_differs("s2", 100)


def _vat(m: Month, d: dict[str, Invoice]) -> None:
    m.book.vat_differs("p2", 100)


def _another_way(m: Month, d: dict[str, Invoice]) -> None:
    m.book.posted_another_way("p2")


def _duplicate(m: Month, d: dict[str, Invoice]) -> None:
    m.uploads.append(Upload("p2", "ingest", d["p2"]))


def _late(m: Month, d: dict[str, Invoice]) -> None:
    pass  # drawn and posted before the month's own documents


def _storno(m: Month, d: dict[str, Invoice]) -> None:
    m.add(m.gen.credit_note("s1_storno", d["s1"], day=25))


def _bank_only(m: Month, d: dict[str, Invoice]) -> None:
    pass  # the statement is drawn with the defect (one line, two invoices; half paid)


DEFECTS: dict[str, Callable[[Month, dict[str, Invoice]], None]] = {
    "missing_from_books": _missing,
    "in_books_no_document": _no_document,
    "amount_differs": _amount,
    "vat_differs": _vat,
    "posted_another_way": _another_way,
    "duplicate_upload": _duplicate,
    "late_prior_month": _late,
    "storno_of_acked": _storno,
    "bank_line_two_invoices": _bank_only,
    "partial_payment": _bank_only,
}


def payroll_of(m: Month) -> Payroll | None:
    pay = m.docs.get("payroll")
    return pay if isinstance(pay, Payroll) else None
