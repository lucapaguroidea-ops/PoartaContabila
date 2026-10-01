"""Witness exports (A2): SAGA C and NextUp journal / trial-balance files → lines and balances.

The book of record is read, never written. Rules that keep the reading honest:

- **Account codes come from the cell's display format**, never from the stored number:
  SAGA stores analytic ``401.00010`` as the float 401.0001 with format ``0.00000``.
  A fractional account cell without a decimal format is an error.
- **Amounts are two-decimal strings**; a value that is not a whole number of cents is refused.
- **SAGA compound entries** (``%`` on one side) expand into D/C pairs; the continuation rows
  must sum to the header amount.
- Day/month total rows, blank rows and page footers are skipped; anything else that does
  not look like a journal line is an error (fail closed). A file whose header row is not
  found is refused.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

from poarta_contabila.types import Closed, FiscalDate, Money, SinkDoc, cui_key

Product = Literal["saga", "nextup"]
_CENT = Decimal("0.01")
_ACCOUNT_RE = re.compile(r"^\d{3,6}(\.\d{1,8})?$")


class ExportError(ValueError):
    """The export cannot be read as a witness; nothing from it is used."""


class SinkLine(Closed):
    product: Product
    row: int  # 1-based row in the source sheet
    seq: str | None
    date: FiscalDate
    journal: str  # SAGA "Tip" / NextUp "Jurnal"
    doc_number: str | None
    explanation: str
    partner: str | None = None
    debit: str
    credit: str
    amount: Money
    note_id: str | None = None


class BalanceRow(Closed):
    product: Product
    row: int
    account: str
    name: str
    partner_cui: str | None = None
    opening_debit: Money | None = None
    opening_credit: Money | None = None
    previous_debit: Money | None = None
    previous_credit: Money | None = None
    turnover_debit: Money
    turnover_credit: Money
    total_debit: Money | None = None
    total_credit: Money | None = None
    closing_debit: Money
    closing_credit: Money


# ----- cell helpers -----


def _money(value: Any, where: str) -> str:
    if value in (None, ""):
        return "0.00"
    try:
        d = Decimal(str(value)) if not isinstance(value, float) else Decimal(repr(value))
    except Exception as exc:
        raise ExportError(f"{where}: not an amount: {value!r}") from exc
    q = d.quantize(_CENT, rounding=ROUND_HALF_UP)
    if abs(d - q) >= Decimal("0.000001"):
        raise ExportError(f"{where}: amount {value!r} is not a whole number of cents")
    return str(q)


def _decimals_in_format(fmt: str) -> int | None:
    """Number of decimals a numeric format shows, or None if it is not a plain number format."""
    m = re.search(r"0(?:\.(0+))?(?:[^0#.,]|$)", fmt.replace("#", "").replace(",", ""))
    if not re.search(r"[0#]", fmt):
        return None
    frac = re.search(r"\.(0+)", fmt)
    return len(frac.group(1)) if frac else (0 if m else None)


def _account(value: Any, fmt: str | None, where: str) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ExportError(f"{where}: unexpected account cell {value!r}")
    decimals = _decimals_in_format(fmt or "")
    whole = float(value) == int(value)
    if decimals is None:
        if whole:
            return str(int(value))
        raise ExportError(f"{where}: account {value!r} has no display format; code is ambiguous")
    if decimals == 0:
        if not whole:
            raise ExportError(f"{where}: account {value!r} shown without decimals")
        return str(int(value))
    return f"{float(value):.{decimals}f}"


def _doc_number(value: Any, fmt: str | None) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, float | int) and not isinstance(value, bool):
        if float(value) == int(value):
            return str(int(value))
        return _account(value, fmt, "doc number")
    return str(value).strip() or None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


# ----- SAGA journal (.xls / .xlsx) -----


def _sheet_cells(path: Path) -> tuple[list[list[Any]], list[list[str | None]], Any]:
    """Values and display formats for the first sheet; dates stay raw (serials) for .xls."""
    path = Path(path)
    if path.suffix.lower() == ".xls":
        import xlrd

        wb = xlrd.open_workbook(str(path), formatting_info=True)
        sh = wb.sheet_by_index(0)
        values, formats = [], []
        for r in range(sh.nrows):
            values.append(sh.row_values(r))
            row_fmt = []
            for c in range(sh.ncols):
                xf = wb.xf_list[sh.cell_xf_index(r, c)]
                row_fmt.append(wb.format_map[xf.format_key].format_str)
            formats.append(row_fmt)
        return values, formats, wb.datemode
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    values, formats = [], []
    for row in ws.iter_rows():
        values.append([c.value for c in row])
        formats.append([c.number_format for c in row])
    return values, formats, None


def _date(value: Any, datemode: Any, where: str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return (date(1899, 12, 30) + timedelta(days=int(value))).isoformat()
    if isinstance(value, str):
        for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(value.strip(), pattern).date().isoformat()
            except ValueError:
                pass
    raise ExportError(f"{where}: not a date: {value!r}")


_FIRM_CUI_RE = re.compile(r"c\.\s*f\.\s*:?\s*((?:RO)?\s*\d{2,10})\b", re.IGNORECASE)


def read_firm_cui(path: str | Path) -> str | None:
    """The firm's CUI from a SAGA export header (``... c.f. RO123 r.c. ...``), or None."""
    values, _, _ = _sheet_cells(Path(path))
    for row in values[:6]:
        for value in row:
            m = _FIRM_CUI_RE.search(_text(value))
            if m:
                return cui_key(m.group(1))
    return None


def _find_header(values: list[list[Any]], labels: tuple[str, ...], where: str) -> int:
    for i, row in enumerate(values):
        texts = {_text(v) for v in row}
        if all(label in texts for label in labels):
            return i
    raise ExportError(f"{where}: header row with {labels} not found")


_SAGA_RJ_LABELS = ("Data", "Explicatie", "Nr. doc", "debitor", "creditor", "Debit", "Credit", "Tip")


def read_saga_rj(path: str | Path) -> list[SinkLine]:
    """SAGA C *Registru jurnal* export → one SinkLine per D/C pair."""
    values, formats, datemode = _sheet_cells(Path(path))
    h = _find_header(values, _SAGA_RJ_LABELS, Path(path).name)
    head = [_text(v) for v in values[h]]
    col = {label: head.index(label) for label in _SAGA_RJ_LABELS}
    seq_col = head.index("crt.") if "crt." in head else 0
    lines: list[SinkLine] = []
    group: dict[str, Any] | None = None

    def close_group(where: str) -> None:
        nonlocal group
        if group is not None and Decimal(group["sum"]) != Decimal(group["amount"]):
            raise ExportError(
                f"{where}: compound entry {group['seq']} continuations sum to {group['sum']},"
                f" header says {group['amount']}"
            )
        group = None

    for i in range(h + 1, len(values)):
        row = values[i] + [""] * (len(head) - len(values[i]))
        fmt = formats[i] + [None] * (len(head) - len(formats[i]))
        where = f"{Path(path).name} row {i + 1}"
        cells = [_text(v) for v in row]
        if not any(cells):
            continue
        if cells[0].startswith("Pagina") or all(label in cells for label in ("Data", "Tip")):
            continue
        seq = cells[seq_col]
        debit_cell = cells[col["debitor"]]
        if not seq and debit_cell.startswith("Total"):
            close_group(where)
            continue
        amount_d = _money(row[col["Debit"]], where)
        amount_c = _money(row[col["Credit"]], where)
        if amount_d != amount_c:
            raise ExportError(f"{where}: Debit {amount_d} != Credit {amount_c}")
        debit = _account(row[col["debitor"]], fmt[col["debitor"]], where)
        credit = _account(row[col["creditor"]], fmt[col["creditor"]], where)
        base = {
            "product": "saga",
            "row": i + 1,
            "date": _date(row[col["Data"]], datemode, where),
            "journal": cells[col["Tip"]],
            "doc_number": _doc_number(row[col["Nr. doc"]], fmt[col["Nr. doc"]]),
            "explanation": cells[col["Explicatie"]],
            "amount": amount_d,
        }
        if seq:
            close_group(where)
            seq = str(int(float(seq))) if re.fullmatch(r"\d+(\.0+)?", seq) else seq
            if "%" in (debit, credit):
                if debit == credit:
                    raise ExportError(f"{where}: '%' on both sides")
                group = {
                    "seq": seq,
                    "side": "credit" if credit == "%" else "debit",
                    "fixed": debit if credit == "%" else credit,
                    "amount": amount_d,
                    "sum": "0.00",
                    "doc_number": base["doc_number"],
                }
                continue
            _check_accounts(debit, credit, where)
            lines.append(SinkLine(seq=seq, debit=debit, credit=credit, **base))
            continue
        # continuation of a compound entry
        if group is None:
            raise ExportError(f"{where}: line without Nr. crt outside a compound entry")
        if group["side"] == "credit":
            if debit or not credit:
                raise ExportError(f"{where}: compound continuation must fill the credit side")
            debit, credit = group["fixed"], credit
        else:
            if credit or not debit:
                raise ExportError(f"{where}: compound continuation must fill the debit side")
            credit = group["fixed"]
        _check_accounts(debit, credit, where)
        group["sum"] = str(Decimal(group["sum"]) + Decimal(amount_d))
        base["doc_number"] = base["doc_number"] or group["doc_number"]
        lines.append(SinkLine(seq=group["seq"], debit=debit, credit=credit, **base))
    close_group(f"{Path(path).name} end")
    return lines


def _check_accounts(debit: str, credit: str, where: str) -> None:
    for acct in (debit, credit):
        if not acct:
            raise ExportError(f"{where}: missing account")


# ----- SAGA balance -----

_SAGA_GROUPS = {
    "Solduri initiale an": "opening",
    "Sume precedente": "previous",
    "Rulaje perioada": "turnover",
    "Sume totale": "total",
    "Solduri finale": "closing",
}


def read_saga_balanta(path: str | Path) -> list[BalanceRow]:
    """SAGA C *Balanță de verificare* (5 column pairs) → BalanceRow per printed row."""
    values, formats, _ = _sheet_cells(Path(path))
    name = Path(path).name
    h = _find_header(values, ("Cont", "Denumirea contului"), name)
    groups_row = next(
        (r for r in range(max(0, h - 3), h) if "Solduri finale" in {_text(v) for v in values[r]}),
        None,
    )
    if groups_row is None:
        raise ExportError(f"{name}: balance column groups not found above the header")
    group_col = {
        _SAGA_GROUPS[_text(v)]: c
        for c, v in enumerate(values[groups_row])
        if _text(v) in _SAGA_GROUPS
    }
    if set(group_col) != set(_SAGA_GROUPS.values()):
        raise ExportError(f"{name}: expected column groups {sorted(_SAGA_GROUPS)}")
    first = h + 1
    if "Debitoare" in {_text(v) for v in values[first]}:
        first += 1
    rows: list[BalanceRow] = []
    for i in range(first, len(values)):
        row = values[i]
        cells = [_text(v) for v in row]
        if not any(cells):
            continue
        if cells[0].startswith("Pagina") or cells[0].startswith("Total"):
            continue
        where = f"{name} row {i + 1}"
        account = _account(row[0], formats[i][0], where)
        if not _ACCOUNT_RE.match(account):
            raise ExportError(f"{where}: not an account code: {account!r}")
        amounts = {
            f"{key}_{side}": _money(row[c + k] if c + k < len(row) else None, where)
            for key, c in group_col.items()
            for k, side in ((0, "debit"), (1, "credit"))
        }
        rows.append(
            BalanceRow(product="saga", row=i + 1, account=account, name=cells[1], **amounts)
        )
    return rows


# ----- NextUp -----

_NEXTUP_RJ = (
    "Nr. crt",
    "Jurnal",
    "Nr. document",
    "Data",
    "Partener",
    "Explicatii",
    "Cont debitor",
    "Cont auxiliar debitor",
    "Cont creditor",
    "Cont auxiliar creditor",
    "Suma",
    "Nr. inregistrare",
)


def read_nextup_rj(path: str | Path) -> list[SinkLine]:
    """NextUp *Registru jurnal* export → SinkLines (one per row)."""
    values, _, _ = _sheet_cells(Path(path))
    name = Path(path).name
    h = _find_header(values, _NEXTUP_RJ, name)
    head = [_text(v) for v in values[h]]
    col = {label: head.index(label) for label in _NEXTUP_RJ}
    lines = []
    for i in range(h + 1, len(values)):
        row = values[i]
        cells = [_text(v) for v in row]
        if not any(cells):
            continue
        where = f"{name} row {i + 1}"
        if not cells[col["Nr. crt"]]:
            continue  # trailing total row
        if cells[col["Cont auxiliar debitor"]] or cells[col["Cont auxiliar creditor"]]:
            raise ExportError(f"{where}: auxiliary accounts are not supported yet")
        debit, credit = cells[col["Cont debitor"]], cells[col["Cont creditor"]]
        _check_accounts(debit, credit, where)
        lines.append(
            SinkLine(
                product="nextup",
                row=i + 1,
                seq=cells[col["Nr. crt"]],
                date=_date(row[col["Data"]], None, where),
                journal=cells[col["Jurnal"]],
                doc_number=_doc_number(row[col["Nr. document"]], None),
                explanation=cells[col["Explicatii"]],
                partner=cells[col["Partener"]] or None,
                debit=debit,
                credit=credit,
                amount=_money(row[col["Suma"]], where),
                note_id=cells[col["Nr. inregistrare"]] or None,
            )
        )
    return lines


def read_nextup_balanta(path: str | Path) -> list[BalanceRow]:
    """NextUp *Balanță* export → BalanceRow per account, with the partner CIF when it is a CUI."""
    values, _, _ = _sheet_cells(Path(path))
    name = Path(path).name
    h = _find_header(values, ("Cont", "Titlu cont", "CIF partener", "Sold final"), name)
    head = [_text(v) for v in values[h]]
    groups = {
        "Rulaj precedent": "previous",
        "Rulaj curent": "turnover",
        "Total": "total",
        "Sold final": "closing",
    }
    group_col = {key: head.index(label) for label, key in groups.items()}
    first = h + 2 if "Debit" in {_text(v) for v in values[h + 1]} else h + 1
    rows = []
    for i in range(first, len(values)):
        row = values[i]
        cells = [_text(v) for v in row]
        if not any(cells):
            continue
        if not cells[0]:
            continue  # trailing total row
        where = f"{name} row {i + 1}"
        amounts = {
            f"{key}_{side}": _money(row[c + k], where)
            for key, c in group_col.items()
            for k, side in ((0, "debit"), (1, "credit"))
        }
        rows.append(
            BalanceRow(
                product="nextup",
                row=i + 1,
                account=cells[0],
                name=cells[head.index("Titlu cont")],
                partner_cui=cui_key(cells[head.index("CIF partener")]),
                **amounts,
            )
        )
    return rows


# ----- eye -----

_INVOICE_JOURNALS = {
    "saga": {"Intrari": "intrare", "Iesiri": "iesire"},
    "nextup": {"JC": "intrare", "JV": "iesire"},
}
_BANK_JOURNALS = {"saga": ("Banca",), "nextup": ("JB",)}
_BANK_ROOTS = ("5121",)
_SUPPLIER_ROOTS = ("401", "404", "408")
_CUSTOMER_ROOTS = ("4111", "411", "418")


def _under(account: str, roots: tuple[str, ...]) -> bool:
    return any(
        account == r or (account.startswith(r) and not account[len(r)].isdigit()) for r in roots
    )


def synthetic(account: str) -> str:
    """The synthetic account of an analytic code: ``401.00010`` / ``401_X`` / ``401XV`` → 401."""
    m = re.match(r"\d+", account)
    return m.group(0) if m else account


class ExportEye:
    """SagaEye implementation over parsed exports (v1 witness, A2)."""

    def __init__(
        self,
        *,
        product: Product,
        lines: list[SinkLine],
        balance: list[BalanceRow] | None = None,
        partner_cuis: dict[str, str] | None = None,
        cui: str | None = None,
        periods: Iterable[str] | None = None,
    ) -> None:
        """``cui``: the firm the export belongs to (SAGA: :func:`read_firm_cui`). Without it
        the eye covers nothing. ``periods``: months the export was taken for; by default
        the months that have journal lines."""
        self.product = product
        self.lines = lines
        self.balance = balance or []
        cuis = {r.account: r.partner_cui for r in self.balance if r.partner_cui}
        cuis.update(partner_cuis or {})
        self.partner_cuis = cuis
        self.cui = cui
        self.periods = frozenset(periods if periods is not None else (ln.date[:7] for ln in lines))

    def covers(self, cui: str, period: str) -> bool:
        return self.cui is not None and self.cui == cui and period in self.periods

    def documents(self, cui: str, period: str) -> list[SinkDoc]:
        journals = _INVOICE_JOURNALS[self.product]
        groups: dict[tuple[str, str, str], list[SinkLine]] = {}
        for line in self.lines:
            if line.journal in journals and line.date.startswith(period):
                key = (line.journal, line.doc_number or "", line.date)
                groups.setdefault(key, []).append(line)
        docs = []
        for (journal, number, day), lines in groups.items():
            doc_class = journals[journal]
            if doc_class == "intrare":
                party = [ln for ln in lines if _under(ln.credit, _SUPPLIER_ROOTS)]
                gross = sum((Decimal(ln.amount) for ln in party), Decimal(0))
                vat = sum(
                    (Decimal(ln.amount) for ln in lines if ln.debit in ("4426", "4428")),
                    Decimal(0),
                )
                analytic = party[0].credit if party else None
            else:
                party = [ln for ln in lines if _under(ln.debit, _CUSTOMER_ROOTS)]
                gross = sum((Decimal(ln.amount) for ln in party), Decimal(0))
                vat = sum(
                    (Decimal(ln.amount) for ln in lines if ln.credit in ("4427", "4428")),
                    Decimal(0),
                )
                analytic = party[0].debit if party else None
            docs.append(
                SinkDoc(
                    saga_key=f"{self.product}:{journal}:{number}:{day}",
                    doc_class=doc_class,
                    number=number,
                    date=day,
                    partner_cui=self.partner_cuis.get(analytic or ""),
                    gross=str(gross.quantize(_CENT)),
                    net=str((gross - vat).quantize(_CENT)),
                    vat=str(vat.quantize(_CENT)),
                    validated=True,
                    analytic=analytic,
                )
            )
        docs.extend(self._bank_documents(period))
        return sorted(docs, key=lambda d: (d.date, d.saga_key))

    def _bank_documents(self, period: str) -> list[SinkDoc]:
        """Bank-journal entries as documents: 5121 debit → încasare, 5121 credit → plată."""
        groups: dict[tuple[str, str, str, str], list[SinkLine]] = {}
        for ln in self.lines:
            if ln.journal not in _BANK_JOURNALS[self.product] or not ln.date.startswith(period):
                continue
            for side, account in (("incasare", ln.debit), ("plata", ln.credit)):
                if _under(account, _BANK_ROOTS):
                    key = (ln.journal, ln.doc_number or "", ln.date, side)
                    groups.setdefault(key, []).append(ln)
        out = []
        for (journal, number, day, side), lines in groups.items():
            amount = sum((Decimal(ln.amount) for ln in lines), Decimal(0)).quantize(_CENT)
            account = lines[0].debit if side == "incasare" else lines[0].credit
            out.append(
                SinkDoc(
                    saga_key=f"{self.product}:{journal}:{number}:{day}:{side}",
                    doc_class=side,
                    number=number,
                    date=day,
                    partner_cui=None,
                    gross=str(amount),
                    net=str(amount),
                    vat="0.00",
                    validated=True,
                    analytic=account,
                )
            )
        return out

    def journal_lines(self, cui: str, period: str) -> list[SinkLine]:
        return [ln for ln in self.lines if ln.date.startswith(period)]

    def turnover(self, cui: str, period: str) -> dict[str, dict[str, str]]:
        """Period turnover per synthetic account: from the journal lines when there are
        any, else from the balance's period columns."""
        sums: dict[str, list[Decimal]] = {}
        if self.lines:
            for ln in self.lines:
                if not ln.date.startswith(period):
                    continue
                for side, account in ((0, ln.debit), (1, ln.credit)):
                    if account:
                        sums.setdefault(synthetic(account), [Decimal(0), Decimal(0)])[side] += (
                            Decimal(ln.amount)
                        )
        else:
            for r in self.balance:
                if r.account.isdigit():
                    pair = sums.setdefault(r.account, [Decimal(0), Decimal(0)])
                    pair[0] += Decimal(r.turnover_debit)
                    pair[1] += Decimal(r.turnover_credit)
        return {
            k: {"debit": str(v[0].quantize(_CENT)), "credit": str(v[1].quantize(_CENT))}
            for k, v in sums.items()
        }

    def solduri(self, cui: str, period: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in self.balance:
            out.setdefault(r.account, {"debit": r.closing_debit, "credit": r.closing_credit})
        return out

    def analytic(self, cui: str, period: str, root: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for r in self.balance:
            if r.account != root and _under(r.account, (root,)):
                out.setdefault(r.account, {"debit": r.closing_debit, "credit": r.closing_credit})
        return out
