"""WP-71: the scenario runner — every scenario in fixtures/scenarios/ runs locally and passes."""

from __future__ import annotations

import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.coverage import build_map
from poarta_contabila.scenarios import (
    AGENT_LABEL,
    SCENARIOS_DIR,
    Scenario,
    head,
    load,
    main,
    names,
    render,
    run_one,
    scenarios,
)

ALL = scenarios()


@pytest.mark.parametrize("sc", ALL, ids=[s.name for s in ALL])
def test_every_scenario_passes(sc):
    result = run_one(sc)
    assert result.passed, render([result])


def test_a_wrong_expectation_fails_with_its_difference():
    sc = load(SCENARIOS_DIR / "platitor_clean.yaml")
    wrong = sc.model_copy(
        update={
            "expect": sc.expect.model_copy(
                update={
                    "documents": {
                        "p1": sc.expect.documents["p1"].model_copy(update={"status": "rejected"})
                    }
                }
            )
        }
    )
    result = run_one(wrong)
    assert not result.passed
    assert result.diffs == ["p1.status: expected 'rejected', got 'acked'"]
    assert AGENT_LABEL in render([result])


def test_scenario_files_are_closed_and_named_after_their_file(tmp_path):
    bad = tmp_path / "other.yaml"
    bad.write_text("name: something\nfirm: platitor\nperiod: '2026-05'\n")
    with pytest.raises(ValueError, match="differs from the file name"):
        load(bad)
    with pytest.raises(ValueError):
        Scenario.model_validate({"name": "x", "firm": "platitor", "period": "2026-05", "y": 1})
    with pytest.raises(KeyError):
        scenarios(["no_such_scenario"])


def test_a_passing_run_feeds_the_coverage_map():
    sc = load(SCENARIOS_DIR / "platitor_clean.yaml")
    named = names(sc)
    assert ("articol", "ro_efactura_inbound") in named
    assert ("articol", "recon_pre_extras") in named  # from the PRE profile
    assert ("control", "C0_synthetic_parity:PASS") in named
    assert ("hitl", "v4_codit") in named and ("hitl", "filing_receipt") in named
    cmap = build_map(load_catalog(), [run_one(sc).outcome()])
    rows = {(r.table, r.key): r for r in cmap.rows}
    assert rows[("write_module", "plata_xml")].scenarios == ["platitor_clean"]
    assert rows[("filing", "d300_platitor")].covered
    assert cmap.problems == []


def test_a_run_reports_what_the_catalog_does_not_foresee():
    outcome = run_one(load(SCENARIOS_DIR / "bonuri_decont.yaml")).outcome()
    cmap = build_map(load_catalog(), [outcome])
    stalled = {(f.kind, f.subject) for f in cmap.findings}
    assert ("no_articol", "bon1") in stalled and ("no_articol", "bon2") in stalled


def test_blocker_heads():
    assert head("C0_synthetic_parity: 401:credit expected 1, books 2") == "C0_synthetic_parity"
    assert head("M1_1_trade_ext (advisory): x") == "M1_1_trade_ext"
    assert head("lock mismatch: the month's jobs changed") == "lock mismatch"


def test_the_cli_runs_named_scenarios(capsys):
    assert main(["platitor_clean"]) == 0
    out = capsys.readouterr().out
    assert "[pass] platitor_clean" in out and AGENT_LABEL in out
