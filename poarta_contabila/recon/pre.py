"""PRE recon (WP-05): is this document already in the books? Deterministic, no model.

Witnesses: the registru jurnal (a :class:`SagaEye`) and, for purchases, the SPV
register. The profile is the ``reconcile_sink`` row on stage ``pre`` that flux
matching picks for the document (ARTICOLE_RECONCILE).

Verdicts (``verdict_det``):

- ``already_posted``: one sink document agrees on every profile key (numbers at an
  accepted level, ``digits_core`` only with the same partner CUI), gross within the
  tolerance, and no conflicting partner CUI; or the SPV register lists the invoice as
  "Înregistrat în SAGA" on the same terms. Ingest must not package.
- ``ambiguous``: two such hits; something close but not decisive (two of number, date
  and gross agree); no single PRE profile; or a month that must be read has no export
  of the books (``need_rj_export``). A person decides.
- ``absent``: every month from the document's to the job's is covered by the
  registru jurnal and nothing is close. Only then may ingest package.

Matching is generous on purpose: a missed match packages a duplicate, a false "close"
costs one question. Verdicts are stored once per ``(job_id, stage, sink_snapshot_id)``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import Field

from poarta_contabila.catalog import Catalog
from poarta_contabila.flux import MatchContext, match_articole
from poarta_contabila.recon.numbers import LEVELS, NumberLevel, match_level
from poarta_contabila.sinks.saga_eye import SagaEye
from poarta_contabila.sinks.spv_register import RegisterInvoice, _plain
from poarta_contabila.types import CanonicalDocument, Closed, JobRecord, SinkDoc, Slug

GRAPH_ID = "reconcile_sink"
PreVerdict = Literal["absent", "already_posted", "ambiguous"]
WitnessName = Literal["registru_jurnal", "spv_register"]
_KEYS = {"number", "date", "gross"}
_SIDES = {
    "intrare": ("intrare", "storn_intrare"),
    "storn_intrare": ("intrare", "storn_intrare"),
    "iesire": ("iesire", "storn_iesire"),
    "storn_iesire": ("iesire", "storn_iesire"),
}
_INBOUND = {"intrare", "storn_intrare"}
_MAX_MONTHS = 24
_LEGAL_FORMS = re.compile(r"\b(s ?r ?l|s ?a|s ?c ?s|p ?f ?a|i ?i|srl ?d)\b")


class PreResult(Closed):
    verdict: PreVerdict
    reason: str
    profile_id: Slug | None
    snapshot_id: str
    witness: WitnessName | None = None
    level: NumberLevel | None = None
    hits: list[str] = Field(default_factory=list)
    near: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Witnesses:
    """What PRE may read for one tenant: its books, and its SPV register if kept.

    The caller picks them by the job's tenant; the eye's ``covers`` checks the firm.
    """

    eye: SagaEye
    register: list[RegisterInvoice] = field(default_factory=list)


class ReconStore(Protocol):
    def put_once(self, job_id: str, stage: str, result: PreResult) -> PreResult: ...


@dataclass
class InMemoryReconStore:
    rows: dict[tuple[str, str, str], PreResult] = field(default_factory=dict)

    def put_once(self, job_id: str, stage: str, result: PreResult) -> PreResult:
        """Store the verdict for this sink snapshot; a replay returns the first one."""
        return self.rows.setdefault((job_id, stage, result.snapshot_id), result)


class PostgresReconStore:
    """Verdicts in ``domain.recon_verdicts`` (key ``(job_id, stage, sink_snapshot_id)``)."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn = dsn
        self._psycopg = psycopg

    def put_once(self, job_id: str, stage: str, result: PreResult) -> PreResult:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.recon_verdicts (job_id, stage, sink_snapshot_id, body)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (job_id, stage, result.snapshot_id, result.model_dump_json()),
            )
            (body,) = conn.execute(
                "SELECT body FROM domain.recon_verdicts"
                " WHERE job_id = %s AND stage = %s AND sink_snapshot_id = %s",
                (job_id, stage, result.snapshot_id),
            ).fetchone()
        return PreResult.model_validate(body, strict=False)


# ----- profile -----


def check_profile(profile: dict[str, Any]) -> None:
    """Refuse a profile the matcher cannot honour (called at wiring time)."""
    pid = profile.get("profile_id")
    keys = set(profile.get("match_keys") or [])
    if not keys or not keys <= _KEYS:
        raise ValueError(f"profile {pid}: match_keys {sorted(keys)} not within {sorted(_KEYS)}")
    levels = profile.get("number_match")
    if "number" in keys and not levels:
        raise ValueError(f"profile {pid}: keyed by number but has no number_match")
    if levels and not set(levels) <= set(LEVELS):
        raise ValueError(f"profile {pid}: number_match {levels} not within {list(LEVELS)}")
    try:
        if Decimal(str(profile.get("tolerance"))) < 0:
            raise ValueError
    except Exception as exc:
        raise ValueError(f"profile {pid}: tolerance must be a non-negative amount") from exc


def pre_profile(
    cat: Catalog,
    doc: CanonicalDocument,
    *,
    fiscal_class: str | None,
    axes: dict[str, str],
    allow_draft: bool = True,
) -> dict[str, Any] | None:
    """The one PRE profile for this document, or None (no row, or a tie)."""
    role = "inbound" if doc.doc_class in _INBOUND else "outbound"
    ctx = MatchContext(
        graph_id=GRAPH_ID,
        fiscal_class=fiscal_class,
        our_role=role if doc.doc_class in _SIDES else None,
        is_storno=doc.is_storno,
        axes=axes,
        day=doc.date,
        stage="pre",
    )
    rows = match_articole(cat, ctx, allow_draft=allow_draft)
    if len(rows) != 1:
        return None
    return cat.recon_profiles[cat.articole[rows[0]]["profile_id"]]


# ----- matching -----


def _months(first: str, last: str) -> list[str]:
    if first > last:
        first, last = last, first
    y, m = int(first[:4]), int(first[5:])
    out = []
    while f"{y:04d}-{m:02d}" <= last and len(out) <= _MAX_MONTHS:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _name_key(name: str) -> str:
    plain = re.sub(r"[^a-z0-9 ]", " ", _plain(name))
    return " ".join(_LEGAL_FORMS.sub(" ", plain).split())


@dataclass(frozen=True)
class _Cand:
    ref: str
    witness: WitnessName
    number: str | None
    date: str
    gross: Decimal
    partner: Literal["same", "differs", "unknown"]


def _partner_by_cui(doc: CanonicalDocument, sink: SinkDoc) -> Literal["same", "differs", "unknown"]:
    if doc.partner.cui is None or sink.partner_cui is None:
        return "unknown"
    return "same" if doc.partner.cui == sink.partner_cui else "differs"


def _judge(
    c: _Cand,
    *,
    keys: set[str],
    levels: tuple[NumberLevel, ...],
    doc: CanonicalDocument,
    tolerance: Decimal,
) -> tuple[Literal["hit", "near"] | None, NumberLevel | None]:
    if c.partner == "differs":
        return None, None
    level = match_level(doc.number, c.number, levels) if "number" in keys else None
    date_ok = c.date == doc.date
    gross_ok = abs(c.gross - Decimal(doc.totals.gross)) <= tolerance
    number_ok = level is not None and (level != "digits_core" or c.partner == "same")
    agree = {"number": number_ok, "date": date_ok, "gross": gross_ok}
    if all(agree[k] for k in keys) and gross_ok:
        return "hit", level
    if level is None and "number" in keys and c.partner != "same":
        return None, None  # date and gross alone, partner unknown: too weak to ask about
    if sum((level is not None, date_ok, gross_ok)) >= 2:
        return "near", level
    return None, None


def det_match(
    profile: dict[str, Any], job: JobRecord, doc: CanonicalDocument, witnesses: Witnesses
) -> PreResult:
    """The deterministic PRE verdict for one document against the witnesses."""
    keys = set(profile["match_keys"])
    levels = tuple(profile.get("number_match") or ())
    tolerance = Decimal(str(profile["tolerance"]))
    cui = job.tenant.cui
    months = _months(doc.period, job.period)
    covered = {p: witnesses.eye.covers(cui, p) for p in months}
    sides = _SIDES.get(doc.doc_class, (doc.doc_class,))

    sink_docs = [
        d
        for p in months
        if covered[p]
        for d in witnesses.eye.documents(cui, p)
        if d.doc_class in sides
    ]
    cands = [
        _Cand(
            d.saga_key,
            "registru_jurnal",
            d.number,
            d.date,
            Decimal(d.gross),
            _partner_by_cui(doc, d),
        )
        for d in sink_docs
    ]
    register = [r for r in witnesses.register if r.posted] if doc.doc_class in _INBOUND else []
    for r in register:
        same = _name_key(r.supplier) == _name_key(doc.partner.name)
        cands.append(
            _Cand(
                r.ref,
                "spv_register",
                r.number,
                r.date,
                Decimal(r.gross),
                "same" if same else "unknown",
            )
        )

    snapshot = hashlib.sha256(
        json.dumps(
            {
                "profile": [profile["profile_id"], str(profile.get("schema_version"))],
                "covered": sorted(covered.items()),
                "sink": [d.model_dump() for d in sink_docs],
                "register": [r.model_dump() for r in register],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()

    def result(verdict: PreVerdict, reason: str, **kw: Any) -> PreResult:
        return PreResult(
            verdict=verdict,
            reason=reason,
            profile_id=profile["profile_id"],
            snapshot_id=snapshot,
            **kw,
        )

    if len(months) > _MAX_MONTHS:
        return result("ambiguous", f"document period {doc.period} is too far from {job.period}")

    hits: list[tuple[_Cand, NumberLevel | None]] = []
    near: list[str] = []
    for c in cands:
        kind, level = _judge(c, keys=keys, levels=levels, doc=doc, tolerance=tolerance)
        if kind == "hit":
            hits.append((c, level))
        elif kind == "near":
            near.append(c.ref)

    book_hits = [(c, lv) for c, lv in hits if c.witness == "registru_jurnal"]
    reg_hits = [(c, lv) for c, lv in hits if c.witness == "spv_register"]
    if len(book_hits) > 1 or len(reg_hits) > 1:
        return result(
            "ambiguous",
            "more than one document in the books matches",
            hits=[c.ref for c, _ in hits],
            near=near,
        )
    if hits:
        c, level = (book_hits or reg_hits)[0]
        reason = f"{c.witness} has {c.ref}"
        if not book_hits:
            reason += "; registru jurnal shows no line for it"
        return result(
            "already_posted",
            reason,
            witness=c.witness,
            level=level,
            hits=[h.ref for h, _ in hits],
            near=near,
        )
    if near:
        return result("ambiguous", "a close but not decisive match", near=near)
    missing = [p for p in months if not covered[p]]
    if missing:
        return result("ambiguous", f"need_rj_export: no registru jurnal export for {missing}")
    return result("absent", f"registru jurnal for {months} has no match")


def make_pre_check(
    cat: Catalog,
    witnesses: Callable[[JobRecord], Witnesses],
    *,
    store: ReconStore | None = None,
    allow_draft: bool = True,
) -> Callable[..., PreResult]:
    """The ``IngestDeps.pre_check`` function: profile → det_match → stored verdict.

    ``witnesses`` is called on every check, so a fresh export is read after a person
    supplies it.
    """
    for row in cat.articole.values():
        if row.get("graph_id") == GRAPH_ID and row.get("stage") == "pre":
            check_profile(cat.recon_profiles[row["profile_id"]])

    def pre_check(
        job: JobRecord,
        doc: CanonicalDocument,
        *,
        fiscal_class: str | None = None,
        axes: dict[str, str] | None = None,
    ) -> PreResult:
        profile = pre_profile(
            cat, doc, fiscal_class=fiscal_class, axes=axes or {}, allow_draft=allow_draft
        )
        if profile is None:  # nothing was read from the books: not a stored verdict
            return PreResult(
                verdict="ambiguous",
                reason="no single PRE articol for this document",
                profile_id=None,
                snapshot_id="no-profile",
            )
        out = det_match(profile, job, doc, witnesses(job))
        return store.put_once(job.job_id, "pre", out) if store is not None else out

    return pre_check
