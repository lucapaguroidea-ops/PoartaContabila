"""A2: an expense report (decont) is a container — split into child packs, never emitted."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from poarta_contabila.catalog import load_catalog
from poarta_contabila.jobs import InMemoryJobStore
from poarta_contabila.triage import Pack, build_triage_graph, decide_emit

CUI = "1000009"  # invented, valid check digit
PARTNER = "20000005"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _container(**over) -> Pack:
    base = dict(
        tenant_cui=CUI,
        saga_firm_folder="0001",
        period="2026-09",
        source_hash="d" * 64,
        source_doc_id="decont_cheltuieli",
        kinds=["xls", "pdf", "msg"],
        our_role="inbound",
        identity_ok=True,
    )
    base.update(over)
    return Pack(**base)


def _part(n: int, source_doc_id: str, kinds: list[str], **over) -> dict:
    return {
        "part_hash": f"{n:x}" * 64 if n < 16 else f"{n:064x}",
        "source_doc_id": source_doc_id,
        "kinds": kinds,
        "bon_our_cui_on_doc": over.get("bon"),
        "counterparty_cui": over.get("cui"),
    }


PARTS = [
    _part(1, "bon_fiscal", ["jpeg"], bon=True),
    _part(2, "bon_fiscal", ["pdf"], bon=False),
    _part(3, "ro_efactura_ubl", ["ubl_spv", "pdf"], cui=PARTNER),
    _part(4, "ro_efactura_pdf", ["pdf"]),
    _part(5, "foreign_invoice", ["pdf"]),
    _part(6, "workings", ["xlsx"]),
]


class Run:
    def __init__(self, cat, pack=None):
        self.store = InMemoryJobStore()
        self.graph = build_triage_graph(cat, self.store, checkpointer=MemorySaver())
        self.cfg = {"configurable": {"thread_id": "batch:decont-1"}}
        self.out = self.graph.invoke({"pack": (pack or _container()).model_dump()}, self.cfg)

    def question(self):
        tasks = self.graph.get_state(self.cfg).tasks
        return tasks[0].interrupts[0].value if tasks and tasks[0].interrupts else None

    def answer(self, parts):
        self.out = self.graph.invoke(Command(resume={"parts": parts}), self.cfg)
        return self.out


def test_container_never_emits(cat):
    d = decide_emit(cat, _container())
    assert not d.emit and "class_gate" in d.failed
    assert d.aisle == "50_decont/2026-09/"


def test_graph_asks_for_the_parts_before_anything_is_emitted(cat):
    run = Run(cat)
    q = run.question()
    assert q["kind"] == "decont_split"
    assert "bon_fiscal" in q["children"] and "ro_efactura_ubl" in q["children"]
    assert run.store.jobs == {}


def test_parts_become_child_jobs_through_their_own_gates(cat):
    run = Run(cat)
    out = run.answer(PARTS)
    children = out["children"]
    by_doc = [(c["pack"]["source_doc_id"], c["decision"]["emit"], c["job_id"]) for c in children]
    emitted = [c for c in children if c["job_id"]]
    assert [c["decision"]["job_kind"] for c in emitted] == [
        "job_bon",
        "job_bon",
        "job_ro_efactura",
        "job_foreign_invoice",
    ]
    assert by_doc[3][:2] == ("ro_efactura_pdf", False)  # PDF only: waits for the XML
    assert children[3]["decision"]["aisle"] == "10_ro_efactura/_incomplete_spv/"
    assert by_doc[5][:2] == ("workings", False)  # evidence
    assert children[0]["decision"]["aisle"] == "30_bon/cu_cui/"
    assert children[1]["decision"]["aisle"] == "30_bon/fara_cui/"
    assert len(run.store.jobs) == 4
    for c in emitted:  # children keep the container's tenant, folder and period
        assert c["pack"]["tenant_cui"] == CUI and c["pack"]["period"] == "2026-09"
    assert children[2]["pack"]["our_role"] == "inbound"  # "either" in an expense report


def test_a_part_seen_again_is_not_a_second_job(cat):
    first = Run(cat)
    first.answer(PARTS[:1])
    again = Run(cat)
    again.store = first.store
    again.graph = build_triage_graph(cat, first.store, checkpointer=MemorySaver())
    again.out = again.graph.invoke({"pack": _container().model_dump()}, again.cfg)
    out = again.answer(PARTS[:1])
    assert out["children"][0]["created"] is False and len(first.store.jobs) == 1


@pytest.mark.parametrize(
    ("parts", "error"),
    [
        ([_part(1, "extras", ["pdf"])], "not one of"),
        ([_part(1, "ro_efactura_pdf", ["pdf", "ubl_spv"])], "XML exists"),
        ([_part(1, "bon_fiscal", ["jpeg"])], "bon_our_cui_on_doc"),
        ([_part(1, "bon_fiscal", ["jpeg"], bon=True)] * 2, "own hash"),
        ([{**_part(1, "bon_fiscal", ["jpeg"], bon=True), "part_hash": "d" * 64}], "own hash"),
        ([_part(1, "ro_efactura_ubl", ["ubl_spv"], cui="20000006")], "CUI"),
        ([], "at least 1"),
    ],
)
def test_bad_answers_are_asked_again(cat, parts, error):
    run = Run(cat)
    run.answer(parts)
    q = run.question()
    assert q is not None and q["kind"] == "decont_split"
    assert error in str(q["error"])
    assert run.store.jobs == {}


def test_report_that_is_not_the_tenants_is_not_split(cat):
    run = Run(cat, _container(identity_ok=False))
    assert run.question() is None
    assert "identity_gate" in run.out["decision"]["failed"] and not run.out.get("children")
