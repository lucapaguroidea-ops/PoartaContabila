"""Which invoice does a bank line settle? A proposal for the person, never a decision.

A statement line names no partner (``extract/statement.py``: nothing is guessed from text),
so the bank mouths wait for a person to bind the partner and the invoice. This
module lists the invoices the line could settle, so the ``v3_approve`` question can carry
them; the person still answers, and only their answer reaches the package.

Deterministic, no model (LAW L21). Candidates, from the invoice Jobs this system
holds and the invoices the uploaded books show:

- the right side: a receipt (``incasare``) settles a sale (``iesire``), a payment
  (``plata``) a purchase (``intrare``); storno documents are not candidates;
- dated on or before the line;
- still open: its gross less what other bound bank lines already paid on it (``paid``, by
  partner + number); an invoice those lines settled in full is no candidate;
- ``full``: the open amount equals the line, to the cent;
- ``partial``: the open amount is larger and the bank's description names the invoice
  or its partner (an amount alone never proposes a partial payment); ``open_after`` is what
  stays open.

They are ranked by what the bank's description shows: the invoice number (strongest), then
the partner's name, then a full cover over a partial one. ``edit`` is a ready ``v3_approve``
edit only when one candidate leads alone; otherwise the person picks from the list or posts
it in SAGA.

``groups``: with no full candidate, two to four open invoices of one partner whose
open amounts add up to the line. A bank mouth writes one invoice per line, so a group is never
an edit: a person posts it in SAGA (or picks one invoice for a partial payment).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations
from typing import Any, Literal

from poarta_contabila.recon.numbers import normalize
from poarta_contabila.types import CanonicalDocument, Closed, Cui, FiscalDate, Money, SinkDoc

SETTLES = {"incasare": "iesire", "plata": "intrare"}
ROLE = {"incasare": "customer", "plata": "supplier"}
MAX_CANDIDATES = 5
MAX_GROUP = 4  # invoices in one combined payment
MAX_GROUP_POOL = 12  # newest open invoices of one partner searched for a group
MAX_GROUPS = 3

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
    cover: Literal["full", "partial"] = "full"
    open_after: Money = "0.00"  # what stays open on the invoice after this line


class CandidateGroup(Closed):
    """One payment for several invoices of one partner."""

    partner_cui: Cui
    partner_name: str | None
    invoices: list[Candidate]
    total: Money
    hits: list[Literal["number_in_text", "name_in_text"]]


class SettlementProposal(Closed):
    candidates: list[Candidate]
    groups: list[CandidateGroup] = []
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
    paid: Mapping[tuple[str, str], Decimal] | None = None,
) -> SettlementProposal:
    """The invoices *line* could settle, ranked; see the module docstring for the rules.

    *settled_ids* are invoice Job ids and *settled_numbers* ``(partner_cui, number)`` pairs
    settled in full elsewhere; *paid* is what other bound bank lines already paid, by
    ``settle_key``.
    """
    side = SETTLES.get(line.doc_class)
    if side is None:
        return SettlementProposal(candidates=[], edit=None, reason="not a bank line")
    amount = Decimal(line.totals.gross)
    text = " ".join([*(ln.desc for ln in line.lines), line.partner.name or ""])
    settled = set(settled_numbers)
    paid = paid or {}

    pool: dict[tuple[str, str], tuple[Candidate, Decimal]] = {}  # key → (invoice, open)

    def consider(source, cui, name, number, factura_id, date, gross) -> None:
        if not cui or date > line.date:
            return
        key = settle_key(cui, number)
        if key in settled or (factura_id and factura_id in settled_ids):
            return
        if key in pool and pool[key][0].source == "job":
            return  # the Job already stands for it, with its FacturaID
        open_ = Decimal(gross) - paid.get(key, Decimal(0))
        if open_ <= 0:
            return
        hits = []
        if number_in_text(number, text):
            hits.append("number_in_text")
        if name_in_text(name, text):
            hits.append("name_in_text")
        pool[key] = (
            Candidate(
                source=source,
                partner_cui=cui,
                partner_name=name,
                factura_numar=number,
                factura_id=factura_id,
                date=date,
                gross=gross,
                hits=hits,
            ),
            open_,
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

    found: list[Candidate] = []
    for c, open_ in pool.values():
        if open_ == amount:
            found.append(c.model_copy(update={"hits": ["amount", *c.hits]}))
        elif open_ > amount and c.hits:
            found.append(
                c.model_copy(update={"cover": "partial", "open_after": f"{open_ - amount:.2f}"})
            )

    def text_score(hits: list[str]) -> int:
        return 2 * ("number_in_text" in hits) + ("name_in_text" in hits)

    def score(c: Candidate) -> tuple[int, bool, bool, str]:
        return (text_score(c.hits), c.cover == "full", c.source == "job", c.date)

    ranked = sorted(found, key=score, reverse=True)[:MAX_CANDIDATES]
    groups = [] if any(c.cover == "full" for c in ranked) else _groups(pool, amount, text)
    best_group = max((text_score(g.hits) for g in groups), default=-1)

    if not ranked:
        if groups:
            g = groups[0]
            who = g.partner_name or g.partner_cui
            return SettlementProposal(
                candidates=[],
                groups=groups,
                edit=None,
                reason=(
                    f"one payment for {len(g.invoices)} invoices of {who}: a bank line names "
                    "one invoice, so a person posts it in SAGA"
                ),
            )
        return SettlementProposal(
            candidates=[], edit=None, reason="no open invoice of this amount on this side"
        )
    top = score(ranked[0])[:2]
    leaders = [c for c in ranked if score(c)[:2] == top]
    if len(leaders) > 1:
        return SettlementProposal(
            candidates=ranked,
            groups=groups,
            edit=None,
            reason=f"{len(leaders)} invoices fit equally: a person picks one or posts it in SAGA",
        )
    if text_score(leaders[0].hits) <= best_group:
        return SettlementProposal(
            candidates=ranked,
            groups=groups,
            edit=None,
            reason="one invoice or several together fit as well: a person picks or posts it",
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
    if best.cover == "partial":
        reason = (
            f"a partial payment on {best.factura_numar} leads ({shown}); {best.open_after} "
            "stays open: confirm or correct"
        )
    else:
        reason = f"one invoice leads ({shown}): confirm or correct"
    return SettlementProposal(candidates=ranked, groups=groups, edit=edit, reason=reason)


def _groups(
    pool: Mapping[tuple[str, str], tuple[Candidate, Decimal]], amount: Decimal, text: str
) -> list[CandidateGroup]:
    """Two to four open invoices of one partner whose open amounts add up to *amount*."""
    by_partner: dict[str, list[tuple[Candidate, Decimal]]] = {}
    for c, open_ in pool.values():
        if open_ < amount:
            by_partner.setdefault(c.partner_cui, []).append((c, open_))
    out: list[CandidateGroup] = []
    for cui, items in by_partner.items():
        items = sorted(items, key=lambda x: x[0].date, reverse=True)[:MAX_GROUP_POOL]
        name = next((c.partner_name for c, _ in items if c.partner_name), None)
        for n in range(2, MAX_GROUP + 1):
            for combo in combinations(items, n):
                if sum(o for _, o in combo) != amount:
                    continue
                members = [
                    c.model_copy(update={"hits": ["amount", *c.hits]})
                    for c, _ in sorted(combo, key=lambda x: x[0].date)
                ]
                hits = []
                if any("number_in_text" in c.hits for c in members):
                    hits.append("number_in_text")
                if name_in_text(name, text):
                    hits.append("name_in_text")
                out.append(
                    CandidateGroup(
                        partner_cui=cui,
                        partner_name=name,
                        invoices=members,
                        total=f"{amount:.2f}",
                        hits=hits,
                    )
                )
    out.sort(
        key=lambda g: (
            -(2 * ("number_in_text" in g.hits) + ("name_in_text" in g.hits)),
            len(g.invoices),
        )
    )
    return out[:MAX_GROUPS]
