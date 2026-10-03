"""WP-69: the coverage map — every reachable catalog row × the scenarios and tests that drive it."""

from __future__ import annotations

import json

import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.coverage import (
    OUT_OF_REACH,
    DocActual,
    MonthActual,
    ScenarioOutcome,
    build_map,
    control_key,
    main,
    render,
)


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def test_the_map_lists_every_flux_row_and_every_reachable_table(cat):
    cmap = build_map(cat)
    articole = {r.key for r in cmap.table("articol")}
    assert articole == set(cat.articole)  # Flux and Reconcile rows alike
    assert {r.key for r in cmap.table("hitl")} == set(cat.hitl)
    assert {r.key for r in cmap.table("control")} == {
        control_key(c, o) for c in cat.controls for o in ("PASS", "FAIL")
    }
    for table, rows in (
        ("source_doc", cat.source_docs),
        ("job_kind", cat.jobs),
        ("recon_profile", cat.recon_profiles),
        ("write_module", cat.write_modules),
        ("filing", cat.filings),
        ("close_kind", cat.close_kinds),
    ):
        assert {r.key for r in cmap.table(table)} == set(rows), table
    assert cmap.problems == []  # OUT_OF_REACH names only real rows


def test_an_out_of_reach_row_says_why(cat):
    cmap = build_map(cat)
    rows = {(r.table, r.key): r for r in cmap.rows}
    assert rows[("articol", "bon_cu_cui")].reach.ref == "WP-14"
    assert rows[("write_module", "nota_nc_dbf")].reach.kind == "decision"
    assert rows[("hitl", "recon_review_contest")].reach.kind == "live_only"
    assert rows[("articol", "ro_efactura_inbound")].reach is None
    for (table, key), reach in OUT_OF_REACH.items():
        assert rows[(table, key)].reach == reach and reach.note


def test_tests_naming_a_row_are_shown_but_never_count_as_coverage(cat):
    cmap = build_map(cat)
    row = next(r for r in cmap.table("articol") if r.key == "ro_efactura_inbound")
    assert row.tests and not row.covered
    assert row in cmap.to_scenario()


def test_a_row_counts_as_covered_only_when_a_passing_scenario_names_it(cat):
    names = frozenset({("articol", "ro_efactura_inbound"), ("hitl", "v3_approve")})
    failing = ScenarioOutcome("bad", passed=False, names=names)
    cmap = build_map(cat, [failing])
    rows = {(r.table, r.key): r for r in cmap.rows}
    assert not rows[("articol", "ro_efactura_inbound")].covered

    passing = ScenarioOutcome("good", passed=True, names=names)
    cmap = build_map(cat, [failing, passing])
    rows = {(r.table, r.key): r for r in cmap.rows}
    assert rows[("articol", "ro_efactura_inbound")].scenarios == ["good"]
    assert rows[("hitl", "v3_approve")].covered
    assert cmap.summary()["articol"]["covered"] == 1


def test_a_scenario_reaching_an_out_of_reach_row_or_an_unknown_row_is_a_problem(cat):
    o = ScenarioOutcome(
        "odd",
        passed=True,
        names=frozenset({("articol", "bon_cu_cui"), ("articol", "no_such_articol")}),
    )
    cmap = build_map(cat, [o])
    assert any("bon_cu_cui is listed out of reach" in p for p in cmap.problems)
    assert any("no_such_articol" in p for p in cmap.problems)


def test_data_to_catalog_findings(cat):
    o = ScenarioOutcome(
        "blind",
        passed=False,
        documents=(
            DocActual("a", "bound", "ro_efactura_inbound", ("define_articol",)),
            DocActual("b", None, error="emit gates failed: ['identity_gate']"),
            DocActual("c", "needs_human", None, error="no articol"),
            DocActual("d", "ingested"),
            DocActual("e", "acked", "ro_efactura_outbound", ("v3_approve",)),
            DocActual("f", "rejected"),
        ),
        months=(
            MonthActual(
                "2027-03",
                (
                    "C0_synthetic_parity: 401:credit expected 1.00, books 2.00",
                    "M1_1_trade_ext (advisory): analytics under 403 …",
                    "lock mismatch: the month's jobs changed since the lock; reopen first",
                ),
            ),
        ),
    )
    cmap = build_map(cat, [o])
    got = {(f.kind, f.subject) for f in cmap.findings}
    assert got == {
        ("define_articol", "a"),
        ("refused", "b"),
        ("needs_human_no_articol", "c"),
        ("no_articol", "d"),
        ("unexplained_blocker", "2027-03"),
    }
    text = render(cmap)
    assert "unexplained_blocker: lock mismatch" in text and "blind (FAIL)" in text


def test_the_cli_prints_text_and_json(capsys):
    assert main(["--no-run"]) == 0
    assert "articole de cale: 23 rows" in capsys.readouterr().out
    assert main(["--json", "--no-run"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["articol"]["rows"] == 23 and data["problems"] == []
