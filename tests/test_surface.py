"""The surface: four states per row, from the catalog, the scenario runs and ``surface/``."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from poarta_contabila.catalog import load_catalog
from poarta_contabila.coverage import ScenarioOutcome, build_map
from poarta_contabila.surface import (
    SURFACE_DIR,
    SurfaceError,
    build_surface,
    load_data,
    render_markdown,
)

ROW = ("articol", "ro_efactura_inbound")
REF = "articol:ro_efactura_inbound"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture
def data_dir(tmp_path) -> Path:
    d = tmp_path / "surface"
    shutil.copytree(SURFACE_DIR, d)
    return d


def _evidence(d: Path, **over) -> None:
    e = {
        "loop": 1,
        "date": "2026-11-02",
        "firm_cui": "1000009",
        "saga_build": "3.0.600",
        "approved": "owner, 2026-11-03",
        "rows": [REF],
        "exports": ["fixtures/saga/iesire.xml"],
    }
    e.update(over)
    (d / "evidence" / "loop-01-1000009.yaml").write_text(yaml.safe_dump(e))


def _out(d: Path, rows: list[dict]) -> None:
    (d / "out.yaml").write_text(yaml.safe_dump({"rows": rows}))


def _map(cat, passing: bool = True):
    o = ScenarioOutcome("s", passed=passing, names=frozenset({ROW}))
    return build_map(cat, [o])


def test_the_repo_data_loads_and_every_possible_row_is_possible(cat):
    data = load_data()
    assert len(data.possible) == 50 and data.out == [] and data.evidence == []
    s = build_surface(build_map(cat), data)
    assert s.problems == []
    assert {r.state for r in s.rows if r.table == "possible"} == {"possible"}


def test_a_passing_scenario_makes_a_catalog_row_synthetic(cat):
    s = build_surface(_map(cat), load_data())
    assert s.state(REF) == "synthetic"
    assert build_surface(_map(cat, passing=False), load_data()).state(REF) == "possible"


def test_a_row_out_of_reach_is_possible_with_its_reason(cat):
    s = build_surface(build_map(cat), load_data())
    row = next(r for r in s.rows if r.ref == "articol:bon_cu_cui")
    assert row.state == "possible" and "parked WP-14" in row.why
    row = next(r for r in s.rows if r.ref == REF)
    assert row.state == "possible" and row.why == "reachable, no scenario yet"


def test_loop_evidence_makes_a_row_saga_over_synthetic(cat, data_dir):
    _evidence(data_dir)
    s = build_surface(_map(cat), load_data(data_dir))
    assert s.state(REF) == "saga" and s.problems == []


def test_the_owners_out_decision(cat, data_dir):
    _out(
        data_dir,
        [
            {
                "ref": "source_doc:unknown",
                "reason": "no route mints it",
                "decided": "owner, 2026-11-03",
            }
        ],
    )
    _out_possible = {
        "ref": "S-XB-03",
        "reason": "no marketplace clients",
        "decided": "owner, 2026-11-03",
    }
    _out(data_dir, [*yaml.safe_load((data_dir / "out.yaml").read_text())["rows"], _out_possible])
    s = build_surface(build_map(cat), load_data(data_dir))
    assert s.state("source_doc:unknown") == "out" and s.state("S-XB-03") == "out"


@pytest.mark.parametrize(
    "out, evidence_rows, problem",
    [
        (
            [{"ref": REF, "reason": "x", "decided": "owner, 2026-11-03"}],
            [REF],
            "both out and proven",
        ),
        (
            [{"ref": "articol:nope", "reason": "x", "decided": "owner, 2026-11-03"}],
            None,
            "not a row",
        ),
        ([], ["articol:nope"], "not a catalog row"),
    ],
)
def test_data_that_does_not_hold_together_is_a_problem(cat, data_dir, out, evidence_rows, problem):
    _out(data_dir, out)
    if evidence_rows:
        _evidence(data_dir, rows=evidence_rows)
    s = build_surface(build_map(cat), load_data(data_dir))
    assert any(problem in p for p in s.problems), s.problems


def test_an_active_row_not_proven_in_saga_is_a_problem(cat):
    cmap = build_map(cat)
    next(r for r in cmap.rows if (r.table, r.key) == ROW).status = "active"
    s = build_surface(cmap, load_data())
    assert any("LAW L42" in p for p in s.problems)


@pytest.mark.parametrize(
    "over, match",
    [
        ({"firm_cui": "1000001"}, "not a valid CUI"),
        ({"exports": ["fixtures/saga/nope.xml"]}, "not in the repo"),
        ({"approved": "someone"}, "owner, YYYY-MM-DD"),
        ({"rows": []}, "names no row"),
        ({"date": "2.11.2026"}, "date"),
    ],
)
def test_bad_evidence_does_not_load(data_dir, over, match):
    _evidence(data_dir, **over)
    with pytest.raises(SurfaceError, match=match):
        load_data(data_dir)


def test_an_out_row_needs_a_reason_and_the_owners_date(data_dir):
    _out(data_dir, [{"ref": "S-XB-03", "reason": "", "decided": "owner, 2026-11-03"}])
    with pytest.raises(SurfaceError, match="needs ref, reason, decided"):
        load_data(data_dir)
    _out(data_dir, [{"ref": "S-XB-03", "reason": "x", "decided": "2026-11-03"}])
    with pytest.raises(SurfaceError, match="owner, YYYY-MM-DD"):
        load_data(data_dir)


def test_a_possible_id_twice_or_an_unknown_kind_does_not_load(data_dir):
    p = data_dir / "possible.yaml"
    rows = yaml.safe_load(p.read_text())["rows"]
    p.write_text(yaml.safe_dump({"rows": [*rows, rows[0]]}))
    with pytest.raises(SurfaceError, match="twice"):
        load_data(data_dir)
    p.write_text(yaml.safe_dump({"rows": [{**rows[0], "kind": "ledger"}]}))
    with pytest.raises(SurfaceError, match="kind"):
        load_data(data_dir)


def test_the_markdown_names_every_row_and_counts_them(cat):
    s = build_surface(_map(cat), load_data())
    text = render_markdown(s)
    assert "| **all** |" in text and "## 3. Not in the catalog yet" in text
    for r in s.rows:
        assert (r.ref.split(":", 1)[-1]) in text
