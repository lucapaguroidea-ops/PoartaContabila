"""The surface: every row the system has, plans or will need, in one of four states.

``possible``  named, not yet on a path we run
``synthetic`` a passing scenario drives it (the coverage map)
``saga``      it went round-trip through a SAGA C test firm and matched: a loop's evidence
``out``       the owner decided it will not be built; the reason is written

Rows are the catalog's (as :mod:`poarta_contabila.coverage` names them: ``table:key``) and the
rows not yet in the catalog (``surface/possible.yaml``). States come from, in order:

1. ``surface/evidence/*.yaml`` — one file per loop and SAGA test firm; a row it names is
   **saga** (BUILD.md B3, steps 9–10). Evidence is checked: invented firm, known rows, files
   that exist, the owner's approval.
2. ``surface/out.yaml`` — the owner's decisions; a row named there is **out**.
3. the coverage map — a catalog row a passing scenario names is **synthetic**.
4. otherwise **possible**, with why: out of reach (:data:`coverage.OUT_OF_REACH`), no scenario
   yet, or not in the catalog yet.

``SURFACE.md`` is generated from this; ``tests/test_scenarios.py`` fails when it is stale.
LAW L42: a catalog row whose status is ``active`` must be **saga**, or the map has a problem.

    uv run python -m poarta_contabila.surface [--write] [--no-run]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from poarta_contabila.catalog import Catalog, load_catalog
from poarta_contabila.coverage import TABLES, TITLES, CoverageMap, ScenarioOutcome, build_map
from poarta_contabila.types import cui_is_valid

ROOT = Path(__file__).resolve().parents[1]
SURFACE_DIR = ROOT / "surface"
SURFACE_MD = ROOT / "SURFACE.md"

State = Literal["possible", "synthetic", "saga", "out"]
STATES: tuple[State, ...] = ("possible", "synthetic", "saga", "out")
POSSIBLE_KINDS = {
    "articol",
    "source_doc",
    "job_kind",
    "hitl",
    "control",
    "recon_profile",
    "mouth",
    "eye",
    "filing",
    "close_kind",
    "workflow",
}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class SurfaceError(ValueError):
    """The surface data does not hold together."""


@dataclass(frozen=True)
class PossibleRow:
    id: str
    area: str
    kind: str
    what: str
    source: str


@dataclass(frozen=True)
class OutRow:
    ref: str  # "table:key" of a catalog row, or a possible row's id
    reason: str
    decided: str  # "owner, YYYY-MM-DD"


@dataclass(frozen=True)
class Evidence:
    file: str
    loop: int
    date: str
    firm_cui: str
    saga_build: str
    approved: str  # "owner, YYYY-MM-DD"
    rows: tuple[str, ...]  # "table:key"
    exports: tuple[str, ...]  # repo paths of the SAGA exports the loop read


@dataclass
class SurfaceData:
    possible: list[PossibleRow]
    out: list[OutRow]
    evidence: list[Evidence]


@dataclass
class SurfaceRow:
    ref: str  # "table:key" or a possible row's id
    table: str  # a coverage table, or "possible"
    state: State
    why: str
    status: str = "-"  # the catalog row's status


@dataclass
class Surface:
    rows: list[SurfaceRow]
    possible: list[PossibleRow]
    problems: list[str]

    def counts(self) -> dict[str, Counter]:
        out: dict[str, Counter] = {}
        for r in self.rows:
            out.setdefault(r.table, Counter())[r.state] += 1
        return out

    def state(self, ref: str) -> State:
        return next(r.state for r in self.rows if r.ref == ref)


# ----- the data -----


def _decided(value: object, where: str) -> str:
    text = str(value or "")
    if not re.fullmatch(r"owner, \d{4}-\d{2}-\d{2}", text):
        raise SurfaceError(f"{where}: needs 'owner, YYYY-MM-DD', got {text!r}")
    return text


def load_data(root: Path = SURFACE_DIR) -> SurfaceData:
    """``surface/possible.yaml``, ``surface/out.yaml`` and ``surface/evidence/*.yaml``, checked."""
    raw = yaml.safe_load((root / "possible.yaml").read_text(encoding="utf-8")) or {}
    possible = []
    for r in raw.get("rows") or []:
        if set(r) != {"id", "area", "kind", "what", "source"}:
            raise SurfaceError(f"possible row {r.get('id')!r}: keys {sorted(r)}")
        if r["kind"] not in POSSIBLE_KINDS:
            raise SurfaceError(f"possible row {r['id']}: kind {r['kind']!r}")
        possible.append(PossibleRow(**{k: str(v) for k, v in r.items()}))
    dup = [i for i, n in Counter(p.id for p in possible).items() if n > 1]
    if dup:
        raise SurfaceError(f"possible ids twice: {dup}")

    raw = yaml.safe_load((root / "out.yaml").read_text(encoding="utf-8")) or {}
    out = []
    for r in raw.get("rows") or []:
        if set(r) != {"ref", "reason", "decided"} or not str(r["reason"]).strip():
            raise SurfaceError(f"out row {r.get('ref')!r}: needs ref, reason, decided")
        out.append(OutRow(str(r["ref"]), str(r["reason"]), _decided(r["decided"], r["ref"])))

    evidence = []
    for f in sorted((root / "evidence").glob("*.yaml")):
        e = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        keys = {"loop", "date", "firm_cui", "saga_build", "approved", "rows", "exports"}
        if set(e) != keys:
            raise SurfaceError(f"{f.name}: keys {sorted(e)}, want {sorted(keys)}")
        if not DATE_RE.match(str(e["date"])):
            raise SurfaceError(f"{f.name}: date {e['date']!r}")
        if not cui_is_valid(str(e["firm_cui"])):
            raise SurfaceError(f"{f.name}: firm_cui {e['firm_cui']!r} is not a valid CUI")
        if not e["rows"] or not e["exports"]:
            raise SurfaceError(f"{f.name}: names no row or no export")
        for p in e["exports"]:
            if not (ROOT / p).is_file():
                raise SurfaceError(f"{f.name}: export {p} is not in the repo")
        evidence.append(
            Evidence(
                f.name,
                int(e["loop"]),
                str(e["date"]),
                str(e["firm_cui"]),
                str(e["saga_build"]),
                _decided(e["approved"], f.name),
                tuple(str(x) for x in e["rows"]),
                tuple(str(x) for x in e["exports"]),
            )
        )
    return SurfaceData(possible, out, evidence)


# ----- the states -----


def build_surface(cmap: CoverageMap, data: SurfaceData) -> Surface:
    """Every catalog row of *cmap* and every possible row of *data*, each with its state."""
    problems: list[str] = []
    catalog_refs = {f"{r.table}:{r.key}": r for r in cmap.rows}
    possible_ids = {p.id for p in data.possible}
    known = set(catalog_refs) | possible_ids

    saga: dict[str, list[str]] = {}
    for e in data.evidence:
        for ref in e.rows:
            if ref not in catalog_refs:
                problems.append(f"{e.file} names {ref!r}, which is not a catalog row")
            saga.setdefault(ref, []).append(f"loop {e.loop}, {e.date}, {e.file}")
    out = {o.ref: o for o in data.out}
    for ref in out:
        if ref not in known:
            problems.append(f"surface/out.yaml names {ref!r}, which is not a row")
        if ref in saga:
            problems.append(f"{ref} is both out and proven in SAGA")
        if ref in possible_ids and ref in catalog_refs:
            problems.append(f"{ref} is both a catalog row and a possible row")

    rows: list[SurfaceRow] = []
    for ref, r in catalog_refs.items():
        if ref in saga:
            state, why = "saga", "; ".join(saga[ref])
        elif ref in out:
            state, why = "out", f"{out[ref].reason} ({out[ref].decided})"
        elif r.covered:
            state, why = "synthetic", ", ".join(r.scenarios)
        elif r.reach is not None:
            ref_ = f" {r.reach.ref}" if r.reach.ref else ""
            state, why = "possible", f"{r.reach.kind}{ref_}: {r.reach.note}"
        else:
            state, why = "possible", "reachable, no scenario yet"
        if r.status == "active" and state != "saga":
            problems.append(f"{ref} is active but not proven in SAGA C (LAW L42)")
        rows.append(SurfaceRow(ref, r.table, state, why, r.status))
    for p in data.possible:
        if p.id in out:
            rows.append(SurfaceRow(p.id, "possible", "out", f"{out[p.id].reason}"))
        else:
            rows.append(SurfaceRow(p.id, "possible", "possible", "not in the catalog yet"))
    return Surface(rows, data.possible, problems + cmap.problems)


def surface(
    outcomes: Iterable[ScenarioOutcome] = (),
    *,
    cat: Catalog | None = None,
    root: Path = SURFACE_DIR,
) -> Surface:
    return build_surface(build_map(cat or load_catalog(), outcomes), load_data(root))


# ----- SURFACE.md -----

INTRO = """\
# Surface — the articol map: possible, synthetic, saga, out

**Generated** by `uv run python -m poarta_contabila.surface --write` from the catalog, the
scenario runs and `surface/` (`possible.yaml`, `out.yaml`, `evidence/`). Do not edit by hand:
edit those files, then regenerate; `tests/test_scenarios.py` fails while this file is stale.

The surface is everything the system has, plans, or will need: articole de cale, source
documents, job kinds, HITL kinds, controls (each as PASS and as FAIL), recon profiles, SAGA
mouths, filings, close kinds, and the rows not yet in the catalog (eyes, workflows, …). Each row
has one state (`BUILD.md` B2):

| State | Means | Set by |
|---|---|---|
| **possible** | named, not yet on a path we run | default; the reason is shown |
| **synthetic** | a passing scenario drives it | `fixtures/scenarios/` through the coverage map |
| **saga** | round-trip through a SAGA C test firm, matched | `surface/evidence/` (owner-approved) |
| **out** | will not be built | `surface/out.yaml` (the owner's decision and reason) |

The program ends when every row is **saga** or **out** (`BUILD.md` B1). A catalog row becomes
`active` only once it is **saga** and the owner approves (LAW L42).

Two rules for the rows not yet in the catalog (§3): **this system keeps no books** (L7), so an
item about posting, a journal or a trial balance enters only as an eye or a control; and **a
legal value is research, not a row** (L40): named, never stated. Their `source` names the item in
the practice harvest (branch `pre-tidy`, `docs/harvest/`; `hWP-…` are its work packages, not
ours). A loop takes rows into the catalog as `draft` (`BUILD.md` B3, step 8) and removes them
from `surface/possible.yaml`; a nuance found during a loop is added there (B4, rule 2).
"""

OUTRO = """\
## 4. Scenario specs not yet in `fixtures/scenarios/`

The harvest's synthetic specs G-01 … G-28 (invented numbers; branch `pre-tidy`,
`docs/harvest/CATALOGUES.md` §G) are the first source for each slice's scenarios. Each loop
translates the specs of its slice into scenario YAML as eye and control checks, not postings.
"""


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _short(r: SurfaceRow) -> str:
    """A synthetic row's scenarios, at most three named."""
    if r.state != "synthetic":
        return r.why
    names = r.why.split(", ")
    more = f" and {len(names) - 3} more" if len(names) > 3 else ""
    return f"{len(names)} scenario{'s' * (len(names) > 1)}: {', '.join(names[:3])}{more}"


def render_markdown(s: Surface) -> str:
    counts = s.counts()
    lines = [INTRO, "## 1. Summary", ""]
    lines += [
        "| Rows | " + " | ".join(STATES) + " | total |",
        "|---|" + "---:|" * (len(STATES) + 1),
    ]
    for t in [*TABLES, "possible"]:
        c = counts.get(t, Counter())
        title = TITLES.get(t, "not in the catalog yet")
        lines.append(
            f"| {title} | " + " | ".join(str(c[st]) for st in STATES) + f" | {sum(c.values())} |"
        )
    total = Counter()
    for c in counts.values():
        total.update(c)
    lines.append(
        "| **all** | "
        + " | ".join(f"**{total[st]}**" for st in STATES)
        + f" | **{sum(total.values())}** |"
    )
    if s.problems:
        lines += ["", "**Problems:**", ""] + [f"- {p}" for p in s.problems]
    lines += ["", "## 2. In the catalog", ""]
    for t in TABLES:
        rows = [r for r in s.rows if r.table == t]
        lines += [
            f"### {TITLES[t]}",
            "",
            "| Row | Status | State | Where / why |",
            "|---|---|---|---|",
        ]
        order = {st: i for i, st in enumerate(("saga", "synthetic", "possible", "out"))}
        for r in sorted(rows, key=lambda r: (order[r.state], r.ref)):
            key = r.ref.split(":", 1)[1]
            lines.append(f"| `{key}` | {r.status} | {r.state} | {_cell(_short(r))} |")
        lines.append("")
    lines += ["## 3. Not in the catalog yet", ""]
    state_of = {r.ref: r for r in s.rows if r.table == "possible"}
    areas: dict[str, list[PossibleRow]] = {}
    for p in s.possible:
        areas.setdefault(p.area, []).append(p)
    for area, ps in areas.items():
        lines += [f"### {area[0].upper()}{area[1:]}", "", "| Id | Kind | What | State | Source |"]
        lines.append("|---|---|---|---|---|")
        for p in ps:
            st = state_of[p.id]
            lines.append(
                f"| {p.id} | {p.kind} | {_cell(p.what)} | {st.state} | {_cell(p.source)} |"
            )
        lines.append("")
    lines.append(OUTRO)
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="poarta_contabila.surface", description=__doc__.split("\n")[0]
    )
    ap.add_argument("--write", action="store_true", help="write SURFACE.md instead of printing it")
    ap.add_argument("--no-run", action="store_true", help="do not run the scenarios")
    args = ap.parse_args(argv)
    outcomes = []
    if not args.no_run:
        from poarta_contabila.scenarios import run_all

        outcomes = [r.outcome() for r in run_all()]
    s = surface(outcomes)
    text = render_markdown(s)
    if args.write:
        SURFACE_MD.write_text(text, encoding="utf-8")
        print(f"wrote {SURFACE_MD.name}: {len(s.rows)} rows, {len(s.problems)} problems")
    else:
        print(text)
    return 1 if s.problems else 0


if __name__ == "__main__":
    sys.exit(main())
