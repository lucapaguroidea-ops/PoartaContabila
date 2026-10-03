"""Coverage map (WP-69): every catalog row a document or a month can reach × what drives it.

Two directions in one report:

- **catalog → data.** Each row of the catalog a document or a month can reach (articole de
  cale, source docs, job kinds, HITL kinds with their actor, controls as PASS and as FAIL,
  recon profiles, write modules, filings, close kinds), with the scenarios (WP-71) whose
  expected path names it and the tests that name it. A row counts as covered only when a
  *passing* scenario's expected path names it; a test naming it is shown, never counted.
  A reachable row no scenario covers is a scenario to write. A row out of reach is listed
  with its status and why (:data:`OUT_OF_REACH`): a parked WP, an open decision, no code
  path yet, a control not computed in v1, or a path only a live model opens.
- **data → catalog.** What scenario runs actually landed on that the catalog does not
  foresee: a ``define_articol`` / ``define_class`` / ``define_module`` question, a job at
  ``needs_human`` with no articol, a job minted that never binds one, an upload refused at
  the door, and a close blocker no control explains.

:data:`OUT_OF_REACH` is written by hand against the code; it is checked both ways: a key that
names no catalog row, or a row a passing scenario reaches although it is listed out of reach,
is a problem (exit code 1), so the table cannot go stale silently.

    uv run python -m poarta_contabila.coverage [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from poarta_contabila.catalog import Catalog, load_catalog

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = ROOT / "tests"

Table = Literal[
    "articol",
    "source_doc",
    "job_kind",
    "hitl",
    "control",
    "recon_profile",
    "write_module",
    "filing",
    "close_kind",
]
TABLES: tuple[Table, ...] = (
    "articol",
    "source_doc",
    "job_kind",
    "hitl",
    "control",
    "recon_profile",
    "write_module",
    "filing",
    "close_kind",
)
TITLES = {
    "articol": "articole de cale",
    "source_doc": "source documents",
    "job_kind": "job kinds",
    "hitl": "HITL kinds",
    "control": "controls (PASS and FAIL)",
    "recon_profile": "recon profiles",
    "write_module": "write modules",
    "filing": "filings",
    "close_kind": "close kinds",
}
CONTROL_OUTCOMES = ("PASS", "FAIL")
DEFINE_KINDS = ("define_articol", "define_class", "define_module")

ReachKind = Literal["parked", "decision", "no_code_path", "not_computed", "live_only"]


@dataclass(frozen=True)
class Reach:
    """Why a row is out of reach of every document and month today."""

    kind: ReachKind
    ref: str | None
    note: str


def control_key(control_id: str, outcome: str) -> str:
    """A control's coverage key: it is covered once passing and once failing."""
    if outcome not in CONTROL_OUTCOMES:
        raise ValueError(f"a control is covered as PASS or FAIL, not {outcome!r}")
    return f"{control_id}:{outcome}"


_BON = Reach("parked", "WP-14", "bonuri walk through ArticolBon / bon_via_nota, parked in v1")
_FOREIGN = Reach(
    "no_code_path",
    None,
    "no foreign-invoice extract or upload route: a decont part mints job_foreign_invoice, "
    "whose thread never starts; an XML from abroad is read as RO e-Factura",
)
_TRIAGE = Reach(
    "no_code_path",
    None,
    "folder_triage gates on ArticoleSourceDoc and never binds a folder_triage articol",
)
_NO_MOUTH = Reach(
    "no_code_path",
    None,
    "no rendered SAGA mouth: tags only from a successful copy-firm import (AGENTS)",
)
_NOT_ASKED = "no graph node asks it"
_PREFILE_FAIL = Reach(
    "no_code_path",
    None,
    "package runs only after an absent PRE verdict: defence in depth no path reaches",
)

OUT_OF_REACH: dict[tuple[Table, str], Reach] = {
    # ----- articole de cale -----
    ("articol", "triage_place"): _TRIAGE,
    ("articol", "triage_pair_efactura"): _TRIAGE,
    ("articol", "triage_bon_fork"): _TRIAGE,
    ("articol", "triage_extras"): _TRIAGE,
    ("articol", "foreign_invoice_inbound"): _FOREIGN,
    ("articol", "foreign_invoice_outbound"): _FOREIGN,
    ("articol", "foreign_rc_neplatitor"): Reach(
        "decision", "WP-D3", "4423 vs 446x open; always-HITL, and no foreign-invoice path"
    ),
    ("articol", "bon_cu_cui"): _BON,
    ("articol", "bon_fara_cui"): _BON,
    ("articol", "recon_pre_bon"): _BON,
    ("articol", "recon_post_bon"): _BON,
    # ----- source documents -----
    ("source_doc", "extras"): Reach(
        "no_code_path", None, "statements arrive as PDF only (extras_statement_pdf, WP-13)"
    ),
    ("source_doc", "extras_pdf"): Reach(
        "no_code_path", None, "superseded by extras_statement_pdf (WP-13); no route mints it"
    ),
    ("source_doc", "instructions"): Reach("no_code_path", None, "no upload route"),
    ("source_doc", "recon_vendor"): Reach("no_code_path", None, "no upload route"),
    ("source_doc", "stat_salarii"): Reach(
        "no_code_path", None, "no upload route; payroll is explained_sink_only (POST /rules)"
    ),
    ("source_doc", "unknown"): Reach(
        "no_code_path", None, "every route names its source doc; none mints 'unknown'"
    ),
    # ----- job kinds -----
    ("job_kind", "job_extras"): Reach(
        "no_code_path", None, "statement packs are line jobs (job_extras_line, WP-13)"
    ),
    # ----- HITL kinds -----
    ("hitl", "which_cui"): Reach("no_code_path", None, _NOT_ASKED),
    ("hitl", "name_ambiguous"): Reach("no_code_path", None, _NOT_ASKED),
    ("hitl", "stmt_no_identity"): Reach(
        "no_code_path", None, "a statement without the tenant's CUI is refused, not asked"
    ),
    ("hitl", "xml_pdf_pair"): Reach("no_code_path", None, _NOT_ASKED),
    ("hitl", "bon_cui_unclear"): Reach(
        "no_code_path", None, "decont_split must say whether our CUI is on a receipt part"
    ),
    ("hitl", "define_class"): Reach(
        "no_code_path", None, "asked only for source doc 'unknown', which no route mints"
    ),
    ("hitl", "define_articol"): Reach(
        "no_code_path", None, "every route's source doc binds exactly one articol de cale"
    ),
    ("hitl", "define_module"): Reach("no_code_path", None, _NOT_ASKED),
    ("hitl", "articol_bon"): _BON,
    ("hitl", "no_counterparty"): _FOREIGN,
    ("hitl", "request_devalidare"): Reach("no_code_path", None, _NOT_ASKED),
    ("hitl", "recon_review_contest"): Reach(
        "live_only", "WP-74", "MODEL_CALLS=dry: llm_review abstains, so nothing is contested"
    ),
    ("hitl", "patch_maps"): Reach(
        "no_code_path", None, "v2_close's patch_maps action holds the month; Lane A maps not built"
    ),
    ("hitl", "codit_combo"): Reach(
        "no_code_path", None, "a CO.DiT soft flag names it; no node asks it"
    ),
    ("hitl", "codit_premise"): Reach(
        "no_code_path", None, "a CO.DiT soft flag names it; no node asks it"
    ),
    ("hitl", "decision_menu"): Reach("no_code_path", None, _NOT_ASKED),
    ("hitl", "control_disposition"): Reach(
        "no_code_path", None, "the answer's checker exists (WP-09); no node asks it"
    ),
    # ----- controls -----
    ("control", control_key("M1_8_4428_open", "PASS")): Reach(
        "not_computed", None, "not computed in v1: fails closed whenever it applies"
    ),
    ("control", control_key("M1_9_4424_watched", "PASS")): Reach(
        "not_computed", None, "advisory, not computed in v1: INFO only"
    ),
    ("control", control_key("M1_9_4424_watched", "FAIL")): Reach(
        "not_computed", None, "advisory, not computed in v1: INFO only"
    ),
    ("control", control_key("P_prefile_duplicate", "FAIL")): _PREFILE_FAIL,
    ("control", control_key("P_prefile_hard_failures", "FAIL")): _PREFILE_FAIL,
    # ----- recon profiles -----
    ("recon_profile", "pre_bon_date_gross"): _BON,
    ("recon_profile", "post_bon_how"): _BON,
    # ----- write modules -----
    ("write_module", "parteneri_xml"): _NO_MOUTH,
    ("write_module", "articole_xml"): _NO_MOUTH,
    ("write_module", "storno_intrare_xml"): _NO_MOUTH,
    ("write_module", "storno_iesire_xml"): _NO_MOUTH,
    ("write_module", "nota_nc_dbf"): Reach(
        "decision", "WP-D3", "its accounts wait on WP-D3; no DBF renderer"
    ),
    ("write_module", "bon_via_nota"): _BON,
}


# ----- what a scenario run reports (WP-71 produces these) -----


@dataclass(frozen=True)
class DocActual:
    """What happened to one document of a scenario."""

    ref: str  # the scenario's name for the document
    status: str | None  # its job's final status; None = refused, no job
    articol_id: str | None = None
    asked: tuple[str, ...] = ()  # HITL kinds, in order
    error: str | None = None


@dataclass(frozen=True)
class MonthActual:
    """What a month's close showed."""

    period: str
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioOutcome:
    """A scenario run: did it pass, what its expected path names, and what actually happened."""

    name: str
    passed: bool
    names: frozenset[tuple[Table, str]] = frozenset()
    documents: tuple[DocActual, ...] = ()
    months: tuple[MonthActual, ...] = ()


@dataclass(frozen=True)
class Finding:
    """data → catalog: an outcome the catalog does not foresee."""

    kind: Literal[
        "define_articol",
        "define_class",
        "define_module",
        "needs_human_no_articol",
        "no_articol",
        "refused",
        "unexplained_blocker",
    ]
    scenario: str
    subject: str
    detail: str


# ----- the map -----


@dataclass
class MapRow:
    table: Table
    key: str  # the row id, or ``control_id:PASS|FAIL``
    status: str
    detail: str
    reach: Reach | None  # None = reachable
    tests: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)

    @property
    def covered(self) -> bool:
        return bool(self.scenarios)


@dataclass
class CoverageMap:
    rows: list[MapRow]
    findings: list[Finding]
    problems: list[str]
    scenarios: list[str]

    def table(self, table: Table) -> list[MapRow]:
        return [r for r in self.rows if r.table == table]

    def to_scenario(self) -> list[MapRow]:
        """Reachable rows no passing scenario names: the scenarios to write."""
        return [r for r in self.rows if r.reach is None and not r.covered]

    def summary(self) -> dict[str, dict[str, int]]:
        out = {}
        for t in TABLES:
            rows = self.table(t)
            out[t] = {
                "rows": len(rows),
                "covered": sum(1 for r in rows if r.covered),
                "to_write": sum(1 for r in rows if r.reach is None and not r.covered),
                "out_of_reach": sum(1 for r in rows if r.reach is not None),
                "named_in_a_test": sum(1 for r in rows if r.tests),
            }
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary(),
            "scenarios": self.scenarios,
            "rows": [
                {**asdict(r), "covered": r.covered, "reach": asdict(r.reach) if r.reach else None}
                for r in self.rows
            ],
            "findings": [asdict(f) for f in self.findings],
            "problems": self.problems,
        }


def _status(row: Any) -> str:
    if isinstance(row, dict):
        return str(row.get("status") or "-")
    return str(getattr(row, "status", "-") or "-")


def catalog_rows(cat: Catalog) -> list[MapRow]:
    """Every row of the catalog a document or a month can reach, each with its key."""
    rows: list[MapRow] = []

    def add(table: Table, key: str, row: Any, detail: str) -> None:
        rows.append(MapRow(table, key, _status(row), detail, OUT_OF_REACH.get((table, key))))

    for aid, a in cat.articole.items():
        add("articol", aid, a, a.get("graph_id", "?"))
    for sid, s in cat.source_docs.items():
        add("source_doc", sid, s, s.get("fiscal_class", "?"))
    for jk, j in cat.jobs.items():
        add("job_kind", jk, j, ",".join(j.get("source_doc_ids") or []))
    for kind, h in cat.hitl.items():
        add("hitl", kind, h, f"{h.get('actor', '?')} @ {','.join(h.get('graph_ids') or [])}")
    for cid, c in cat.controls.items():
        for outcome in CONTROL_OUTCOMES:
            add("control", control_key(cid, outcome), c, f"{c.get('severity')} {c.get('layer')}")
    for pid, p in cat.recon_profiles.items():
        add("recon_profile", pid, p, ",".join(p.get("match_keys") or []))
    for mid, m in cat.write_modules.items():
        add("write_module", mid, m, m.saga_path)
    for fid, f in cat.filings.items():
        add("filing", fid, f, str(f.get("form", "?")))
    for ck, c in cat.close_kinds.items():
        add("close_kind", ck, c, str(c.get("articol_id", "?")))
    return rows


def tests_naming(ids: Iterable[str], tests_dir: Path = TESTS_DIR) -> dict[str, list[str]]:
    """For each id, the test files that name it as a quoted string."""
    texts = {p.name: p.read_text(encoding="utf-8") for p in sorted(tests_dir.glob("*.py"))}
    out = {}
    for i in ids:
        pattern = re.compile(r"[\"']" + re.escape(i) + r"[\"']")
        out[i] = [name for name, text in texts.items() if pattern.search(text)]
    return out


def findings(cat: Catalog, outcomes: Iterable[ScenarioOutcome]) -> list[Finding]:
    """data → catalog: what each run landed on that no catalog row foresees."""
    controls = set(cat.controls)
    out: list[Finding] = []
    for o in outcomes:
        for d in o.documents:
            for kind in d.asked:
                if kind in DEFINE_KINDS:
                    out.append(Finding(kind, o.name, d.ref, f"asked {kind}"))
            if d.status is None:
                out.append(Finding("refused", o.name, d.ref, d.error or "refused"))
            elif d.articol_id is None and d.status == "needs_human":
                out.append(Finding("needs_human_no_articol", o.name, d.ref, d.error or ""))
            elif d.articol_id is None and d.status != "rejected":
                out.append(Finding("no_articol", o.name, d.ref, f"job {d.status}, never bound"))
        for m in o.months:
            for b in m.blockers:
                head = re.split(r"[:\s]", b, maxsplit=1)[0]
                if head not in controls:
                    out.append(Finding("unexplained_blocker", o.name, m.period, b))
    return out


def build_map(
    cat: Catalog,
    outcomes: Iterable[ScenarioOutcome] = (),
    *,
    tests_dir: Path = TESTS_DIR,
) -> CoverageMap:
    """The coverage map of *cat* against scenario *outcomes* and the tests in *tests_dir*."""
    outcomes = list(outcomes)
    rows = catalog_rows(cat)
    by_key = {(r.table, r.key): r for r in rows}
    problems = [
        f"OUT_OF_REACH names {t} {k!r}, which is not a catalog row"
        for t, k in OUT_OF_REACH
        if (t, k) not in by_key
    ]
    named = tests_naming({r.key.split(":")[0] for r in rows}, tests_dir)
    for r in rows:
        r.tests = named[r.key.split(":")[0]]
    for o in outcomes:
        for t, k in sorted(o.names):
            row = by_key.get((t, k))
            if row is None:
                problems.append(f"scenario {o.name} names {t} {k!r}, which is not a catalog row")
            elif o.passed:
                row.scenarios.append(o.name)
    for r in rows:
        if r.reach is not None and r.covered:
            problems.append(
                f"{r.table} {r.key} is listed out of reach ({r.reach.kind}) but "
                f"{', '.join(r.scenarios)} reaches it: update OUT_OF_REACH"
            )
    return CoverageMap(
        rows=rows,
        findings=findings(cat, outcomes),
        problems=problems,
        scenarios=[f"{o.name} ({'pass' if o.passed else 'FAIL'})" for o in outcomes],
    )


# ----- report -----


def render(cmap: CoverageMap) -> str:
    lines = ["Coverage map (WP-69)", ""]
    if cmap.scenarios:
        lines.append(f"scenarios run: {len(cmap.scenarios)}")
        lines += [f"  {s}" for s in cmap.scenarios]
    else:
        lines.append("scenarios run: none")
    lines += ["", "catalog → data", ""]
    summary = cmap.summary()
    for t in TABLES:
        s = summary[t]
        lines.append(
            f"{TITLES[t]}: {s['rows']} rows — {s['covered']} covered by a scenario, "
            f"{s['to_write']} reachable with none (to write), {s['out_of_reach']} out of reach; "
            f"{s['named_in_a_test']} named in a test"
        )
        for r in cmap.table(t):
            if r.reach is not None:
                continue
            mark = "ok " if r.covered else "-- "
            where = ", ".join(r.scenarios) if r.covered else "no scenario"
            tests = f"; tests: {len(r.tests)}" if r.tests else ""
            lines.append(f"  {mark}{r.key:<34} {r.status:<6} {r.detail:<30} {where}{tests}")
        out = [r for r in cmap.table(t) if r.reach is not None]
        if out:
            lines.append("  out of reach:")
        for r in out:
            reach = r.reach
            ref = f" {reach.ref}" if reach.ref else ""
            lines.append(f"     {r.key:<34} {r.status:<6} {reach.kind}{ref}: {reach.note}")
        lines.append("")
    lines += ["data → catalog", ""]
    if not cmap.findings:
        lines.append("  nothing the catalog does not foresee" if cmap.scenarios else "  no run")
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in cmap.findings:
        groups.setdefault((f.kind, _shape(f.detail)), []).append(f)
    for (kind, shape), fs in sorted(groups.items()):
        where = sorted({f"{f.scenario}:{f.subject}" for f in fs})
        lines.append(
            f"  {kind}: {shape} ({len(fs)}×: {', '.join(where[:4])}"
            + (" …" if len(where) > 4 else "")
            + ")"
        )
    if cmap.problems:
        lines += ["", "problems:"] + [f"  - {p}" for p in cmap.problems]
    return "\n".join(lines)


def _shape(detail: str) -> str:
    """A finding's detail with numbers and ids blanked, so alike findings group together."""
    return re.sub(r"\d+(?:[.,]\d+)?", "#", detail)[:160]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="poarta_contabila.coverage", description=__doc__.split("\n")[0]
    )
    ap.add_argument("--json", action="store_true", help="print the map as JSON")
    args = ap.parse_args(argv)
    cmap = build_map(load_catalog())
    if args.json:
        print(json.dumps(cmap.as_dict(), indent=2, ensure_ascii=False))
    else:
        print(render(cmap))
    return 1 if cmap.problems else 0


if __name__ == "__main__":
    sys.exit(main())
