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


@pytest.fixture(scope="module")
def results():
    """Every scenario, run once for this module (each on a fresh in-memory runtime)."""
    return {sc.name: run_one(sc) for sc in ALL}


@pytest.mark.parametrize("name", [s.name for s in ALL])
def test_every_scenario_passes(results, name):
    assert results[name].passed, render([results[name]])


def test_every_reachable_catalog_row_has_a_passing_scenario(results):
    """WP-72, catalog → data: a row is reachable or listed out of reach with its reason."""
    cmap = build_map(load_catalog(), [r.outcome() for r in results.values()])
    assert cmap.problems == []
    assert [f"{r.table} {r.key}" for r in cmap.to_scenario()] == []
    for r in cmap.rows:
        assert r.covered or (r.reach is not None and r.reach.note), (r.table, r.key)


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


def test_nothing_unforeseen_once_the_accepted_rows_are_in(results):
    """WP-73: after G1–G4 and G6 entered, the realistic months land on nothing the catalog
    does not foresee (no refused upload, no unbound Job, no blocker outside a control)."""
    cmap = build_map(load_catalog(), [r.outcome() for r in results.values()])
    assert [(f.kind, f.scenario, f.subject) for f in cmap.findings] == []


def test_an_invoice_from_abroad_as_xml_is_a_foreign_invoice_job():
    """WP-73 G1: a UBL whose counterparty has no RO CUI is foreign_invoice_xml."""
    from poarta_contabila.scenarios import local_clients
    from poarta_contabila.synthetic import FIRMS
    from poarta_contabila.synthetic.docs import Gen

    f = FIRMS["abroad"]
    client, _ = local_clients()
    assert client.put(f"/tenants/{f.cui}", json=f.tenant()).status_code == 200
    g = Gen(f, "2026-05", 2)
    xml = g.foreign_purchase("x", partner="x1", currency="RON").xml(f)
    body = client.post(
        "/ingest",
        params={"cui": f.cui, "filename": "x.xml"},
        content=xml,
        headers={"Content-Type": "application/octet-stream"},
    ).json()
    job = body["job"]
    assert (
        job["job_kind"] == "job_foreign_invoice" and job["articol_id"] == "foreign_invoice_inbound"
    )
    assert body["pre"]["profile_id"] == "pre_doc_nr_date"  # PRE waits on the books here


def test_blocker_heads():
    assert head("C0_synthetic_parity: 401:credit expected 1, books 2") == "C0_synthetic_parity"
    assert head("M1_1_trade_ext (advisory): x") == "M1_1_trade_ext"
    assert head("lock mismatch: the month's jobs changed") == "lock mismatch"


def test_the_cli_runs_named_scenarios(capsys):
    assert main(["platitor_clean"]) == 0
    out = capsys.readouterr().out
    assert "[pass] platitor_clean" in out and AGENT_LABEL in out


def test_an_invoice_from_abroad_is_not_labelled_as_from_spv():
    """WP-74 (live): System Two read "received via SPV" off an XML from abroad; the stored
    source kind said ``ubl_spv``. It is ``xml``; an SPV zip stays ``ubl_spv``."""
    from langgraph.checkpoint.memory import MemorySaver

    from poarta_contabila.agent import InMemoryAgentStore
    from poarta_contabila.jobs import InMemoryJobStore
    from poarta_contabila.packages import InMemoryBlobStore, InMemoryPackageStore
    from poarta_contabila.recon.pre import InMemoryReconStore
    from poarta_contabila.registry import InMemoryRegistry, Tenant
    from poarta_contabila.runtime import build_runtime
    from poarta_contabila.synthetic import FIRMS
    from poarta_contabila.synthetic.docs import Gen

    f = FIRMS["abroad"]
    rt = build_runtime(
        catalog=load_catalog(),
        jobs=InMemoryJobStore(),
        packages=InMemoryPackageStore(),
        blobs=InMemoryBlobStore(),
        registry=InMemoryRegistry(),
        recon=InMemoryReconStore(),
        agent_store=InMemoryAgentStore(),
        checkpointer=MemorySaver(),
    )
    rt.registry.put_tenant(Tenant.model_validate(f.tenant()))
    g = Gen(f, "2026-05", 3)
    x = rt.ingest_upload(f.cui, g.foreign_purchase("x", partner="x1").xml(f), "x.xml")
    p = rt.ingest_upload(f.cui, g.purchase("p").spv_zip(f), "p.zip")
    assert rt.canonical(x["job"]["job_id"]).source.kind == "xml"
    assert rt.canonical(p["job"]["job_id"]).source.kind == "ubl_spv"
