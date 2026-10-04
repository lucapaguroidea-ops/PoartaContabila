"""ingest_source_doc through `packaged`, with v3_approve before any SAGA write."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from poarta_contabila.catalog import load_catalog
from poarta_contabila.flux import MatchContext, match_articole
from poarta_contabila.ingest import IngestDeps, build_ingest_graph, start_payload
from poarta_contabila.jobs import InMemoryJobStore
from poarta_contabila.packages import InMemoryBlobStore, InMemoryPackageStore
from poarta_contabila.recon.pre import PreResult
from poarta_contabila.sinks.saga_xml import fixture_documents
from poarta_contabila.triage import EmitDecision, Pack


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


class World:
    """Stores + fakes for one test; counts SAGA-side writes."""

    def __init__(self, cat, *, pre="absent", judge=None):
        self.jobs = InMemoryJobStore()
        self.blobs = InMemoryBlobStore()
        self.packages = InMemoryPackageStore()
        self.deps = IngestDeps(
            catalog=cat,
            jobs=self.jobs,
            packages=self.packages,
            blobs=self.blobs,
            pre_check=lambda job, doc, **kw: PreResult(
                verdict=pre, reason="test", profile_id=None, snapshot_id="test"
            ),
            judge=judge
            or (lambda doc, articol: {"accounts_ok": True, "risk": "low", "needs_human": False}),
            tenant_name=lambda cui: "Firma Test",
        )
        self.graph = build_ingest_graph(self.deps, checkpointer=MemorySaver())

    def emit(self, kind="iesire", source_hash=None):
        doc = fixture_documents()[kind]
        pack = Pack(
            tenant_cui=doc.tenant.cui,
            saga_firm_folder="0001",
            period=doc.period,
            source_hash=source_hash or doc.source.source_hash,
            source_doc_id="ro_efactura_ubl",
            kinds=["ubl_spv"],
            our_role="outbound" if kind == "iesire" else "inbound",
            counterparty_cui=doc.partner.cui,
        )
        job = self.jobs.emit(
            pack, EmitDecision(emit=True, job_kind="job_ro_efactura", aisle="x")
        ).job
        return job, doc.model_copy(update={"job_id": job.job_id})

    def run(self, job, doc, **kw):
        cfg = {"configurable": {"thread_id": f"job:{job.job_id}"}}
        out = self.graph.invoke(start_payload(job, doc, source_doc_id="ro_efactura_ubl"), cfg)
        return cfg, out

    def interrupt(self, cfg):
        tasks = self.graph.get_state(cfg).tasks
        return tasks[0].interrupts[0].value if tasks and tasks[0].interrupts else None


# ----- flux matching -----


def test_match_outbound_efactura(cat):
    ctx = MatchContext(
        graph_id="ingest_source_doc", fiscal_class="ro_efactura", our_role="outbound"
    )
    assert match_articole(cat, ctx) == ["ro_efactura_outbound"]


def test_match_storno_goes_to_storno_articol(cat):
    ctx = MatchContext(
        graph_id="ingest_source_doc", fiscal_class="ro_efactura", our_role="inbound", is_storno=True
    )
    assert match_articole(cat, ctx) == ["storno_intrare"]


def test_match_respects_forbid_axes(cat):
    ctx = MatchContext(
        graph_id="ingest_source_doc",
        fiscal_class="ro_efactura",
        our_role="outbound",
        axes={"rol": "mandat_contabil"},
    )
    assert match_articole(cat, ctx) == []


# ----- graph -----


def test_first_jobs_ask_v3_approve_before_any_saga_write(cat):
    w = World(cat)
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    question = w.interrupt(cfg)
    assert question["kind"] == "v3_approve" and question["articol_id"] == "ro_efactura_outbound"
    assert w.blobs.puts == 0 and not w.packages.rows
    assert w.jobs.get(job.job_id).status == "reconcile_pre"


def test_approve_packages_exactly_once(cat):
    w = World(cat)
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    out = w.graph.invoke(Command(resume={"decision": "approve", "edit": None}), cfg)
    assert out["status"] == "packaged"
    assert out["export_key"] == f"iesire_factura_xml:{job.job_id}:1"
    assert w.blobs.puts == 1 and len(w.packages.rows) == 1
    record = w.jobs.get(job.job_id)
    assert record.status == "packaged" and record.module_id == "iesire_factura_xml"
    assert record.articol_id == "ro_efactura_outbound"
    # replaying the node (crash/resume) does not write a second XML
    w.deps.package(record, doc, w.deps.catalog.write_modules["iesire_factura_xml"])
    assert w.blobs.puts == 1 and len(w.packages.rows) == 1


def test_reject_does_not_package(cat):
    w = World(cat)
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    out = w.graph.invoke(Command(resume={"decision": "reject", "edit": None}), cfg)
    assert out["status"] == "rejected"
    assert w.blobs.puts == 0 and not w.packages.rows
    assert w.jobs.get(job.job_id).status == "rejected"


def test_invalid_resume_is_asked_again(cat):
    w = World(cat)
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    w.graph.invoke(Command(resume={"approve": True, "reject": False}), cfg)
    question = w.interrupt(cfg)
    assert question["kind"] == "v3_approve" and question["error"]
    assert w.blobs.puts == 0


def test_edit_patches_the_document_before_packaging(cat):
    w = World(cat)
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    out = w.graph.invoke(Command(resume={"decision": "edit", "edit": {"number": "FX-102"}}), cfg)
    assert out["status"] == "packaged"
    (blob,) = w.blobs.data.values()
    assert b"<FacturaNumar>FX-102</FacturaNumar>" in blob


def test_edit_with_unknown_field_is_asked_again(cat):
    w = World(cat)
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    w.graph.invoke(Command(resume={"decision": "edit", "edit": {"tva_deducere": "full"}}), cfg)
    assert w.interrupt(cfg)["error"]
    assert w.blobs.puts == 0


def test_already_in_sink_never_packages(cat):
    w = World(cat, pre="already_posted")
    job, doc = w.emit()
    _, out = w.run(job, doc)
    assert out["status"] == "already_in_sink"
    assert w.blobs.puts == 0 and w.jobs.get(job.job_id).status == "already_in_sink"


def test_ambiguous_pre_needs_human_and_does_not_package(cat):
    w = World(cat, pre="ambiguous")
    job, doc = w.emit()
    _, out = w.run(job, doc)
    assert out["status"] == "needs_human" and w.blobs.puts == 0


def test_first_n_then_no_interrupt_when_judge_is_confident(cat):
    w = World(cat)
    first_n = cat.articol("ro_efactura_outbound")["first_n"]
    for i in range(first_n):
        job, doc = w.emit(source_hash=f"{i:064x}")
        cfg, _ = w.run(job, doc)
        w.graph.invoke(Command(resume={"decision": "approve", "edit": None}), cfg)
    job, doc = w.emit(source_hash="f" * 64)
    _, out = w.run(job, doc)
    assert out["status"] == "packaged"


def test_judge_needs_human_forces_the_question(cat):
    judge = lambda doc, articol: {"accounts_ok": False, "risk": "high", "needs_human": True}  # noqa: E731
    w = World(cat, judge=judge)
    first_n = cat.articol("ro_efactura_outbound")["first_n"]
    w.jobs.packaged_count = lambda cui, articol_id: first_n  # past first_n
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    assert w.interrupt(cfg)["kind"] == "v3_approve"


def test_no_articol_asks_define_articol(cat):
    w = World(cat)
    job, doc = w.emit()
    cfg = {"configurable": {"thread_id": f"job:{job.job_id}"}}
    w.graph.invoke(
        start_payload(job, doc, source_doc_id="ro_efactura_ubl", axes={"rol": "mandat_contabil"}),
        cfg,
    )
    question = w.interrupt(cfg)
    assert question["kind"] == "define_articol"
    w.graph.invoke(Command(resume={"articol_id": "invented_by_jev"}), cfg)
    assert "invented_by_jev" in w.interrupt(cfg)["error"]
    w.graph.invoke(Command(resume={"articol_id": "ro_efactura_outbound"}), cfg)
    assert w.interrupt(cfg)["kind"] == "v3_approve"


def test_thread_prefix_is_job(cat):
    w = World(cat)
    job, doc = w.emit()
    with pytest.raises(ValueError, match="job:"):
        w.graph.invoke(
            start_payload(job, doc, source_doc_id="ro_efactura_ubl"),
            {"configurable": {"thread_id": f"batch:{job.job_id}"}},
        )


def test_intrare_packages_through_intrare_mouth(cat):
    w = World(cat)
    job, doc = w.emit(kind="intrare")
    cfg, _ = w.run(job, doc)
    out = w.graph.invoke(Command(resume={"decision": "approve", "edit": None}), cfg)
    assert out["status"] == "packaged" and out["export_key"].startswith("intrare_factura_xml:")


def test_postgres_stores_package_once(cat):
    import os

    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    from poarta_contabila.jobs import PostgresJobStore
    from poarta_contabila.packages import PostgresPackageStore

    w = World(cat)
    w.jobs = w.deps.jobs = PostgresJobStore(dsn, reset=True)
    w.packages = w.deps.packages = PostgresPackageStore(dsn)
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    out = w.graph.invoke(Command(resume={"decision": "approve", "edit": None}), cfg)
    assert out["status"] == "packaged"
    record = w.jobs.get(job.job_id)
    w.deps.package(record, doc, cat.write_modules["iesire_factura_xml"])
    assert w.blobs.puts == 1
    assert w.jobs.get(job.job_id).status == "packaged"
    assert w.jobs.packaged_count(doc.tenant.cui, "ro_efactura_outbound") == 1


def test_a_nextup_tenant_gets_no_prefile(cat):
    """LAW L8: nothing is written to NextUp; the job stops before any package."""
    w = World(cat)
    w.deps.book_of_record = lambda cui: "nextup"
    w.graph = build_ingest_graph(w.deps, checkpointer=MemorySaver())
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    out = w.graph.invoke(Command(resume={"decision": "approve", "edit": None}), cfg)
    assert out["status"] == "needs_human"
    assert w.blobs.puts == 0 and not w.packages.rows
    assert "no PreFile" in w.jobs.get(job.job_id).error
