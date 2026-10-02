"""Which invoice does a bank line settle? A proposal for the person, never a decision (WP-22).

A statement line names no partner (``extract/statement.py``: nothing is guessed from text),
so the bank mouths (WP-19) wait for a person to bind the partner and the invoice. This
module lists the invoices the line could settle, so the ``v3_approve`` question can carry
them; the person still answers, and only their answer reaches the package.

Deterministic, no model (00_LAW invariant 4). Candidates, from the invoice Jobs this system
holds and the invoices the uploaded books show:

- the right side: a receipt (``incasare``) settles a sale (``iesire``), a payment
  (``plata``) a purchase (``intrare``); storno documents are not candidates;
- the same gross, to the cent (a partial payment gets no candidate);
- dated on or before the line;
- not already named by another bound bank line (by ``FacturaID`` or partner + number).

They are ranked by what the bank's description shows: the invoice number (strongest), then
the partner's name, then the amount alone. ``edit`` is a ready ``v3_approve`` edit only when
one candidate leads alone; otherwise the person picks from the list or posts it in SAGA.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from poarta_contabila.recon.numbers import normalize
from poarta_contabila.types import CanonicalDocument, Closed, Cui, FiscalDate, Money, SinkDoc

SETTLES = {"incasare": "iesire", "plata": "intrare"}
ROLE = {"incasare": "customer", "plata": "supplier"}
MAX_CANDIDATES = 5

# legal forms and filler that say nothing about who the partner is
_NOISE = frozenset(
    "sc srl sa snc scs sca pfa ii if ra rl ltd gmbh co cooperativa societatea the and si".split()
)
_HITS = ("number_in_text", "name_in_text")


class Candidate(Closed):
    source: Literal["job", "books"]  # an invoice Job of this system | the books' journals
    partner_cui: Cui
    partner_name: str | None
    factura_numar: str
    factura_id: str | None  # the invoice Job's id (its FacturaID), when source = job
    date: FiscalDate
    gross: Money
    hits: list[Literal["amount", "number_in_text", "name_in_text"]]


class SettlementProposal(Closed):
    candidates: list[Candidate]
    edit: dict[str, Any] | None
    reason: str


@dataclass(frozen=True)
class InvoiceJob:
    """An invoice Job and the document its thread carries."""

    job_id: str
    doc: CanonicalDocument


def _tokens(text: str | None) -> list[str]:
    plain = unicodedata.normalize("NFKD", str(text or ""))
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower().replace(".", "")
    return [t for t in re.split(r"[^0-9a-z]+", plain) if t]


def number_in_text(number: str, text: str) -> bool:
    """The invoice number reads in *text*: as one token or a run of up to three tokens
    (``FX-101`` in "… FX-101", "… fx 101"). Shorter than three characters never counts."""
    wanted = (normalize(number, "alnum") or "").lower()
    if len(wanted) < 3:
        return False
    words = _tokens(text)
    return any("".join(words[i : i + n]) == wanted for n in (1, 2, 3) for i in range(len(words)))


def name_in_text(name: str | None, text: str) -> bool:
    """Every telling word of the partner's name (legal forms dropped) is in *text*."""
    core = [t for t in _tokens(name) if t not in _NOISE and len(t) >= 2]
    words = set(_tokens(text))
    return bool(core) and all(t in words for t in core)


def settle_key(cui: str, number: str) -> tuple[str, str]:
    return cui, normalize(number, "alnum") or ""


def propose_settlement(
    line: CanonicalDocument,
    invoices: Iterable[InvoiceJob],
    books: Iterable[SinkDoc] = (),
    *,
    settled_ids: frozenset[str] = frozenset(),
    settled_numbers: frozenset[tuple[str, str]] = frozenset(),
) -> SettlementProposal:
    """The invoices *line* could settle, ranked; see the module docstring for the rules.

    *settled_ids* are invoice Job ids and *settled_numbers* ``(partner_cui, number)`` pairs
    that other bound bank lines already name.
    """
    side = SETTLES.get(line.doc_class)
    if side is None:
        return SettlementProposal(candidates=[], edit=None, reason="not a bank line")
    amount = Decimal(line.totals.gross)
    text = " ".join([*(ln.desc for ln in line.lines), line.partner.name or ""])
    settled = set(settled_numbers)

    found: dict[tuple[str, str], Candidate] = {}

    def consider(source, cui, name, number, factura_id, date, gross) -> None:
        if not cui or Decimal(gross) != amount or date > line.date:
            return
        key = settle_key(cui, number)
        if key in settled or (factura_id and factura_id in settled_ids):
            return
        if key in found and found[key].source == "job":
            return  # the Job already stands for it, with its FacturaID
        hits = ["amount"]
        if number_in_text(number, text):
            hits.append("number_in_text")
        if name_in_text(name, text):
            hits.append("name_in_text")
        found[key] = Candidate(
            source=source,
            partner_cui=cui,
            partner_name=name,
            factura_numar=number,
            factura_id=factura_id,
            date=date,
            gross=gross,
            hits=hits,
        )

    for inv in invoices:
        d = inv.doc
        if d.doc_class == side and not d.is_storno and d.tenant.cui == line.tenant.cui:
            consider(
                "job", d.partner.cui, d.partner.name, d.number, inv.job_id, d.date, d.totals.gross
            )
    for s in books:
        if s.doc_class == side:
            consider("books", s.partner_cui, None, s.number, None, s.date, s.gross)

    def score(c: Candidate) -> tuple[int, int, str]:
        return (
            2 * ("number_in_text" in c.hits) + ("name_in_text" in c.hits),
            c.source == "job",
            c.date,
        )

    ranked = sorted(found.values(), key=score, reverse=True)[:MAX_CANDIDATES]
    if not ranked:
        return SettlementProposal(
            candidates=[], edit=None, reason="no open invoice of this amount on this side"
        )
    top = score(ranked[0])[0]
    leaders = [c for c in ranked if score(c)[0] == top]
    if len(leaders) > 1:
        return SettlementProposal(
            candidates=ranked,
            edit=None,
            reason=f"{len(leaders)} invoices fit equally: a person picks one or posts it in SAGA",
        )
    best = leaders[0]
    maps = {"factura_numar": best.factura_numar}
    if best.factura_id:
        maps["factura_id"] = best.factura_id
    edit = {
        "partner": {
            "cui": best.partner_cui,
            "name": best.partner_name or line.partner.name,
            "role": ROLE[line.doc_class],
        },
        "maps": maps,
    }
    shown = ", ".join(h for h in best.hits if h in _HITS) or "the amount alone"
    return SettlementProposal(
        candidates=ranked, edit=edit, reason=f"one invoice leads ({shown}): confirm or correct"
    )
