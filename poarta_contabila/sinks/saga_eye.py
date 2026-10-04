"""SagaEye: the read-only witness protocol (ARCHITECTURE.md §6).

Core graphs depend only on this protocol. v1 reads the SAGA report pack /
RJ-CM export; FDB SQL is parked (WP-15).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from poarta_contabila.sinks.exports import (
    BalanceRow,
    ExportError,
    ExportEye,
    SinkLine,
    _date,
    _doc_number,
    _money,
    _sheet_cells,
    _text,
)
from poarta_contabila.types import SinkDoc, cui_key


@runtime_checkable
class SagaEye(Protocol):
    def covers(self, cui: str, period: str) -> bool:
        """True only if this witness holds the firm's books for that month.

        "Not in the books" may be concluded only for a covered month (PRE ``absent``).
        """
        ...

    def documents(self, cui: str, period: str) -> list[SinkDoc]: ...

    def turnover(self, cui: str, period: str) -> dict[str, dict[str, str]]:
        """Period turnover per synthetic account: ``{account: {debit, credit}}``."""
        ...

    def journal_lines(self, cui: str, period: str) -> list[SinkLine]:
        """The journal register's lines of the month ([] when the eye has none)."""
        ...

    def solduri(self, cui: str, period: str) -> dict[str, dict]: ...

    def analytic(self, cui: str, period: str, root: str) -> dict[str, dict]: ...


class FakeSagaEye:
    """Witness with nothing in it. For tests and for a tenant with no eye yet."""

    def covers(self, cui: str, period: str) -> bool:
        return False

    def turnover(self, cui: str, period: str) -> dict[str, dict[str, str]]:
        return {}

    def journal_lines(self, cui: str, period: str) -> list[SinkLine]:
        return []

    def documents(self, cui: str, period: str) -> list[SinkDoc]:
        return []

    def solduri(self, cui: str, period: str) -> dict[str, dict]:
        return {}

    def analytic(self, cui: str, period: str, root: str) -> dict[str, dict]:
        return {}


# ----- SAGA report pack: purchase / sales journals (harvest C-F11) -----
#
# One row per document: date, number, partner (name, tax id), total incl. VAT, and a
# base/VAT column pair per rate. Headers sit in the first rows and are located by label.
# The aliases below follow the harvest description; [de confirmat] against a real
# report-pack export (the example pack had none).

TVA_JOURNAL_COLUMNS: dict[str, tuple[str, ...]] = {
    "date": ("Data", "Data doc", "Data document"),
    "number": ("Nr. doc", "Nr. document", "Numar document", "Numar"),
    "partner": ("Denumire partener", "Furnizor", "Client", "Denumire", "Partener"),
    "tax_id": ("Cod fiscal", "CIF", "Cod fiscal partener", "CUI"),
    "total": ("Total document", "Total (inclusiv TVA)", "Total cu TVA", "Total"),
}
_BASE_PREFIX, _VAT_PREFIX = ("baza",), ("tva",)


def _label(text: str) -> str:
    return " ".join(text.replace(".", ". ").split()).strip().lower().replace(" .", ".")


def _locate(head: list[str], aliases: tuple[str, ...]) -> int | None:
    norm = [_label(h) for h in head]
    for alias in aliases:
        if _label(alias) in norm:
            return norm.index(_label(alias))
    return None


def read_saga_tva_journal(path: str | Path, side: Literal["cumparari", "vanzari"]) -> list[SinkDoc]:
    """SAGA *Jurnal de cumpărări* / *vânzări* → one :class:`SinkDoc` per document.

    Every row must add up (Σ base + Σ VAT = total). Total and blank rows are skipped.
    Raises :class:`ExportError`.
    """
    path = Path(path)
    values, formats, datemode = _sheet_cells(path)
    head_at = None
    for i, row in enumerate(values[:20]):
        head = [_text(v) for v in row]
        if all(_locate(head, a) is not None for a in TVA_JOURNAL_COLUMNS.values()):
            head_at = i
            break
    if head_at is None:
        raise ExportError(f"{path.name}: TVA journal header not found in the first 20 rows")
    head = [_text(v) for v in values[head_at]]
    col = {k: _locate(head, a) for k, a in TVA_JOURNAL_COLUMNS.items()}
    norm = [_label(h) for h in head]
    bases = [i for i, h in enumerate(norm) if h.startswith(_BASE_PREFIX)]
    vats = [i for i, h in enumerate(norm) if h.startswith(_VAT_PREFIX)]
    if not bases or not vats:
        raise ExportError(f"{path.name}: no Baza / TVA columns")
    doc_class = "intrare" if side == "cumparari" else "iesire"
    docs: list[SinkDoc] = []
    for r in range(head_at + 1, len(values)):
        cells = values[r] + [None] * (len(head) - len(values[r]))
        where = f"{path.name} row {r + 1}"
        first = _text(cells[0]).lower()
        if first.startswith(("total", "pagina")) or _text(cells[col["date"]]) == "":
            continue
        number = _doc_number(cells[col["number"]], formats[r][col["number"]])
        if not number:
            raise ExportError(f"{where}: no document number")
        base = sum((Decimal(_money(cells[i], where)) for i in bases), Decimal(0))
        vat = sum((Decimal(_money(cells[i], where)) for i in vats), Decimal(0))
        total = Decimal(_money(cells[col["total"]], where))
        if base + vat != total:
            raise ExportError(f"{where}: base {base} + VAT {vat} ≠ total {total}")
        day = _date(cells[col["date"]], datemode, where)
        docs.append(
            SinkDoc(
                saga_key=f"saga:{side}:{number}:{day}",
                doc_class=doc_class,
                number=number,
                date=day,
                partner_cui=cui_key(_text(cells[col["tax_id"]])),
                gross=str(total),
                net=str(base),
                vat=str(vat),
                validated=True,  # the journals list posted documents [de confirmat]
            )
        )
    return docs


class ReportPackEye:
    """SagaEye over the report pack's purchase/sales journals (+ balance when given).

     The journals hold invoices only. With *journal* (the registru jurnal of the same firm),
     its bank documents, journal lines and turnover are read from it for the months it covers
    : otherwise a statement line SAGA already holds would look absent."""

    def __init__(
        self,
        *,
        documents: list[SinkDoc],
        cui: str | None,
        periods: Iterable[str],
        balance: list[BalanceRow] | None = None,
        journal: ExportEye | None = None,
    ) -> None:
        self.docs = documents
        self.cui = cui
        self.periods = frozenset(periods)
        self._balance = ExportEye(product="saga", lines=[], balance=balance or [], cui=cui)
        self._journal = journal

    def _rj(self, cui: str, period: str) -> ExportEye | None:
        j = self._journal
        return j if j is not None and j.covers(cui, period) else None

    def covers(self, cui: str, period: str) -> bool:
        return self.cui is not None and self.cui == cui and period in self.periods

    def documents(self, cui: str, period: str) -> list[SinkDoc]:
        docs = [d for d in self.docs if d.date.startswith(period)]
        rj = self._rj(cui, period)
        if rj is not None:
            docs += rj.bank_documents(period)
        return sorted(docs, key=lambda d: (d.date, d.saga_key))

    def turnover(self, cui: str, period: str) -> dict[str, dict[str, str]]:
        rj = self._rj(cui, period)
        return rj.turnover(cui, period) if rj is not None else self._balance.turnover(cui, period)

    def journal_lines(self, cui: str, period: str) -> list[SinkLine]:
        rj = self._rj(cui, period)
        return rj.journal_lines(cui, period) if rj is not None else []

    def solduri(self, cui: str, period: str) -> dict[str, dict]:
        return self._balance.solduri(cui, period)

    def analytic(self, cui: str, period: str, root: str) -> dict[str, dict]:
        return self._balance.analytic(cui, period, root)
