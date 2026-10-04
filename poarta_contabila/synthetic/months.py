"""A firm-month of synthetic data: what is uploaded, and the books SAGA would hold.

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
    storno_of_acked         credit notes reverse a sale and a purchase of the month
    bank_line_two_invoices  one payment settles two purchases
    partial_payment         a customer pays half of a sale
    posted_on_other_accounts  a purchase on 408 with its VAT in the cost (none of 401 / 4426)
    payables_skew           balanță: 401 closes 10.00 off the sum of its analytics
    receivables_skew        balanță: 4111 closes 10.00 off the sum of its analytics
    trade_accounts          balanță: analytics under 408 and 418 that tie
    trade_accounts_skew     … and 408 / 418 that do not
    vat_on_4428             a purchase's VAT on 4428 (wrong for a neplătitor)
    vat_on_4423             a purchase's VAT on 4423 (wrong for a neplătitor)

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
    PartFormat,
    Payroll,
    Statement,
    Workings,
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
    if firm.key == "abroad":
        for y in firm.foreign_customers:
            m.add(g.export_sale(f"xs_{y.key}", partner=y.key, day=16))
        _abroad_report(m)
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


def _abroad_report(m: Month) -> ExpenseReport:
    """A trip abroad: a foreign invoice (printed) and a RO invoice whose XML never came."""
    g = m.gen
    hotel = g.foreign_purchase("dec_abroad", partner="x2", items=1, day=13)
    taxi = g.purchase("dec_pdf", partner="s3", items=1, day=13)
    report = g.expense_report(
        "decont_abroad", [(hotel, "pdf"), (taxi, "pdf"), (g.workings("diurna"), "pdf")]
    )
    for doc in (hotel, taxi):
        m.add(doc, upload=False, via="542")
    m.docs["decont_abroad"] = report
    m.uploads.append(Upload("decont_abroad", "decont", report))
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
    m.add(m.gen.credit_note("p1_storno", d["p1"], day=26, share=50))


def _other_accounts(m: Month, d: dict[str, Invoice]) -> None:
    m.book.posted_another_way("p2").repost_party("p2", "408")


def _skew(root: str):
    return lambda m, d: m.book.skew_analytic(root, 1_000)


def _trade(skew: bool):
    def apply(m: Month, d: dict[str, Invoice]) -> None:
        m.book.open("408.00002", -30_000).open("418.00001", 45_000).open("117", -15_000)
        if skew:
            m.book.skew_analytic("408", 1_000).skew_analytic("418", -1_000)

    return apply


def _vat_on(account: str):
    return lambda m, d: m.book.move_vat("p1", account)


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
    "posted_on_other_accounts": _other_accounts,
    "payables_skew": _skew("401"),
    "receivables_skew": _skew("4111"),
    "trade_accounts": _trade(False),
    "trade_accounts_skew": _trade(True),
    "vat_on_4428": _vat_on("4428"),
    "vat_on_4423": _vat_on("4423"),
}


def payroll_of(m: Month) -> Payroll | None:
    pay = m.docs.get("payroll")
    return pay if isinstance(pay, Payroll) else None


# ----- realistic months: drawn, not designed -----


def realistic(firm: Firm, periods: list[str], *, seed: int = 0) -> Month:
    """Consecutive months of a firm drawn from *seed*, without choosing any document's path:
    a random mix of SPV purchases and sales, credit notes, invoices from abroad (XML, as the
    supplier sends them), an expense report with random parts, payroll, and a statement per
    month that pays and collects some invoices (in part, two at a time, or of the month
    before); the books hold what SAGA would, with a little noise (a document missing, one with
    no document here, one amount off). The uploads follow, month by month."""
    book = Book(firm)
    first = Gen(firm, periods[0], seed)
    m = Month(firm, periods[-1], first, book)
    unpaid: list[Invoice] = []
    for period in periods:
        g = Gen(firm, period, seed)
        rng, yy = g.rng, g.yymm
        lines: list[BankLine] = []
        inv = m.add

        suppliers = [p.key for p in firm.suppliers]
        customers = [p.key for p in firm.customers]
        buys = [
            inv(g.purchase(f"{yy}-p{i}", partner=rng.choice(suppliers)))
            for i in range(1, rng.randint(12, 18))
        ]
        sells = [
            inv(g.sale(f"{yy}-s{i}", partner=rng.choice(customers)))
            for i in range(1, rng.randint(8, 13))
        ]
        for i, of in enumerate(rng.sample(buys + sells, k=rng.randint(1, 2)), start=1):
            inv(g.credit_note(f"{yy}-c{i}", of, share=rng.choice((50, 100))))
        for i, x in enumerate(firm.foreign, start=1):
            if rng.random() < 0.8:
                inv(g.foreign_purchase(f"{yy}-x{i}", partner=x.key))
        if firm.key in ("bonuri", "abroad") or rng.random() < 0.4:
            parts: list[tuple[Any, PartFormat]] = []
            for j in range(rng.randint(2, 5)):
                kind = rng.choice(("bon", "bon", "ro_xml", "ro_pdf", "foreign", "workings"))
                if kind == "bon":
                    parts.append((g.bon(f"{yy}-b{j}", our_cui=rng.random() < 0.6), "pdf"))
                elif kind in ("ro_xml", "ro_pdf"):
                    parts.append(
                        (
                            g.purchase(f"{yy}-d{j}", partner=rng.choice(suppliers), items=1),
                            "xml" if kind == "ro_xml" else "pdf",
                        )
                    )
                elif kind == "foreign" and firm.foreign:
                    parts.append(
                        (
                            g.foreign_purchase(f"{yy}-dx{j}", partner=firm.foreign[0].key, items=1),
                            "pdf",
                        )
                    )
                else:
                    parts.append((g.workings(f"{yy}-w{j}"), "pdf"))
            report = g.expense_report(f"{yy}-decont", parts)
            for doc, _ in parts:
                if not isinstance(doc, Workings):
                    m.add(doc, upload=False, via="542")
            m.docs[report.ref] = report
            m.uploads.append(Upload(report.ref, "decont", report))
        if firm.axes.get("employees") == "has":
            pay = m.add(g.payroll(f"{yy}-payroll", employees=rng.randint(1, 4)), upload=False)
            lines.append(g.salaries(pay))

        # the statement: pays and collects some invoices of this month and the one before
        open_buys = [d for d in unpaid if d.side == "in"] + [d for d in buys if not d.foreign]
        open_sells = [d for d in unpaid if d.side == "out"] + sells
        rng.shuffle(open_buys)
        rng.shuffle(open_sells)
        paid: set[str] = set()
        for d in open_buys[: len(open_buys) * 2 // 3]:
            if d.ref in paid:
                continue
            twin = next(
                (
                    o
                    for o in open_buys
                    if o.ref not in paid and o.ref != d.ref and o.partner == d.partner
                ),
                None,
            )
            if twin is not None and rng.random() < 0.2:
                lines.append(g.payment(d, also=(twin,), day=rng.randint(10, 28)))
                paid |= {d.ref, twin.ref}
            elif rng.random() < 0.1:
                lines.append(g.payment(d, amount=d.gross // 2, day=rng.randint(10, 28)))
                paid.add(d.ref)
            else:
                lines.append(g.payment(d, day=rng.randint(10, 28)))
                paid.add(d.ref)
        for d in open_sells[: len(open_sells) // 2]:
            lines.append(g.receipt(d, day=rng.randint(10, 28)))
            paid.add(d.ref)
        lines.append(g.fee(day=28))
        unpaid = [d for d in [*buys, *sells] if d.ref not in paid]

        # the books: what SAGA holds, a little noisy
        if rng.random() < 0.7:
            book.missing(rng.choice(buys).ref)
        if rng.random() < 0.7:
            m.add(g.purchase(f"{yy}-hidden", partner=rng.choice(suppliers)), upload=False)
        if rng.random() < 0.5:
            book.amount_differs(rng.choice(sells).ref, rng.choice((100, -250, 1_000)))
        for ln in lines:
            book.post(ln)
        m.bank.extend(lines)
        bal = book.balances(period).get(firm.bank_account, {})
        opening = bal.get("open_d", 0) + bal.get("prev_d", 0)
        opening -= bal.get("open_c", 0) + bal.get("prev_c", 0)
        stmt = g.statement(f"{yy}-extras", lines, opening=opening)
        m.docs[stmt.ref] = stmt
        m.uploads.append(Upload(stmt.ref, "extras", stmt))
    return m
