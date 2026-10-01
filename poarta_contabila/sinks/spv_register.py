"""SPV invoice register (harvest C-F12): the second PRE witness, read only.

One row per invoice and VAT rate::

    Companie | Trimestru | Data facturii | Numar factura | Numele furnizorului |
    Suma net per % de TVA | Cota TVA | TVA | Gross | Status | Obs re status | Ordine

``Status`` goes from "De înregistrat" to "Înregistrat în SAGA". Checks (fail closed):
net + VAT = gross on every row; net × rate = VAT to the cent; one company in scope;
the rows of one invoice share its date and status; any other status is refused.
"""

from __future__ import annotations

import csv
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

from poarta_contabila.sinks.exports import (
    ExportError,
    _date,
    _doc_number,
    _find_header,
    _money,
    _sheet_cells,
    _text,
)
from poarta_contabila.types import Closed, FiscalDate, Money, Rate

COLUMNS = (
    "Companie",
    "Trimestru",
    "Data facturii",
    "Numar factura",
    "Numele furnizorului",
    "Suma net per % de TVA",
    "Cota TVA",
    "TVA",
    "Gross",
    "Status",
    "Obs re status",
    "Ordine",
)
_STATUS = {"de inregistrat": "pending", "inregistrat in saga": "posted"}
_CENT = Decimal("0.01")


class RegisterRow(Closed):
    row: int
    company: str
    quarter: str
    date: FiscalDate
    number: str
    supplier: str
    net: Money
    rate: Rate
    vat: Money
    gross: Money
    status: Literal["pending", "posted"]
    note: str = ""
    order: str = ""


class RegisterInvoice(Closed):
    """One invoice of the register: its rows added up."""

    ref: str
    number: str
    date: FiscalDate
    supplier: str
    net: Money
    vat: Money
    gross: Money
    posted: bool


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).lower().split())


def _rate(value: Any, fmt: str | None, where: str) -> str:
    if isinstance(value, str):
        value = value.strip().rstrip("%").strip().replace(",", ".")
    try:
        d = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value))
    except Exception as exc:
        raise ExportError(f"{where}: not a VAT rate: {value!r}") from exc
    if not isinstance(value, str) and ("%" in (fmt or "") or Decimal(0) < d < 1):
        d *= 100
    if d < 0:
        raise ExportError(f"{where}: negative VAT rate")
    return format(d.normalize(), "f")


def _cells(path: Path) -> tuple[list[list[Any]], list[list[str | None]], Any]:
    if path.suffix.lower() == ".csv":
        text = path.read_text(encoding="utf-8-sig")
        dialect = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t")
        rows = [list(r) for r in csv.reader(text.splitlines(), dialect)]
        return rows, [[None] * len(r) for r in rows], None
    return _sheet_cells(path)


def read_spv_register(path: str | Path) -> list[RegisterRow]:
    """Read and check the register (``.xlsx`` or ``.csv``). Raises :class:`ExportError`."""
    path = Path(path)
    values, formats, datemode = _cells(path)
    head_at = _find_header(values, COLUMNS[:10], path.name)
    head = [_text(v) for v in values[head_at]]
    col = {name: head.index(name) for name in COLUMNS if name in head}
    rows: list[RegisterRow] = []
    for r in range(head_at + 1, len(values)):
        cells = values[r] + [None] * (len(head) - len(values[r]))
        where = f"{path.name} row {r + 1}"
        if all(_text(cells[col[c]]) == "" for c in ("Numar factura", "Data facturii", "Gross")):
            continue  # blank or filler row
        status = _STATUS.get(_plain(_text(cells[col["Status"]])))
        if status is None:
            raise ExportError(f"{where}: unknown status {_text(cells[col['Status']])!r}")
        number = _doc_number(cells[col["Numar factura"]], formats[r][col["Numar factura"]])
        if not number:
            raise ExportError(f"{where}: no invoice number")
        net = _money(cells[col["Suma net per % de TVA"]], where)
        vat = _money(cells[col["TVA"]], where)
        gross = _money(cells[col["Gross"]], where)
        rate = _rate(cells[col["Cota TVA"]], formats[r][col["Cota TVA"]], where)
        if Decimal(net) + Decimal(vat) != Decimal(gross):
            raise ExportError(f"{where}: net {net} + VAT {vat} ≠ gross {gross}")
        expected = (Decimal(net) * Decimal(rate) / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
        if abs(expected - Decimal(vat)) > _CENT:
            raise ExportError(f"{where}: VAT {vat} is not {rate}% of {net}")
        rows.append(
            RegisterRow(
                row=r + 1,
                company=_text(cells[col["Companie"]]),
                quarter=_text(cells[col["Trimestru"]]),
                date=_date(cells[col["Data facturii"]], datemode, where),
                number=number,
                supplier=_text(cells[col["Numele furnizorului"]]),
                net=net,
                rate=rate,
                vat=vat,
                gross=gross,
                status=status,
                note=_text(cells[col["Obs re status"]]) if "Obs re status" in col else "",
                order=_text(cells[col["Ordine"]]) if "Ordine" in col else "",
            )
        )
    companies = {_plain(r.company) for r in rows}
    if len(companies) > 1:
        raise ExportError(f"{path.name}: more than one company in the register")
    register_invoices(rows)  # rows of one invoice must agree
    return rows


def register_invoices(rows: list[RegisterRow]) -> list[RegisterInvoice]:
    """Group rows by (supplier, number): one invoice per group, with one date and status."""
    groups: dict[tuple[str, str], list[RegisterRow]] = {}
    for r in rows:
        groups.setdefault((_plain(r.supplier), r.number), []).append(r)
    out = []
    for (_, number), group in groups.items():
        if len({r.date for r in group}) > 1 or len({r.status for r in group}) > 1:
            where = ", ".join(str(r.row) for r in group)
            raise ExportError(f"register rows {where}: invoice {number} has mixed dates/statuses")
        out.append(
            RegisterInvoice(
                ref="register:" + ",".join(str(r.row) for r in group),
                number=number,
                date=group[0].date,
                supplier=group[0].supplier,
                net=str(sum((Decimal(r.net) for r in group), Decimal(0))),
                vat=str(sum((Decimal(r.vat) for r in group), Decimal(0))),
                gross=str(sum((Decimal(r.gross) for r in group), Decimal(0))),
                posted=group[0].status == "posted",
            )
        )
    return sorted(out, key=lambda i: (i.date, i.ref))
