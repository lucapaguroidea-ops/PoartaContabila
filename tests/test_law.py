"""LAW.md holds: every `[test]` rule has a test, and nothing in the repo cites what does not exist.

`LAW_TESTS` names, for each rule marked `[test]` in LAW.md, the tests that enforce it. A rule
marked `[test]` with no entry here, or an entry naming a test that is gone, fails the build.
The citation checks keep the rewrite of 2026-10-04 from rotting: a rule id, a WP id, an
ARCHITECTURE section or a document path that is cited must exist.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from poarta_contabila.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[1]

LAW_TESTS: dict[str, list[str]] = {
    "L4": [
        "test_law.py::test_every_articol_names_a_cale_on_its_graph",
        "test_catalog.py::test_unknown_articol_is_an_error",
    ],
    "L5": [
        "test_catalog.py::test_book_of_record_allows_nextup_as_eye",
        "test_ingest.py::test_a_nextup_tenant_gets_no_prefile",
    ],
    "L7": ["test_domain_schema.py::test_no_books_in_domain"],
    "L9": [
        "test_catalog.py::test_write_module_with_fdb_path_is_refused",
        "test_types.py::test_write_module_cannot_name_fdb_insert",
    ],
    "L10": ["test_law.py::test_no_database_rights_in_the_package"],
    "L12": ["test_agent.py::test_closed_month_gets_nothing"],
    "L13": [
        "test_agent.py::test_agent_cannot_devalidate",
        "test_agent.py::test_cancelled_import_reopens",
    ],
    "L15": ["test_triage.py::test_ubl_label_without_ubl_bytes_does_not_emit"],
    "L21": ["test_law.py::test_no_model_on_a_graph_edge"],
    "L22": [
        "test_domain_schema.py::test_package_written_once",
        "test_agent.py::test_import_moves_to_wait_validare_once",
    ],
    "L23": [
        "test_ingest.py::test_thread_prefix_is_job",
        "test_triage.py::test_graph_thread_prefix_is_batch",
        "test_reconcile.py::test_recon_runs_only_on_its_own_thread",
    ],
    "L24": [
        "test_types.py::test_extra_keys_forbidden",
        "test_types.py::test_money_must_be_two_decimal_string",
        "test_types.py::test_dates_are_iso_strings",
    ],
    "L25": [
        "test_jev.py::test_layer2_cannot_clear_material",
        "test_close.py::test_jev_file_on_a_material_month_is_ignored",
    ],
    "L28": [
        "test_model_roles.py::test_every_model_call_site_has_one_role",
        "test_model_roles.py::test_an_alias_or_auto_model_is_refused",
    ],
    "L29": [
        "test_close.py::test_material_month_cannot_be_filed",
        "test_jev_live.py::test_layer2_suggests_live_and_never_clears_material",
    ],
    "L33": [
        "test_jev_live.py::test_a_client_tenant_is_never_sent",
        "test_sysbuilder.py::test_a_client_tenants_job_is_out_of_reach",
    ],
    "L36": [
        "test_synthetic.py::test_firms_are_invented_and_valid",
        "test_law.py::test_every_iban_in_the_repo_is_invented",
    ],
    "L40": ["test_codit.py::test_every_axis_needs_certainty_and_a_known_value"],
}

OPEN_WPS_RE = re.compile(r"^\| (WP-[\dA-Z]+) \|", re.M)
WP_RE = re.compile(r"(?<![\w-])WP-(?:D\d|\d+[A-Z]?)\b")
LAW_CITE_RE = re.compile(r"\bLAW(?:\.md)?`{0,2} (L\d+(?:(?:, |–| and )L\d+)*)")
BARE_L_RE = re.compile(r"[(\s,–]L(\d{1,2})\b(?![.\d])")
ARCH_RE = re.compile(r"ARCHITECTURE(?:\.md)?`{0,2} §(\d+(?:\.\d+)?)")
MD_PATH_RE = re.compile(r"`((?:docs/(?:owner/)?|catalog/)?[A-Z][A-Z0-9_]+\.md)`")


def _law():
    return (ROOT / "LAW.md").read_text()


def _rule_ids():
    return {int(n) for n in re.findall(r"^- \*\*L(\d+) ·", _law(), re.M)}


def _files():
    out = (
        list(ROOT.glob("*.md"))
        + list((ROOT / "docs").rglob("*.md"))
        + list((ROOT / "catalog").rglob("*.md"))
    )
    for pat in ("poarta_contabila/**/*", "tests/**/*", "catalog/**/*", "fixtures/**/*"):
        for f in ROOT.glob(pat):
            if (
                f.is_file()
                and "__pycache__" not in f.parts
                and f.suffix in {".py", ".sql", ".js", ".html", ".yaml"}
            ):
                out.append(f)
    return sorted(set(out))


# ----- every [test] rule has a test -----


def test_every_test_rule_has_a_test_that_exists():
    marked = {f"L{n}" for n in re.findall(r"\*\*L(\d+) ·(?:(?!\n- \*\*).)*\[test\]", _law(), re.S)}
    assert marked == set(LAW_TESTS), marked ^ set(LAW_TESTS)
    for rule, tests in LAW_TESTS.items():
        for t in tests:
            file, name = t.split("::")
            src = (ROOT / "tests" / file).read_text()
            assert re.search(rf"^def {name}\(", src, re.M), f"{rule}: {t} is gone"


# ----- citations -----


def test_law_ids_cited_exist():
    ids = _rule_ids()
    assert ids == set(range(1, max(ids) + 1))  # no gap: a retired id would be listed here
    bad, seen = [], 0
    for f in _files():
        text = f.read_text()
        cited = [int(x) for m in LAW_CITE_RE.finditer(text) for x in re.findall(r"L(\d+)", m[1])]
        if f.suffix == ".md":
            cited += [int(x) for x in BARE_L_RE.findall(text)]
        seen += len(cited)
        bad += [f"{f.relative_to(ROOT)}: L{n}" for n in cited if n not in ids]
    assert not bad, bad
    assert seen > 100  # the check reads the citations it guards


def test_wp_ids_cited_are_open_in_build():
    open_ = set(OPEN_WPS_RE.findall((ROOT / "BUILD.md").read_text()))
    bad = []
    for f in _files():
        for n, line in enumerate(f.read_text().splitlines(), 1):
            bad += [
                f"{f.relative_to(ROOT)}:{n}: {w}" for w in WP_RE.findall(line) if w not in open_
            ]
    assert not bad, bad


def test_architecture_sections_cited_exist():
    heads = set(
        re.findall(r"^#{2,3} (\d+(?:\.\d+)?)\. ", (ROOT / "ARCHITECTURE.md").read_text(), re.M)
    )
    bad = [
        f"{f.relative_to(ROOT)}: §{s}"
        for f in _files()
        for s in ARCH_RE.findall(f.read_text())
        if s not in heads and s.split(".")[0] not in heads
    ]
    assert not bad, bad


def test_documents_cited_exist_and_the_old_law_is_gone():
    assert not (ROOT / "00_LAW.md").exists()
    bad = []
    for f in _files():
        text = f.read_text()
        if f.name != "test_law.py" and re.search(r"00_LAW(?:\.md`?)? ?§|00_LAW invariant", text):
            bad.append(f"{f.relative_to(ROOT)}: cites 00_LAW")
        for p in MD_PATH_RE.findall(text):
            if not (
                (ROOT / p).exists() or (f.parent / p).exists() or list(ROOT.rglob(Path(p).name))
            ):
                bad.append(f"{f.relative_to(ROOT)}: {p}")
    assert not bad, bad


# ----- rules no other test held -----


def test_every_articol_names_a_cale_on_its_graph():
    cat = load_catalog()
    for aid, a in cat.articole.items():
        g = cat.graphs.get(a.get("graph_id"))
        assert g is not None, aid
        assert aid in (g.get("allowed_flux") or []), aid
        if a.get("write_modules"):
            assert a.get("hitl"), f"{aid} writes to SAGA with no poartă"


def test_no_database_rights_in_the_package():
    """L10: no SYSDBA, no Firebird driver, no SQL write against SAGA's database in the package."""
    bad = []
    for f in (ROOT / "poarta_contabila").rglob("*.py"):
        src = f.read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                bad += [
                    f"{f.name}: imports {m}" for m in mods if m.split(".")[0] in {"fdb", "firebird"}
                ]
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                v = node.value.upper()
                if "SYSDBA" in v and "NO " not in v:
                    bad.append(f"{f.name}: {node.value[:60]}")
                if "CONT_BAZA" in v and re.search(r"\b(INSERT|UPDATE|DELETE)\b", v):
                    bad.append(f"{f.name}: {node.value[:60]}")
    assert not bad, bad


MODEL_NAMES = {
    "jev",
    "explain",
    "gemini",
    "model",
    "gateway",
    "llm",
    "sys2",
    "openrouter",
    "judge_live",
}


def test_no_model_on_a_graph_edge():
    """L21: the function behind every conditional edge reads state only; it calls no model."""
    checked = 0
    for name in ("triage", "ingest", "reconcile", "close"):
        f = ROOT / "poarta_contabila" / f"{name}.py"
        tree = ast.parse(f.read_text())
        defs = {
            n.name: n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "add_conditional_edges"
            ):
                fn = node.args[1]
                assert isinstance(fn, ast.Name) and fn.id in defs, (
                    f"{name}: edge function not a local def"
                )
                body = defs[fn.id]
                assert not any(
                    isinstance(n, (ast.Await, ast.AsyncFunctionDef))
                    for n in ast.walk(body)
                    if n is not body
                ), fn.id
                called = {
                    (
                        c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", "")
                    ).lower()
                    for c in ast.walk(body)
                    if isinstance(c, ast.Call)
                }
                names = {n.id.lower() for n in ast.walk(body) if isinstance(n, ast.Name)}
                hit = {w for w in MODEL_NAMES for x in called | names if w in x}
                assert not hit, f"{name}.{fn.id} touches {hit}"
                checked += 1
    assert checked >= 7


IBAN_RE = re.compile(r"\bRO\d{2}([A-Z]{4})[0-9A-Z]{16}\b")


@pytest.mark.parametrize("folder", ["fixtures", "tests", "poarta_contabila", "catalog"])
def test_every_iban_in_the_repo_is_invented(folder):
    """L36: a Romanian IBAN in the repo carries the invented bank code AAAA."""
    bad = []
    for f in (ROOT / folder).rglob("*"):
        if (
            f.is_file()
            and "__pycache__" not in f.parts
            and f.suffix in {".py", ".yaml", ".xml", ".json", ".csv"}
        ):
            bad += [
                f"{f.relative_to(ROOT)}: {m[0]}"
                for m in IBAN_RE.finditer(f.read_text(errors="ignore"))
                if m[1] != "AAAA"
            ]
    assert not bad, bad
