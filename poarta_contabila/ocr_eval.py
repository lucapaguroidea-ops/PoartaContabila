"""WP-37: the reading evaluation — how well a model reads statements whose answers are known.

Six invented statements (``cases()``), each a real PDF built here with its known answer. They
vary what bank statements vary: column labels, column order, wrapped descriptions, total rows,
thousands separators, two pages, a dense table of similar amounts. A case is read by the
server's Gemini reader (``POST /ocr-eval/{cui}``: synthetic tenants only, ``MODEL_CALLS=live``)
and scored:

- ``read``: the model answered in the card's shape;
- ``identity`` / ``iban``: the holder CUI and the IBAN as printed;
- ``header_fields``: how many of the six header fields match (amounts and dates normalized);
- ``ties``: ``parse_statement`` accepts the reading (every line ties opening → closing);
- ``lines_exact``: lines read with the right date, side and amount, in order, out of the
  known count.

Nothing is minted or stored except the model-call records. ``--model`` reads with another
Google AI Studio model for comparison (e.g. a Pro model on the hard cases); production keeps
the catalog's one pinned model (00_LAW §3 invariant 5).

    OPERATOR_TOKEN=… uv run python -m poarta_contabila.ocr_eval --base-url https://…
    OPERATOR_TOKEN=… uv run python -m poarta_contabila.ocr_eval --base-url https://… \\
        --model gemini-…-pro --case two_pages
    uv run python -m poarta_contabila.ocr_eval --write-pdfs ./eval-pdfs   # look at them
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from poarta_contabila.extract.statement import (
    _CREDIT,
    _DATE,
    _DEBIT,
    _DESC,
    StatementError,
    StatementMeta,
    _amount,
    _col,
    _date,
    _plain,
    parse_statement,
)
from poarta_contabila.synthetic_docs import text_pdf
from poarta_contabila.types import Closed, cui_key

CUI = "1000009"  # the smoke run's invented firm
IBAN = "RO49AAAA1B31007593840000"  # the textbook example IBAN
PARTNERS = ["CLIENT TEST SRL", "FURNIZOR TEST SRL", "ALFA SERV SRL", "BETA COM SA", "GAMA IT SRL"]


@dataclass(frozen=True)
class Movement:
    date: str  # ISO
    desc: str
    ref: str
    side: str  # debit | credit
    amount: Decimal


@dataclass(frozen=True)
class EvalCase:
    name: str
    about: str
    pages: list[list[str]]
    meta: dict[str, str]  # what a person types for the header
    movements: list[Movement]
    answer: dict[str, Any]  # what a perfect reading returns: header as printed, page tables

    def pdf(self) -> bytes:
        return text_pdf(self.pages)


class CaseScore(Closed):
    case: str
    model: str
    read: bool
    error: str | None = None
    identity: bool = False
    iban: bool = False
    header_fields: int = 0
    ties: bool = False
    lines_expected: int
    lines_exact: int = 0
    seconds: float = 0.0


# ----- the cases -----


def _ro(amount: Decimal) -> str:
    """1234.5 → 1.234,50, as Romanian statements print it."""
    whole, cents = f"{amount:.2f}".split(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return ".".join(groups) + "," + cents


def _dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}.{m}.{y}"


def _movements(seed: str, n: int, *, low: int, high: int, same_day: bool = False) -> list[Movement]:
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        day = 3 + (i // 3 if same_day else i * 27 // max(n, 1))
        side = "credit" if rnd.random() < 0.45 else "debit"
        partner = PARTNERS[rnd.randrange(len(PARTNERS))]
        number = f"F{rnd.randrange(100, 999)}"
        verb = "Incasare" if side == "credit" else "Plata"
        cents = rnd.randrange(low * 100, high * 100)
        out.append(
            Movement(
                date=f"2026-09-{min(day, 29):02d}",
                desc=f"{verb} {partner} fact {number}",
                ref=f"OP-{rnd.randrange(1000, 9999)}",
                side=side,
                amount=Decimal(cents) / 100,
            )
        )
    return out


def _case(
    name: str,
    about: str,
    movements: list[Movement],
    *,
    columns: list[tuple[str, str, int]],  # (label, field, width)
    opening: Decimal,
    per_page: int = 40,
    wrap: bool = False,
    totals: bool = True,
) -> EvalCase:
    debits = sum((m.amount for m in movements if m.side == "debit"), Decimal(0))
    credits = sum((m.amount for m in movements if m.side == "credit"), Decimal(0))
    closing = opening - debits + credits
    if closing < 0:  # the evaluation reads balances, not overdrafts
        raise ValueError(f"case {name}: the closing balance {closing} is below zero")

    def cell(m: Movement | None, field: str, text: str = "") -> str:
        if m is None:
            return text
        return {
            "date": _dmy(m.date),
            "desc": m.desc,
            "ref": m.ref,
            "debit": _ro(m.amount) if m.side == "debit" else "",
            "credit": _ro(m.amount) if m.side == "credit" else "",
        }[field]

    def row(values: list[str]) -> str:
        return "  ".join(v.ljust(w)[:w] for v, (_, _, w) in zip(values, columns, strict=True))

    labels = [label for label, _, _ in columns]
    head = row(labels)
    grid: list[list[str]] = []  # the cells of every printed body line
    for i, m in enumerate(movements):
        grid.append([cell(m, f) for _, f, _ in columns])
        if wrap and i % 3 == 0:  # a wrapped description: a line with no date
            grid.append([("ref. client " + m.ref) if f == "desc" else "" for _, f, _ in columns])
    if totals:
        grid.append(
            [
                "Total rulaje"
                if f == "desc"
                else (_ro(debits) if f == "debit" else _ro(credits) if f == "credit" else "")
                for _, f, _ in columns
            ]
        )
    body = [row(cells) for cells in grid]
    top = [
        "BANCA TEST SA - EXTRAS DE CONT",
        f"Titular: FIRMA TEST SRL   CUI: RO{CUI}",
        "IBAN: RO49 AAAA 1B31 0075 9384 0000   Moneda: RON",
        "Data extras: 30.09.2026",
        f"Sold initial: {_ro(opening)}",
        "",
    ]
    chunks = [body[i : i + per_page] for i in range(0, len(body), per_page)] or [[]]
    cell_chunks = [grid[i : i + per_page] for i in range(0, len(grid), per_page)] or [[]]
    pages = []
    for k, chunk in enumerate(chunks):
        lines = (top if k == 0 else [f"BANCA TEST SA - pagina {k + 1} din {len(chunks)}", ""]) + [
            head,
            *chunk,
        ]
        if k == len(chunks) - 1:
            lines += ["", f"Sold final: {_ro(closing)}"]
        pages.append(lines)
    meta = {
        "iban": IBAN,
        "holder_cui": f"RO{CUI}",
        "currency": "RON",
        "opening": f"{opening:.2f}",
        "closing": f"{closing:.2f}",
        "statement_date": "2026-09-30",
    }
    answer = {
        "header": {
            "iban": "RO49 AAAA 1B31 0075 9384 0000",
            "holder_cui": f"RO{CUI}",
            "currency": "RON",
            "opening": _ro(opening),
            "closing": _ro(closing),
            "statement_date": "30.09.2026",
        },
        "tables": [{"headers": labels, "rows": rows} for rows in cell_chunks],
    }
    return EvalCase(name, about, pages, meta, movements, answer)


STANDARD = [
    ("Data", "date", 10),
    ("Descriere", "desc", 36),
    ("Referinta", "ref", 9),
    ("Debit", "debit", 11),
    ("Credit", "credit", 11),
]


def cases() -> list[EvalCase]:
    """The evaluation set: deterministic, so every run and model reads the same PDFs."""
    return [
        _case(
            "simple",
            "two movements, standard labels",
            _movements("simple", 2, low=100, high=2000),
            columns=STANDARD,
            opening=Decimal("5000.00"),
        ),
        _case(
            "ro_labels",
            "Data operatiunii / Detalii / Plati / Incasari, thousands separators",
            _movements("ro_labels", 6, low=1000, high=90000),
            columns=[
                ("Data operatiunii", "date", 16),
                ("Detalii", "desc", 34),
                ("Plati", "debit", 12),
                ("Incasari", "credit", 12),
            ],
            opening=Decimal("400000.00"),
        ),
        _case(
            "continuation",
            "wrapped descriptions (lines without a date) and a total row",
            _movements("continuation", 9, low=50, high=5000),
            columns=STANDARD,
            opening=Decimal("20000.00"),
            wrap=True,
        ),
        _case(
            "column_order",
            "credit before debit, description after the amounts",
            _movements("column_order", 8, low=10, high=3000),
            columns=[
                ("Data", "date", 10),
                ("Credit", "credit", 11),
                ("Debit", "debit", 11),
                ("Detalii tranzactie", "desc", 34),
                ("Ref", "ref", 8),
            ],
            opening=Decimal("8000.00"),
        ),
        _case(
            "two_pages",
            "60 movements over two pages, the header row repeated",
            _movements("two_pages", 60, low=5, high=4000),
            columns=STANDARD,
            opening=Decimal("90000.00"),
            per_page=40,
        ),
        _case(
            "dense",
            "30 movements on few days with near-equal amounts",
            _movements("dense", 30, low=99, high=101, same_day=True),
            columns=STANDARD,
            opening=Decimal("3000.00"),
        ),
    ]


# ----- scoring -----


def lenient_lines(tables: list[dict[str, Any]]) -> list[tuple[str, str, Decimal]]:
    """The movement lines a reading shows, row by row, skipping what does not read (the
    score counts them; ``parse_statement`` is the strict check)."""
    out = []
    for table in tables:
        headers = [str(h) for h in table.get("headers") or []]
        cols = {k: _col(headers, v) for k, v in (("date", _DATE), ("debit", _DEBIT))}
        cols["credit"], cols["desc"] = _col(headers, _CREDIT), _col(headers, _DESC)
        if None in (cols["date"], cols["debit"], cols["credit"]):
            continue
        for row in table.get("rows") or []:
            cells = [str(c) for c in row] + [""] * len(headers)
            desc = _plain(cells[cols["desc"]]) if cols["desc"] is not None else ""
            if not cells[cols["date"]].strip() or desc.startswith(("total", "sold")):
                continue
            try:
                date = _date(cells[cols["date"]], "")
                debit = _amount(cells[cols["debit"]], "")
                credit = _amount(cells[cols["credit"]], "")
            except StatementError:
                continue
            if bool(debit) != bool(credit):
                out.append((date, "debit" if debit else "credit", debit or credit))
    return out


def _same(field: str, read: str, truth: str) -> bool:
    try:
        if field in ("opening", "closing"):
            return _amount(read, field) == Decimal(truth)
        if field == "statement_date":
            return _date(read, field) == truth
        if field == "iban":
            return "".join(read.split()).upper() == truth
        if field == "holder_cui":
            return cui_key(read) == cui_key(truth)
        return read.strip().upper() == truth.upper()
    except (StatementError, ValueError):
        return False


def score(case: EvalCase, reader: Any, cui: str = CUI) -> CaseScore:
    """Read *case* with *reader* (a ``GeminiStatementReader``) and score it."""
    model = str(getattr(getattr(reader, "role", None), "model", "?"))
    base = {"case": case.name, "model": model, "lines_expected": len(case.movements)}
    started = time.monotonic()
    try:
        extraction, header = reader.read(case.pdf(), tenant_cui=cui)
    except Exception as exc:  # a refusal or a bad answer is a score, not a crash
        return CaseScore(read=False, error=str(exc)[:200], **base)
    seconds = round(time.monotonic() - started, 2)
    truth = [(m.date, m.side, m.amount) for m in case.movements]
    got = lenient_lines(extraction.tables)
    exact = sum(1 for a, b in zip(got, truth, strict=False) if a == b)
    try:
        parse_statement(extraction.tables, StatementMeta.model_validate(case.meta), cui)
        ties = True
    except StatementError:
        ties = False
    return CaseScore(
        read=True,
        identity=extraction.meta.identity_ok,
        iban=_same("iban", header.get("iban", ""), case.meta["iban"]),
        header_fields=sum(_same(f, header.get(f, ""), v) for f, v in case.meta.items()),
        ties=ties,
        lines_exact=exact if len(got) == len(truth) else min(exact, len(truth)),
        seconds=seconds,
        **base,
    )


def summary(scores: list[CaseScore]) -> dict[str, Any]:
    return {
        "cases": len(scores),
        "read": sum(s.read for s in scores),
        "ties": sum(s.ties for s in scores),
        "lines_exact": sum(s.lines_exact for s in scores),
        "lines_expected": sum(s.lines_expected for s in scores),
        "header_fields": sum(s.header_fields for s in scores),
        "header_expected": 6 * len(scores),
        "seconds": round(sum(s.seconds for s in scores), 2),
    }


def render(scores: list[CaseScore]) -> str:
    lines = [f"{'case':<14}{'model':<22}{'read':<6}{'ties':<6}{'lines':<10}{'header':<8}secs"]
    for s in scores:
        lines.append(
            f"{s.case:<14}{s.model:<22}{'yes' if s.read else 'NO':<6}"
            f"{'yes' if s.ties else 'NO':<6}{f'{s.lines_exact}/{s.lines_expected}':<10}"
            f"{f'{s.header_fields}/6':<8}{s.seconds}"
        )
        if s.error:
            lines.append(f"  error: {s.error}")
    t = summary(scores)
    lines.append(
        f"total: read {t['read']}/{t['cases']}, ties {t['ties']}/{t['cases']}, "
        f"lines {t['lines_exact']}/{t['lines_expected']}, "
        f"header {t['header_fields']}/{t['header_expected']}, {t['seconds']} s"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="poarta_contabila.ocr_eval", description=__doc__.split("\n")[0]
    )
    ap.add_argument("--base-url", help="the operator API (OPERATOR_TOKEN in the environment)")
    ap.add_argument("--model", help="read with this Google AI Studio model instead of the pin")
    ap.add_argument("--case", action="append", help="only this case (repeatable)")
    ap.add_argument("--write-pdfs", metavar="DIR", help="write the cases' PDFs here and stop")
    args = ap.parse_args(argv)

    chosen = [c for c in cases() if not args.case or c.name in args.case]
    if args.write_pdfs:
        out = Path(args.write_pdfs)
        out.mkdir(parents=True, exist_ok=True)
        for c in chosen:
            (out / f"{c.name}.pdf").write_bytes(c.pdf())
            print(f"{out / (c.name + '.pdf')}  {c.about}")
        return 0
    if not args.base_url:
        ap.error("--base-url or --write-pdfs")
    token = os.environ.get("OPERATOR_TOKEN")
    if not token:
        print("set OPERATOR_TOKEN (the service's operator token) in the environment")
        return 2
    import httpx

    client = httpx.Client(
        base_url=args.base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=300,
    )
    scores = []
    for c in chosen:  # one request per case: no request waits on six model calls
        params = {"case": c.name, **({"model": args.model} if args.model else {})}
        resp = client.post(f"/ocr-eval/{CUI}", params=params)
        if resp.status_code != 200:
            print(f"{c.name}: HTTP {resp.status_code} {resp.text[:300]}")
            return 1
        scores += [CaseScore.model_validate(s) for s in resp.json()["scores"]]
    print(render(scores))
    return 0


if __name__ == "__main__":
    sys.exit(main())
