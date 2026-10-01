"""WP-01: Lane B catalog loads, merges additive files, and fails closed."""

from __future__ import annotations

import shutil
import typing
from pathlib import Path

import pytest
import yaml

from poarta_contabila.catalog import (
    CatalogError,
    UnknownArticol,
    UnknownHitlKind,
    load_catalog,
)
from poarta_contabila.types import JobStatus, PrimaryKind

PACK = Path(__file__).resolve().parents[1] / "catalog"


@pytest.fixture(scope="module")
def cat():
    return load_catalog(PACK)


@pytest.fixture
def pack_copy(tmp_path):
    dst = tmp_path / "catalog"
    shutil.copytree(PACK, dst)
    return dst


def _edit(path: Path, fn) -> None:
    doc = yaml.safe_load(path.read_text())
    fn(doc)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))


def test_pack_loads(cat):
    assert "ro_efactura_inbound" in cat.articole
    assert "recon_pre_standard" in cat.articole  # reconcile_sink căi live here too
    assert set(cat.graphs) == {
        "folder_triage",
        "ingest_source_doc",
        "reconcile_sink",
        "monthly_close",
    }
    assert cat.write_modules["nota_nc_dbf"].saga_path == "import_dbf"


def test_additive_files_merge(cat):
    assert "decision_menu" in cat.hitl  # from 60_harvest/ARTICOLE_HITL_ADD_v1.yaml
    assert "v3_approve" in cat.hitl  # from 50_control/ARTICOLE_HITL_v1.yaml
    assert "extras_statement_pdf" in cat.source_docs  # SOURCE_DOC_ADD
    assert "C0_synthetic_parity" in cat.controls
    assert "d300_platitor" in cat.filings


def test_unknown_articol_is_an_error(cat):
    with pytest.raises(UnknownArticol):
        cat.articol("ro_efactura_invented")


def test_define_articol_with_invented_id_fails(cat):
    with pytest.raises(UnknownArticol):
        cat.bind_articol("ingest_source_doc", "invented_by_jev")


def test_bind_articol_respects_graph(cat):
    assert cat.bind_articol("ingest_source_doc", "ro_efactura_inbound")["articol_id"]
    with pytest.raises(UnknownArticol):
        cat.bind_articol("monthly_close", "ro_efactura_inbound")


def test_unknown_hitl_kind_is_an_error(cat):
    assert cat.hitl_kind("v3_approve", graph_id="ingest_source_doc")
    with pytest.raises(UnknownHitlKind):
        cat.hitl_kind("approve_please")
    with pytest.raises(UnknownHitlKind):
        cat.hitl_kind("v2_close", graph_id="ingest_source_doc")  # not allowed on that graph


def test_types_match_catalog_enums(cat):
    assert set(typing.get_args(JobStatus)) == set(cat.enums("ArticoleJobs")["status"])
    assert set(typing.get_args(PrimaryKind)) == set(cat.enums("ArticoleSourceDoc")["primary_kind"])


def test_write_module_and_cale_agree_both_ways(cat):
    for articol_id, row in cat.articole.items():
        for module_id in row.get("write_modules") or []:
            assert articol_id in cat.write_modules[module_id].used_by_flux, (articol_id, module_id)


def test_duplicate_id_across_files_is_an_error(pack_copy):
    _edit(
        pack_copy / "60_harvest/ARTICOLE_HITL_ADD_v1.yaml",
        lambda d: d["kinds"].append({**d["kinds"][0], "kind": "v3_approve"}),
    )
    with pytest.raises(CatalogError, match="duplicate"):
        load_catalog(pack_copy)


def test_two_base_files_for_one_catalog_is_an_error(pack_copy):
    _edit(pack_copy / "60_harvest/ARTICOLE_HITL_ADD_v1.yaml", lambda d: d.pop("mode"))
    with pytest.raises(CatalogError, match="additive"):
        load_catalog(pack_copy)


def test_dangling_write_module_is_an_error(pack_copy):
    def add(d):
        d["flux"][0]["write_modules"] = ["fdb_direct"]

    _edit(pack_copy / "30_cale/ARTICOLE_FLUX_v1.yaml", add)
    with pytest.raises(CatalogError, match="fdb_direct"):
        load_catalog(pack_copy)


def test_unknown_hitl_kind_on_a_graph_is_an_error(pack_copy):
    _edit(
        pack_copy / "30_cale/ARTICOLE_GRAPH_v1.yaml",
        lambda d: d["graphs"][0]["allowed_hitl"].append("ask_the_llm"),
    )
    with pytest.raises(CatalogError, match="ask_the_llm"):
        load_catalog(pack_copy)


def test_write_module_with_fdb_path_is_refused(pack_copy):
    _edit(
        pack_copy / "30_cale/ARTICOLE_WRITE_MODULE_v1.yaml",
        lambda d: d["modules"][0].update(saga_path="fdb_insert"),
    )
    with pytest.raises(CatalogError, match="parteneri_xml"):
        load_catalog(pack_copy)


def test_unparseable_yaml_is_an_error(pack_copy):
    (pack_copy / "30_cale/ARTICOLE_GRAPH_v1.yaml").write_text("graphs: [\n)\n")
    with pytest.raises(CatalogError, match="ARTICOLE_GRAPH_v1.yaml"):
        load_catalog(pack_copy)


# ----- A2 -----


def test_a2_sources_exist_and_never_post(cat):
    for sid in (
        "sink_rj_nextup",
        "sink_balanta_saga",
        "sink_balanta_nextup",
        "decont_cheltuieli",
        "stat_salarii",
    ):
        assert sid in cat.source_docs, sid
        assert cat.source_docs[sid]["posting_eligible"] is False, sid


def test_decont_is_a_split_container(cat):
    split = cat.source_docs["decont_cheltuieli"]["split"]
    assert split["hitl"] == "decont_split"
    assert "decont_split" in cat.allowed_hitl("folder_triage")
    assert set(split["children"]) <= set(cat.source_docs)


def test_split_child_must_exist(pack_copy):
    def bad(d):
        for row in d["rows"]:
            if row["source_doc_id"] == "decont_cheltuieli":
                row["split"]["children"].append("invented_child")

    _edit(pack_copy / "60_harvest/ARTICOLE_SOURCE_DOC_ADD_v1.yaml", bad)
    with pytest.raises(CatalogError, match="invented_child"):
        load_catalog(pack_copy)


def test_book_of_record_allows_nextup_as_eye(cat):
    axes = cat.docs["ArticoleCoDitAxes"]["new_axes"]
    assert axes["book_of_record"]["values"] == ["saga_c", "nextup"]
