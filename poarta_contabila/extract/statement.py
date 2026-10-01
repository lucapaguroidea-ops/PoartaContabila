"""Bank statements (WP-13): the extract contract's tables → one validated statement.

Portfolio statements arrive as PDF (harvest C-10), so the reading is done by the extract
backend (``document_ai``; EXTRACT.md), which hands over ``normalized/tables.json``:
``[{headers, rows}]`` as strings. This module turns those tables into movement lines,
deterministically, and checks them before anything is emitted (fail closed):

- the movement table is found by label (date + debit + credit columns);
- every amount is a whole number of cents, and a line moves on exactly one side;
- ``opening − Σ debits + Σ credits = closing`` to the cent;
- the account holder's CUI is the tenant's (identity before any line Job);
- RON only in v1 (a foreign-currency account is another witness: CO.DiT ``fx_currencies``).

The statement is a pack, never a Job: each line becomes its own Job (ARTICOLE_EXTRAS_GRAIN).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

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
    SourceRef,
    Totals,
    cui_key,
)

_CENT = Decimal("0.01")
_DATE = ("data", "data tranzactiei", "data operatiunii", "data operatiei", "data valutei")
_DESC = ("descriere", "detalii", "detalii tranzactie", "explicatii", "descrierea tranzactiei")
_DEBIT = ("debit", "suma debit", "debit (ron)", "plati")
_CREDIT = ("credit", "suma credit", "credit (ron)", "incasari")
_REF = ("referinta", "nr. referinta", "ref")


class StatementError(ValueError):
    """The statement does not read or does not add up. No line is emitted."""


class StatementLine(Closed):
    seq: int = Field(ge=1)
    date: FiscalDate
    side: Literal["debit", "credit"]  # debit = money out (plată), credit = money in (încasare)
    amount: Money
    description: str
    reference: str | None = None


class StatementMeta(Closed):
    """What the backend read from the statement header."""

    iban: str = Field(min_length=10)
    holder_cui: str
    currency: str = "RON"
    opening: Money
    closing: Money
    statement_date: FiscalDate


class Statement(Closed):
    statement_id: str
    meta: StatementMeta
    holder_cui: Cui
    lines: list[StatementLine]


def _plain(text: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).lower().split())


def _amount(raw: Any, where: str) -> Decimal:
    text = str(raw or "").strip().replace(" ", "").replace(" ", "")
    if text in ("", "-"):
        return Decimal(0)
    if "," in text and "." in text:  # 1.234,56 or 1,234.56: the last separator is decimal
        text = (
            text.replace(".", "").replace(",", ".")
            if text.rfind(",") > text.rfind(".")
            else (text.replace(",", ""))
        )
    elif "," in text:
        text = text.replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise StatementError(f"{where}: not an amount: {raw!r}") from exc
    if value.quantize(_CENT) != value:
        raise StatementError(f"{where}: {raw!r} is not a whole number of cents")
    return abs(value)


def _date(raw: Any, where: str) -> str:
    text = str(raw or "").strip()
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    raise StatementError(f"{where}: not a date: {raw!r}")


def _col(headers: list[str], names: tuple[str, ...]) -> int | None:
    norm = [_plain(h) for h in headers]
    for name in names:
        if name in norm:
            return norm.index(name)
    return None


def parse_statement(
    tables: list[dict[str, Any]], meta: StatementMeta, tenant_cui: str
) -> Statement:
    """Lines from the extract tables, checked against the header totals and the tenant."""
    holder = cui_key(meta.holder_cui)
    if holder is None:
        raise StatementError("the statement names no valid account-holder CUI")
    if holder != tenant_cui:
        raise StatementError(f"the account holder is {holder}, not the tenant {tenant_cui}")
    if meta.currency.upper() != "RON":
        raise StatementError(f"{meta.currency} account: v1 reads RON statements only")

    lines: list[StatementLine] = []
    found = False
    for t, table in enumerate(tables):
        headers = [str(h) for h in table.get("headers") or []]
        cols = {
            k: _col(headers, v)
            for k, v in (("date", _DATE), ("desc", _DESC), ("debit", _DEBIT), ("credit", _CREDIT))
        }
        if None in (cols["date"], cols["debit"], cols["credit"]):
            continue
        found = True
        ref = _col(headers, _REF)
        for r, row in enumerate(table.get("rows") or [], start=1):
            where = f"table {t + 1} row {r}"
            cells = [str(c) if c is not None else "" for c in row] + [""] * len(headers)
            if not cells[cols["date"]].strip():
                continue  # carried description line or a subtotal without a date
            if re.match(
                r"^\s*(total|sold)", _plain(cells[cols["desc"]] if cols["desc"] is not None else "")
            ):
                continue
            debit = _amount(cells[cols["debit"]], where)
            credit = _amount(cells[cols["credit"]], where)
            if bool(debit) == bool(credit):
                raise StatementError(f"{where}: a line moves on exactly one side")
            lines.append(
                StatementLine(
                    seq=len(lines) + 1,
                    date=_date(cells[cols["date"]], where),
                    side="debit" if debit else "credit",
                    amount=str((debit or credit).quantize(_CENT)),
                    description=(cells[cols["desc"]] if cols["desc"] is not None else "").strip(),
                    reference=(cells[ref].strip() or None) if ref is not None else None,
                )
            )
    if not found:
        raise StatementError("no movement table (date, debit, credit) in the extract")
    if not lines:
        raise StatementError("the statement has no movements")
    out = sum((Decimal(ln.amount) for ln in lines if ln.side == "debit"), Decimal(0))
    into = sum((Decimal(ln.amount) for ln in lines if ln.side == "credit"), Decimal(0))
    if Decimal(meta.opening) - out + into != Decimal(meta.closing):
        raise StatementError(
            f"opening {meta.opening} − debits {out} + credits {into} ≠ closing {meta.closing}"
        )
    body = json.dumps(
        {"meta": meta.model_dump(), "lines": [ln.model_dump() for ln in lines]}, sort_keys=True
    )
    return Statement(
        statement_id=hashlib.sha256(body.encode()).hexdigest()[:32],
        meta=meta,
        holder_cui=holder,
        lines=lines,
    )


def line_source_hash(statement_id: str, seq: int) -> str:
    """The Job key of one movement line (ARTICOLE_EXTRAS_GRAIN ``job_key``)."""
    return hashlib.sha256(f"{statement_id}:{seq}".encode()).hexdigest()


def statement_line_document(
    statement: Statement, line: StatementLine, *, job: JobRecord, bucket_key: str, source_hash: str
) -> CanonicalDocument:
    """One movement line as the document its Job carries: the bank side only.

    The counterparty is not read from free text: it stays unknown until a person or a
    map names it (no partner CUI is guessed from a description).
    """
    doc_class = "plata" if line.side == "debit" else "incasare"
    amount = line.amount
    return CanonicalDocument(
        job_id=job.job_id,
        tenant=job.tenant,
        period=line.date[:7],
        doc_class=doc_class,
        number=f"EXT-{statement.statement_id[:8]}-{line.seq}",
        date=line.date,
        partner=PartnerRef(cui=None, name=line.description or "—", role="unknown"),
        totals=Totals(net=amount, vat="0.00", gross=amount),
        lines=[
            Line(
                desc=line.description or doc_class,
                net=amount,
                vat_rate="0",
                vat="0.00",
                gross=amount,
            )
        ],
        source=SourceRef(
            kind="pdf",
            bucket_key=bucket_key,
            content_type="application/pdf",
            source_hash=source_hash,
        ),
        maps={"iban": statement.meta.iban, "statement_id": statement.statement_id},
    )
