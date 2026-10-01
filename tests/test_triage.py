"""WP-02: folder_triage emit gates, aisle routing, and one Job per (tenant, source_hash)."""

from __future__ import annotations

import os
import uuid

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from poarta_contabila.catalog import load_catalog
from poarta_contabila.jobs import InMemoryJobStore, PostgresJobStore
from poarta_contabila.jsonlogic import apply
from poarta_contabila.triage import Pack, build_triage_graph, decide_emit

CUI = "1000009"  # invented, valid check digit
PARTNER = "20000005"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _pack(**over) -> Pack:
    base = dict(
        tenant_cui=CUI,
        saga_firm_folder="0001",
        period="2026-09",
        source_hash="b" * 64,
        source_doc_id="ro_efactura_ubl",
        kinds=["ubl_spv"],
        our_role="inbound",
        counterparty_cui=PARTNER,
    )
    base.update(over)
    return Pack(**base)


# ----- jsonlogic -----


def test_jsonlogic_core_ops():
    assert apply({"==": [{"var": "a.b"}, 1]}, {"a": {"b": 1}}) is True
    assert apply({"and": [True, {"!": False}]}, {}) is True
    assert apply({"in": ["x", ["x", "y"]]}, {}) is True
    assert apply({"if": [False, "a", True, "b", "c"]}, {}) == "b"
    with pytest.raises(ValueError, match="unsupported"):
        apply({"merge": [[1], [2]]}, {})


# ----- gates -----


def test_ubl_inbound_emits_job_ro_efactura(cat):
    d = decide_emit(cat, _pack())
    assert d.emit and d.job_kind == "job_ro_efactura"
    assert d.aisle == "10_ro_efactura/inbound/20000005/"


def test_pdf_only_ro_efactura_does_not_emit(cat):
    d = decide_emit(cat, _pack(source_doc_id="ro_efactura_pdf", kinds=["pdf"]))
    assert not d.emit
    assert "class_gate" in d.failed
    assert d.aisle == "10_ro_efactura/_incomplete_spv/"


def test_ubl_label_without_ubl_bytes_does_not_emit(cat):
    d = decide_emit(cat, _pack(kinds=["pdf"]))
    assert not d.emit and "primary_gate" in d.failed


def test_ro_efactura_needs_counterparty_cui(cat):
    d = decide_emit(cat, _pack(counterparty_cui=None))
    assert not d.emit and "identity_gate" in d.failed


def test_extras_without_tenant_identity_does_not_emit(cat):
    d = decide_emit(
        cat, _pack(source_doc_id="extras", kinds=["mt940"], our_role="n/a", identity_ok=False)
    )
    assert not d.emit and "identity_gate" in d.failed
    ok = decide_emit(
        cat, _pack(source_doc_id="extras", kinds=["mt940"], our_role="n/a", identity_ok=True)
    )
    assert ok.emit and ok.job_kind == "job_extras"


def test_extras_pdf_has_no_job_kind_until_wp13(cat):
    d = decide_emit(
        cat,
        _pack(
            source_doc_id="extras_statement_pdf", kinds=["pdf"], our_role="n/a", identity_ok=True
        ),
    )
    assert not d.emit and "job_kind" in d.failed


def test_storno_ubl_emits_job_storno(cat):
    d = decide_emit(cat, _pack(is_storno=True))
    assert d.emit and d.job_kind == "job_storno"


def test_non_posting_sources_never_emit(cat):
    for sid in ("instructions", "recon_vendor", "workings", "sink_rj", "unknown"):
        d = decide_emit(cat, _pack(source_doc_id=sid, kinds=["pdf"], our_role="n/a"))
        assert not d.emit, sid


def test_unknown_source_doc_id_fails_closed(cat):
    with pytest.raises(Exception, match="unknown source_doc_id"):
        decide_emit(cat, _pack(source_doc_id="factura_simplificata"))


def test_pack_refuses_extra_keys():
    with pytest.raises(ValidationError):
        _pack(tva_deducere="full")


# ----- job uniqueness -----


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        return InMemoryJobStore()
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    return PostgresJobStore(dsn, reset=True)


def test_duplicate_hash_does_not_create_second_job(cat, store):
    pack = _pack(source_hash=uuid.uuid4().hex * 2)
    first = store.emit(pack, decide_emit(cat, pack))
    second = store.emit(pack, decide_emit(cat, pack))
    assert first.created and not second.created
    assert first.job.job_id == second.job.job_id
    assert first.job.status == "ingested" and first.job.job_kind == "job_ro_efactura"


def test_store_refuses_a_closed_gate(cat, store):
    pack = _pack(source_doc_id="ro_efactura_pdf", kinds=["pdf"])
    with pytest.raises(ValueError, match="not emittable"):
        store.emit(pack, decide_emit(cat, pack))


# ----- graph -----


def _run(graph, thread, payload):
    return graph.invoke(payload, {"configurable": {"thread_id": thread}})


def test_graph_emits_and_is_idempotent(cat):
    store = InMemoryJobStore()
    graph = build_triage_graph(cat, store, checkpointer=MemorySaver())
    out = _run(graph, "batch:t1", {"pack": _pack().model_dump()})
    again = _run(graph, "batch:t2", {"pack": _pack().model_dump()})
    assert out["job_id"] and out["job_id"] == again["job_id"]
    assert len(store.jobs) == 1


def test_graph_interrupts_define_class_on_unknown(cat):
    store = InMemoryJobStore()
    graph = build_triage_graph(cat, store, checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "batch:t3"}}
    graph.invoke({"pack": _pack(source_doc_id="unknown").model_dump()}, cfg)
    state = graph.get_state(cfg)
    (intr,) = state.tasks[0].interrupts
    assert intr.value["kind"] == "define_class"
    # an invalid answer does not poison the thread: it is asked again, with the error
    graph.invoke(Command(resume={"source_doc_id": "ro_efactura_ubl", "x": 1}), cfg)
    (intr,) = graph.get_state(cfg).tasks[0].interrupts
    assert intr.value["kind"] == "define_class" and intr.value["error"]
    graph.invoke(Command(resume={"source_doc_id": "invented_class"}), cfg)
    (intr,) = graph.get_state(cfg).tasks[0].interrupts
    assert "unknown source_doc_id" in intr.value["error"]
    assert not store.jobs
    out = graph.invoke(Command(resume={"source_doc_id": "ro_efactura_ubl"}), cfg)
    assert out["job_id"] and len(store.jobs) == 1


def test_bon_cui_unclear_requires_exactly_one_choice(cat):
    store = InMemoryJobStore()
    graph = build_triage_graph(cat, store, checkpointer=MemorySaver())
    cfg = {"configurable": {"thread_id": "batch:t5"}}
    pack = _pack(source_doc_id="bon_fiscal", kinds=["jpeg"], our_role="n/a", counterparty_cui=None)
    graph.invoke({"pack": pack.model_dump()}, cfg)
    graph.invoke(Command(resume={"cu_cui": True, "fara_cui": True}), cfg)
    (intr,) = graph.get_state(cfg).tasks[0].interrupts
    assert intr.value["kind"] == "bon_cui_unclear" and "exactly one" in intr.value["error"]
    out = graph.invoke(Command(resume={"cu_cui": False, "fara_cui": True}), cfg)
    assert out["decision"]["emit"] and out["job_id"]
    assert out["decision"]["aisle"] == "30_bon/fara_cui/"


def test_graph_thread_prefix_is_batch(cat):
    graph = build_triage_graph(cat, InMemoryJobStore(), checkpointer=MemorySaver())
    with pytest.raises(ValueError, match="batch:"):
        _run(graph, "job:t4", {"pack": _pack().model_dump()})


def test_a2_aisles(cat):
    payroll = decide_emit(
        cat, _pack(source_doc_id="stat_salarii", kinds=["pdf"], our_role="n/a", identity_ok=True)
    )
    assert not payroll.emit and payroll.aisle == "55_salarii/2026-09/"
    nextup = decide_emit(
        cat, _pack(source_doc_id="sink_rj_nextup", kinds=["xlsx"], our_role="n/a", identity_ok=True)
    )
    assert not nextup.emit and nextup.aisle == "80_sink/nextup/"
