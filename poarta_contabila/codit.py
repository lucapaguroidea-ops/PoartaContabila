"""CO.DiT: a firm's tax profile for one period — a period document, not a sticky flag.

Write order (ARCHITECTURE §7): defaults → T* → F* → F7 / A* → derive().

- **Defaults** fill an *omitted* ``exig`` only (payer → ``tva_exig_livrare``, else none);
  a value the writer set is never wiped, so T1 can refuse it.
- **Hard pairs** (T1–T3, then F5 F6 F1 F2 F4 F3) raise :class:`CoditError`; nothing is saved.
- **Soft pairs** (F7.*, A*) are saved as flags with their HITL kind; ``blocks_file`` ones
  block V2 filing. ``A_FLIP`` (an axis changed inside an open period) and ``A_CONTESTED``
  flag a premise for a person.
- Every axis a writer sets carries ``certainty`` (+ ``as_of``, ``source``). An empty profile
  is never ``tva_platitor``: missing axes stay missing, and what reads them fails closed.
- Seeding copies the year's pins (law facts) onto the document; later pins never touch it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field

from poarta_contabila.catalog import Catalog
from poarta_contabila.types import Closed, Cui, FiscalDate, Period

Certainty = Literal["confirmed", "de_confirmat", "contested"]
_PAIRS_ORDER_T = ("T1", "T2", "T3")
_DEFAULT_SOURCE = "default from tva"
_PAIRS_ORDER_F = ("F5", "F6", "F1", "F2", "F4", "F3")


class CoditError(ValueError):
    """A hard pair failed (``ValidationError`` in the catalog). The document is not saved."""

    def __init__(self, pair_id: str, code: str, fix: str | None) -> None:
        super().__init__(f"{pair_id} {code}" + (f": {fix}" if fix else ""))
        self.pair_id, self.code, self.fix = pair_id, code, fix


class AxisValue(Closed):
    value: str | None
    certainty: Certainty
    as_of: FiscalDate | None = None
    source: str | None = None


class CoditInput(Closed):
    """What a person writes for a period. Axes not given are not set."""

    axes: dict[str, AxisValue] = Field(default_factory=dict)
    parent_cui: Cui | None = None
    saf_t: bool | None = None
    auto: str | None = None
    vehicle_count: int | None = None


class SoftFlag(Closed):
    pair_id: str
    code: str
    hitl: str
    blocks_file: bool


class Codit(Closed):
    cui: Cui
    period: Period
    axes: dict[str, AxisValue]
    parent_cui: Cui | None = None
    saf_t: bool | None = None
    auto: str | None = None
    vehicle_count: int | None = None
    pins: dict[str, Any] | None = None
    soft: list[SoftFlag] = Field(default_factory=list)
    hash: str = ""

    def derive(self) -> dict[str, str]:
        """Axis values for flux / close / controls; unset axes are absent (never guessed)."""
        return {k: v.value for k, v in sorted(self.axes.items()) if v.value is not None}

    @property
    def blocks_file(self) -> list[str]:
        return [f"{f.pair_id} {f.code}" for f in self.soft if f.blocks_file]


# ----- rules engine -----


def _allowed(cat: Catalog) -> dict[str, list]:
    doc = cat.docs["ArticoleCoDitAxes"]
    out = {k: list(v) for k, v in doc["existing_axes"].items()}
    out.update({k: list(v["values"]) for k, v in doc["new_axes"].items()})
    return out


def _field(doc: dict[str, Any], name: str) -> Any:
    if name == "vehicle.count":
        return doc.get("vehicle_count")
    return doc.get(name)


def _holds(cond: dict[str, Any], doc: dict[str, Any]) -> bool:
    for key, want in cond.items():
        for suffix, test in (
            ("_not_in", lambda v, w: v not in w),
            ("_in", lambda v, w: v in w),
            ("_ne", lambda v, w: v != w),
        ):
            if key.endswith(suffix):
                if not test(_field(doc, key[: -len(suffix)]), want):
                    return False
                break
        else:
            value = _field(doc, key)
            if want == "missing":
                if value is not None:
                    return False
            elif value != want:
                return False
    return True


def _pairs(cat: Catalog) -> tuple[dict[str, dict], list[dict]]:
    t = {p["id"]: p for p in cat.docs["ArticoleCoDitT"]["hard"]}
    pairs = cat.docs["ArticoleCoDitPairs"]
    hard = {p["id"]: p for p in pairs["hard"]}
    hard.update(t)
    return hard, list(pairs.get("soft") or [])


def _flat(axes: dict[str, AxisValue], extra: dict[str, Any]) -> dict[str, Any]:
    return {**{k: v.value for k, v in axes.items()}, **extra}


def write_codit(
    cat: Catalog,
    cui: str,
    period: str,
    data: CoditInput,
    *,
    previous: Codit | None = None,
    closed: bool = False,
) -> Codit:
    """Run the write pipeline. Raises :class:`CoditError` (hard pair) or ``ValueError``."""
    allowed = _allowed(cat)
    axes = dict(previous.axes) if previous else {}
    for name, av in data.axes.items():
        if name not in allowed:
            raise ValueError(f"unknown CO.DiT axis {name!r}")
        if av.value is not None and av.value not in allowed[name]:
            raise ValueError(f"{name}={av.value!r} is not one of {allowed[name]}")
        axes[name] = av

    # defaults: fill an omitted exig only; one that was itself a default follows a new tva
    if (
        "tva" in data.axes
        and "exig" not in data.axes
        and axes.get("exig") is not None
        and axes["exig"].source == _DEFAULT_SOURCE
    ):
        del axes["exig"]
    tva = axes.get("tva")
    if "exig" not in axes and tva is not None and tva.value is not None:
        axes["exig"] = AxisValue(
            value="tva_exig_livrare" if tva.value == "tva_platitor" else None,
            certainty=tva.certainty,
            as_of=tva.as_of,
            source=_DEFAULT_SOURCE,
        )
    extra = {
        "parent_cui": data.parent_cui
        if data.parent_cui is not None
        else (previous.parent_cui if previous else None),
        "saf_t": data.saf_t if data.saf_t is not None else (previous.saf_t if previous else None),
        "auto": data.auto if data.auto is not None else (previous.auto if previous else None),
        "vehicle_count": data.vehicle_count
        if data.vehicle_count is not None
        else (previous.vehicle_count if previous else None),
    }
    flat = _flat(axes, extra)

    hard, soft = _pairs(cat)
    for pid in (*_PAIRS_ORDER_T, *_PAIRS_ORDER_F):
        pair = hard[pid]
        # T3 applies only once tva is known; an empty profile is not a payer
        if _holds(pair["if"], flat) and _holds(pair.get("and") or {}, flat):
            raise CoditError(pid, pair["code"], pair.get("fix") or pair.get("hitl_repair"))

    flags = [
        SoftFlag(
            pair_id=p["id"],
            code=p["code"],
            hitl=p["hitl"],
            blocks_file=bool(p.get("blocks_file")),
        )
        for p in soft
        if _holds(p["if"], flat)
    ]
    if any(av.certainty == "contested" for av in axes.values()):
        flags.append(
            SoftFlag(
                pair_id="A_CONTESTED",
                code="contested_premise",
                hitl="codit_premise",
                blocks_file=False,
            )
        )
    if previous is not None and not closed:
        changed = [
            k
            for k, av in data.axes.items()
            if k in previous.axes and previous.axes[k].value != av.value
        ]
        if changed:
            flags.append(
                SoftFlag(
                    pair_id="A_FLIP",
                    code="flip:" + ",".join(sorted(changed)),
                    hitl="codit_premise",
                    blocks_file=False,
                )
            )
    doc = Codit(
        cui=cui,
        period=period,
        axes=axes,
        pins=previous.pins if previous else seed_pins(cat, period),
        soft=flags,
        **extra,
    )
    body = doc.model_dump(exclude={"hash"})
    return doc.model_copy(
        update={"hash": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}
    )


def seed_pins(cat: Catalog, period: str) -> dict[str, Any] | None:
    """The year's pins, copied (provenance kept, certainty as the catalog says)."""
    year = int(period[:4])
    for row in (cat.docs.get("ArticolePins") or {}).get("pins") or []:
        if int(row.get("year", 0)) == year:
            return json.loads(json.dumps(row, default=str))
    return None


# ----- store -----


@dataclass
class InMemoryCoditStore:
    rows: dict[tuple[str, str], Codit] = field(default_factory=dict)

    def get(self, cui: str, period: str) -> Codit | None:
        return self.rows.get((cui, period))

    def put(self, doc: Codit) -> None:
        self.rows[(doc.cui, doc.period)] = doc


class PostgresCoditStore:
    """``domain.codit`` (one document per ``(cui, period)``)."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def get(self, cui: str, period: str) -> Codit | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.codit WHERE cui = %s AND period = %s", (cui, period)
            ).fetchone()
        return Codit.model_validate(row[0], strict=False) if row else None

    def put(self, doc: Codit) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.codit (cui, period, body, hash) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT (cui, period) DO UPDATE SET body = EXCLUDED.body,"
                " hash = EXCLUDED.hash",
                (doc.cui, doc.period, doc.model_dump_json(), doc.hash),
            )


# ----- V4 after file  -----


class V4Edit(Closed):
    """What V4 may patch on a filed period (ArticoleClose ``v4.may_patch``)."""

    auto: str | None = None
    saf_t: bool | None = None
    exig: AxisValue | None = None


def next_period(period: str) -> str:
    year, month = int(period[:4]), int(period[5:])
    return f"{year + month // 12:04d}-{month % 12 + 1:02d}"


def v4_rules(cat: Catalog) -> tuple[list[str], list[str]]:
    v4 = cat.docs["ArticoleClose"]["v4"]
    return list(v4["may_patch"]), list(v4["seed_next_period_on"])


def v4_patch(cat: Catalog, doc: Codit, edit: dict[str, Any]) -> Codit:
    """The filed period's CO.DiT with V4's patch: only ``may_patch`` fields, hard pairs run.

    Raises:
        ValueError: a field V4 may not patch; :class:`CoditError` for a hard pair.
    """
    may_patch, _ = v4_rules(cat)
    extra = sorted(set(edit) - set(may_patch))
    if extra:
        raise ValueError(f"V4 may patch only {may_patch}, not {extra}")
    patch = V4Edit.model_validate(edit)
    data = CoditInput(
        axes={"exig": patch.exig} if patch.exig is not None else {},
        saf_t=patch.saf_t,
        auto=patch.auto,
    )
    return write_codit(cat, doc.cui, doc.period, data, previous=doc, closed=True)


def v4_seed(cat: Catalog, doc: Codit, seed: dict[str, Any], existing: Codit | None) -> Codit | None:
    """Next period's CO.DiT, seeded from *doc*.

    The firm's profile carries forward whole (axes, ``parent_cui``, ``saf_t``, ``auto``,
    ``vehicle_count``; pins are the next period's year's). *seed* may change only the
    ``seed_next_period_on`` axes (``{axis: AxisValue}``, ``{}`` = no change); an ``exig`` that
    was itself a default follows a changed ``tva``. Every carried axis is marked
    ``seeded by V4 from <period>``. Returns None when *existing* is already this seed (a
    replay); an existing CO.DiT that is not is never overwritten.

    Raises:
        ValueError: an axis outside ``seed_next_period_on``, or a next period already
            written otherwise; :class:`CoditError` for a hard pair.
    """
    _, seed_on = v4_rules(cat)
    extra = sorted(set(seed) - set(seed_on))
    if extra:
        raise ValueError(f"V4 seeds only {seed_on}, not {extra}")
    source = f"seeded by V4 from {doc.period}"
    axes = {name: av.model_copy(update={"source": source}) for name, av in doc.axes.items()}
    for name, given in seed.items():
        axes[name] = AxisValue.model_validate(given).model_copy(update={"source": source})
    exig = doc.axes.get("exig")
    if "tva" in seed and exig is not None and exig.source == _DEFAULT_SOURCE:
        del axes["exig"]  # write_codit derives it again from the new tva
    nxt = next_period(doc.period)
    data = CoditInput(
        axes=axes,
        parent_cui=doc.parent_cui,
        saf_t=doc.saf_t,
        auto=doc.auto,
        vehicle_count=doc.vehicle_count,
    )
    seeded = write_codit(cat, doc.cui, nxt, data)
    if existing is not None:
        if existing.hash == seeded.hash:
            return None
        raise ValueError(f"{nxt} already has a CO.DiT: V4 does not overwrite it")
    return seeded
