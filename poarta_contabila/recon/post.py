"""POST recon: how did SAGA post this document? Deterministic, no model.

For an ``acked`` Job (SAGA shows its document validated), the registru jurnal's lines of that
posting are found — the invoice journal (SAGA ``Intrari`` / ``Iesiri``, NextUp ``JC`` / ``JV``),
the same date, the number at a level the profile accepts — and the synthetic accounts they use
are compared with what the articol de cale expects (``reconcile.expect_accounts``, else the
POST profile's ``fallback_accounts``):

- ``require_all_accounts: true``: every expected account appears;
- ``false``: at least one does (the catalog's flag; ``[de confirmat]`` on a copy firm).

An expected account matches a used one by prefix (``401`` ← ``401.00001``; class ``6`` ← ``628``).

Amounts: once the accounts fit, every expected account the profile's
``account_amounts`` lists (``401`` / ``4111`` → the document's gross, ``4426`` / ``4427`` /
``4428`` → its VAT) is checked: the amount the posting moves on it (each line once, on either
side) against the document, within the articol's ``tolerance`` (else the profile's). Accounts
not listed — class 6 / 7, where the net may be split — are not compared.

Verdicts (``verdict_det``): ``how_ok``; ``how_mismatch`` (no posting found in a month the
journal covers, the expected accounts are not used, an amount differs, no expected accounts at
all, or no single POST profile); ``need_rj_export`` (the month is not covered, or the eye has
no journal lines — the report pack's purchase / sales journals carry no accounts). The snapshot
covers the profile (incl. its amounts and tolerance) and the posting's own lines, so a verdict
(and a person's answer to it) holds until that posting changes in SAGA.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, Literal

from pydantic import Field

from poarta_contabila.recon.numbers import NumberLevel, match_level
from poarta_contabila.sinks.exports import (
    _BANK_JOURNALS,
    _INVOICE_JOURNALS,
    SinkLine,
    synthetic,
)
from poarta_contabila.sinks.saga_xml import packaged_number
from poarta_contabila.types import CanonicalDocument, Closed, Money, Slug

PostVerdict = Literal["how_ok", "how_mismatch", "need_rj_export"]


class AccountAmount(Closed):
    """What the posting moved on one expected account, against the document."""

    account: str
    of: Literal["gross", "vat"]
    expected: Money
    posted: Money
    ok: bool


class PostResult(Closed):
    verdict: PostVerdict
    reason: str
    profile_id: Slug | None
    snapshot_id: str
    expected: list[str] = Field(default_factory=list)
    used: list[str] = Field(default_factory=list)
    require_all: bool = False
    rows: list[int] = Field(default_factory=list)  # registru jurnal rows of the posting
    missing: list[str] = Field(default_factory=list)  # months the journal does not cover
    amounts: list[AccountAmount] = Field(default_factory=list)


def posting_lines(
    lines: list[SinkLine], product: str, doc: CanonicalDocument, levels: tuple[NumberLevel, ...]
) -> list[SinkLine]:
    """The journal lines of *doc*'s posting: same date, number at an accepted level. An
    invoice is looked for in the invoice journals; a bank line in the bank journal, under the
    number SAGA was given (``packaged_number``)."""
    bank = doc.doc_class in ("incasare", "plata")
    journals = _BANK_JOURNALS[product] if bank else _INVOICE_JOURNALS[product]
    number = packaged_number(doc)
    out = []
    for ln in lines:
        if ln.journal not in journals or ln.date != doc.date:
            continue
        level = match_level(number, ln.doc_number, levels)
        if level is not None and level != "digits_core":  # digits alone name no posting
            out.append(ln)
    return out


def _snapshot(profile_id: str | None, rows: list[SinkLine], extra: dict[str, Any]) -> str:
    body = {
        "profile": profile_id,
        "lines": [ln.model_dump() for ln in sorted(rows, key=lambda x: x.row)],
        **extra,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def how_check(
    doc: CanonicalDocument,
    articol: dict[str, Any],
    profile: dict[str, Any] | None,
    eye: Any,
    cui: str,
) -> PostResult:
    """The deterministic POST verdict for *doc* against the registru jurnal in *eye*."""
    if profile is None:
        return PostResult(
            verdict="how_mismatch",
            reason="no single POST articol for this document",
            profile_id=None,
            snapshot_id="no-profile",
        )
    pid = profile["profile_id"]
    reconcile = articol.get("reconcile") or {}
    expected = [str(a) for a in (reconcile.get("expect_accounts") or [])] or [
        str(a) for a in (profile.get("fallback_accounts") or [])
    ]
    require_all = bool(reconcile.get("require_all_accounts", profile.get("require_all_accounts")))
    base = {"profile_id": pid, "expected": expected, "require_all": require_all}

    lines = getattr(eye, "lines", None)
    if eye is None or lines is None:
        return PostResult(
            verdict="need_rj_export",
            reason="POST reads the registru jurnal's accounts; none is uploaded",
            snapshot_id=f"no-rj:{doc.period}",
            missing=[doc.period],
            **base,
        )
    if not eye.covers(cui, doc.period):
        return PostResult(
            verdict="need_rj_export",
            reason=f"the registru jurnal does not cover {doc.period}",
            snapshot_id=f"uncovered:{doc.period}",
            missing=[doc.period],
            **base,
        )
    levels = tuple(profile.get("number_match") or ("exact", "alnum"))
    rows = posting_lines(lines, eye.product, doc, levels)
    used = sorted({synthetic(a) for ln in rows for a in (ln.debit, ln.credit)})
    amount_of = dict(profile.get("account_amounts") or {})
    tolerance = Decimal(str(reconcile.get("tolerance") or profile.get("tolerance") or "0"))
    snapshot = _snapshot(
        pid,
        rows,
        {
            "expected": expected,
            "require_all": require_all,
            "amounts": amount_of,
            "tolerance": str(tolerance),
        },
    )
    found = {
        "snapshot_id": snapshot,
        "used": used,
        "rows": sorted(ln.row for ln in rows),
        **base,
    }
    if not rows:
        return PostResult(
            verdict="how_mismatch",
            reason=f"the registru jurnal shows no posting of {doc.number} on {doc.date}",
            **found,
        )
    if not expected:
        return PostResult(
            verdict="how_mismatch",
            reason="the articol names no expected accounts (see WP-D3): a person checks",
            **found,
        )
    hits = [e for e in expected if any(u.startswith(e) for u in used)]
    ok = len(hits) == len(expected) if require_all else bool(hits)
    if ok:
        amounts = account_amounts(doc, rows, hits, amount_of, tolerance)
        off = [a for a in amounts if not a.ok]
        if off:
            shown = "; ".join(
                f"{a.account} posted {a.posted}, document {a.of} {a.expected}" for a in off
            )
            return PostResult(
                verdict="how_mismatch",
                reason=f"posted on {used}, but the amounts differ: {shown}",
                amounts=amounts,
                **found,
            )
        return PostResult(verdict="how_ok", reason=f"posted on {used}", amounts=amounts, **found)
    want = "all of" if require_all else "any of"
    return PostResult(
        verdict="how_mismatch",
        reason=f"posted on {used}; expected {want} {expected}",
        **found,
    )


def account_amounts(
    doc: CanonicalDocument,
    rows: list[SinkLine],
    accounts: list[str],
    amount_of: dict[str, str],
    tolerance: Decimal,
) -> list[AccountAmount]:
    """For each of *accounts* that *amount_of* lists: the amount the posting moved on it."""
    out = []
    for acct in accounts:
        of = amount_of.get(acct)
        if of not in ("gross", "vat"):
            continue
        moved = sum(
            (
                Decimal(ln.amount)
                for ln in rows
                if synthetic(ln.debit).startswith(acct) or synthetic(ln.credit).startswith(acct)
            ),
            Decimal(0),
        )
        want = Decimal(getattr(doc.totals, of))
        out.append(
            AccountAmount(
                account=acct,
                of=of,
                expected=f"{want:.2f}",
                posted=f"{moved:.2f}",
                ok=abs(moved - want) <= tolerance,
            )
        )
    return out
