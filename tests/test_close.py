"""WP-10: monthly_close — lock, Layer 1, Layer 2 suggests only, a person decides V2."""

from __future__ import annotations

import os

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from poarta_contabila.catalog import load_catalog
from poarta_contabila.close import CloseDeps, InMemoryCloseStore, build_close_graph
from poarta_contabila.rules import InMemoryRuleStore, RuleBody
from tests.test_controls import CUI, PAYER, PERIOD, PURCHASE, SALE, CleanEye, _exp, _sd

CFG = {"configurable": {"thread_id": f"close:{CUI}:{PERIOD}"}}


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


class Month:
    def __init__(self, cat, expected, sink, *, jev=None, rules=None):
        self.expected, self.sink = list(expected), list(sink)
        self.store = InMemoryCloseStore()
        self.graph = build_close_graph(
            CloseDeps(
                catalog=cat,
                store=self.store,
                expected=lambda cui, period: self.expected,
                eye=lambda cui, period: CleanEye(self.sink),
                rules=rules,
                jev_v2=jev or (lambda diff: None),
            ),
            checkpointer=MemorySaver(),
        )

    def start(self, axes=PAYER):
        return self.graph.invoke({"cui": CUI, "period": PERIOD, "axes": axes}, CFG)

    def answer(self, body):
        return self.graph.invoke(Command(resume=body), CFG)

    def question(self):
        tasks = self.graph.get_state(CFG).tasks
        return tasks[0].interrupts[0].value if tasks and tasks[0].interrupts else None

    @property
    def run(self):
        return self.store.get(CUI, PERIOD)


def _clean(cat, **kw):
    return Month(
        cat,
        [_exp(*PURCHASE), _exp(*SALE, doc_class="iesire", n=2)],
        [_sd(*PURCHASE), _sd(*SALE, doc_class="iesire")],
        **kw,
    )


def test_thread_is_close_cui_period(cat):
    m = _clean(cat)
    with pytest.raises(ValueError, match="close:"):
        m.graph.invoke(
            {"cui": CUI, "period": PERIOD, "axes": PAYER}, {"configurable": {"thread_id": "job:x"}}
        )


def test_clean_month_files_then_v4(cat):
    m = _clean(cat)
    m.start()
    q = m.question()
    assert q["kind"] == "v2_close" and q["material"] is False
    assert m.run.status == "v2_ready" and m.run.close_kind == "close_standard"
    m.answer({"action": "file", "explained_rule": None})
    assert m.question()["kind"] == "v4_codit" and m.run.status == "filed"
    m.answer({"accept": True, "skip": False, "edit": None, "seed_next": None})
    assert m.run.status == "v4_done" and m.run.v4["accept"] is True


def test_material_month_cannot_be_filed(cat):
    m = Month(cat, [_exp(*PURCHASE)], [_sd(*PURCHASE), _sd("Z-9", "2026-09-20", "50.00", "8.68")])
    m.start()
    assert m.question()["material"] is True and m.question()["unexplained"] == ["saga:Z-9"]
    m.answer({"action": "file", "explained_rule": None})
    q = m.question()
    assert q["kind"] == "v2_close" and "cannot file" in q["error"]
    m.answer({"action": "hold", "explained_rule": None})
    assert m.run.status == "hold" and m.question() is None


def test_jev_file_on_a_material_month_is_ignored(cat):
    def jev(diff):
        return {"books_support_declaration": True, "gap_materiality": "none", "action": "file"}

    m = Month(cat, [_exp(*PURCHASE)], [], jev=jev)  # purchase not in the books: hole
    m.start()
    q = m.question()
    assert q["material"] is True
    assert q["jev"]["action"] is None and "may not clear material" in q["jev"]["ignored"]
    m.answer({"action": "file", "explained_rule": None})
    assert "cannot file" in m.question()["error"]


def test_layer2_must_be_v2gate_json(cat):
    m = _clean(cat, jev=lambda diff: '{"action": "file", "confidence": 0.99}')
    m.start()
    assert "not V2Gate JSON" in m.question()["jev"]["ignored"]
    ok = _clean(
        cat,
        jev=lambda diff: (
            '{"books_support_declaration": true, "gap_materiality": "none", "action": "file"}'
        ),
    )
    ok.start()
    assert ok.question()["jev"]["action"] == "file"  # a suggestion; the person still answers


def test_explained_rule_in_the_answer_must_exist(cat):
    rules = InMemoryRuleStore()
    m = _clean(cat, rules=rules)
    m.start()
    m.answer({"action": "hold", "explained_rule": "comisioane"})
    assert "POST /rules" in m.question()["error"]
    rules.add(
        CUI,
        "comisioane",
        RuleBody.model_validate(
            {"description": "Comisioane", "scope": "document", "document": {"number_prefix": "COM"}}
        ),
    )
    m.answer({"action": "hold", "explained_rule": "comisioane"})
    assert m.run.explained_rule == "comisioane"


def test_unknown_axes_block_the_close(cat):
    m = _clean(cat)
    m.start(axes={})
    q = m.question()
    assert q["material"] is True and any("no close kind" in b for b in q["blockers"])


def test_changed_month_after_the_lock_is_a_mismatch_until_reopened(cat):
    m = _clean(cat)
    m.start()
    m.answer({"action": "hold", "explained_rule": None})
    m.expected.append(_exp("N-1", "2026-09-25", "10.00", "0.00", n=3, status="acked"))
    m.sink.append(_sd("N-1", "2026-09-25", "10.00", "0.00"))
    m.start()
    assert any("lock mismatch" in b for b in m.question()["blockers"])
    m.answer({"action": "file", "explained_rule": None})
    assert "cannot file" in m.question()["error"]
    m.answer({"action": "reopen", "explained_rule": None})
    assert m.run.status == "opened" and m.run.expected_set_hash is None
    m.start()  # locks the month afresh
    assert m.question()["material"] is False


def test_close_routes_over_the_runtime(cat):
    from tests.test_runtime import Ops, _runtime

    o = Ops(_runtime(cat))
    o.tenant()
    o.upload_rj()
    out = o.http.post(f"/close/{CUI}/{PERIOD}", params={"tva": "tva_platitor"}, headers=o.op).json()
    assert out["question"]["kind"] == "v2_close" and out["run"]["status"] == "v2_ready"
    again = o.http.post(f"/close/{CUI}/{PERIOD}", headers=o.op).json()
    assert again["question"] == out["question"]  # waiting on a person: not restarted
    done = o.http.post(
        f"/close/{CUI}/{PERIOD}/resume",
        headers=o.op,
        json={"action": "hold", "explained_rule": None},
    ).json()
    assert done["run"]["status"] == "hold" and done["question"] is None


def test_postgres_close_store(cat):
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    from poarta_contabila.close import CloseRun, PostgresCloseStore
    from poarta_contabila.jobs import PostgresJobStore

    PostgresJobStore(dsn, reset=True)
    store = PostgresCloseStore(dsn)
    assert store.get(CUI, PERIOD) is None
    store.put(CloseRun(cui=CUI, period=PERIOD, status="locked", expected_set_hash="h1"))
    store.put(CloseRun(cui=CUI, period=PERIOD, status="hold", expected_set_hash="h1"))
    assert store.get(CUI, PERIOD).status == "hold"


# ----- V4 after file: patch the filed period on may_patch, seed the next -----


def _filed_with_codit(cat):
    from poarta_contabila.codit import AxisValue, CoditInput, InMemoryCoditStore, write_codit

    def a(v):
        return AxisValue(value=v, certainty="confirmed", as_of="2026-09-01", source="test")

    codits = InMemoryCoditStore()
    axes = {"forma": a("srl"), "impozit": a("micro_1"), "tva": a("tva_platitor")}
    codits.put(write_codit(cat, CUI, PERIOD, CoditInput(axes=axes)))
    m = _clean(cat)
    m.graph = build_close_graph(
        CloseDeps(
            catalog=cat,
            store=m.store,
            expected=lambda cui, period: m.expected,
            eye=lambda cui, period: CleanEye(m.sink),
            codit=codits.get,
            codit_put=codits.put,
        ),
        checkpointer=MemorySaver(),
    )
    m.start()
    m.answer({"action": "file", "explained_rule": None})
    assert m.question()["kind"] == "v4_codit"
    return m, codits, a


def test_v4_question_proposes_what_it_may_patch_and_seed(cat):
    m, _, _ = _filed_with_codit(cat)
    proposal = m.question()["proposal"]
    assert proposal["may_patch"] == ["auto", "saf_t", "exig"]
    assert set(proposal["seed_next"]) == {"impozit", "tva"}


def test_v4_patches_the_filed_period_on_may_patch_only(cat):
    m, codits, a = _filed_with_codit(cat)
    m.answer(
        {
            "accept": True,
            "skip": False,
            "edit": {"tva": a("tva_neplatitor").model_dump()},
            "seed_next": None,
        }
    )
    assert "may patch only" in m.question()["error"]  # asked again, nothing written
    assert codits.get(CUI, PERIOD).saf_t is None
    m.answer({"accept": True, "skip": False, "edit": {"saf_t": True}, "seed_next": None})
    doc = codits.get(CUI, PERIOD)
    assert doc.saf_t is True and doc.derive()["tva"] == "tva_platitor"
    assert m.run.status == "v4_done" and m.run.v4["patched_hash"] == doc.hash


def test_v4_refuses_a_patch_a_hard_pair_forbids(cat):
    m, codits, a = _filed_with_codit(cat)
    m.answer(
        {"accept": True, "skip": False, "edit": {"exig": a(None).model_dump()}, "seed_next": None}
    )
    assert "T3" in m.question()["error"]  # a payer with exig emptied
    assert codits.get(CUI, PERIOD).derive()["exig"] == "tva_exig_livrare"


def test_v4_seeds_the_next_period_once_and_never_overwrites(cat):
    m, codits, a = _filed_with_codit(cat)
    m.answer(
        {
            "accept": True,
            "skip": False,
            "edit": None,
            "seed_next": {"impozit": a("profit_16").model_dump()},
        }
    )
    nxt = codits.get(CUI, "2026-10")
    assert {k: nxt.derive()[k] for k in ("exig", "impozit", "tva")} == {
        "exig": "tva_exig_livrare",
        "impozit": "profit_16",
        "tva": "tva_platitor",
    }
    assert nxt.axes["tva"].source == f"seeded by V4 from {PERIOD}"
    assert nxt.derive()["forma"] == "srl"  # the profile travels whole; impozit changed
    assert m.run.v4["seeded_period"] == "2026-10"

    other, codits2, a2 = _filed_with_codit(cat)
    from poarta_contabila.codit import CoditInput, write_codit

    codits2.put(write_codit(cat, CUI, "2026-10", CoditInput(axes={"tva": a2("tva_neplatitor")})))
    other.answer({"accept": True, "skip": False, "edit": None, "seed_next": {}})
    assert "does not overwrite" in other.question()["error"]
    assert codits2.get(CUI, "2026-10").derive()["tva"] == "tva_neplatitor"


@pytest.mark.parametrize(
    ("body", "match"),
    [
        (
            {"accept": False, "skip": False, "edit": None, "seed_next": None},
            "choose accept or skip",
        ),
        ({"accept": True, "skip": True, "edit": None, "seed_next": None}, "choose accept or skip"),
        (
            {"accept": False, "skip": True, "edit": {"saf_t": True}, "seed_next": None},
            "skip writes",
        ),
    ],
)
def test_v4_answer_must_be_one_clear_choice(cat, body, match):
    m, codits, _ = _filed_with_codit(cat)
    before = codits.get(CUI, PERIOD).hash
    m.answer(body)
    assert match in m.question()["error"] and codits.get(CUI, PERIOD).hash == before


def test_v4_skip_writes_nothing(cat):
    m, codits, _ = _filed_with_codit(cat)
    before = codits.get(CUI, PERIOD).hash
    m.answer({"accept": False, "skip": True, "edit": None, "seed_next": None})
    assert m.run.status == "v4_done" and codits.get(CUI, PERIOD).hash == before
    assert codits.get(CUI, "2026-10") is None


def test_v4_seed_carries_a_micro_firm_and_its_default_exig_follows_tva(cat):
    m, codits, a = _filed_with_codit(cat)
    m.answer({"accept": True, "skip": False, "edit": None, "seed_next": {}})
    nxt = codits.get(CUI, "2026-10")
    assert nxt.derive()["impozit"] == "micro_1" and nxt.derive()["forma"] == "srl"
    other, codits2, a2 = _filed_with_codit(cat)
    other.answer(
        {
            "accept": True,
            "skip": False,
            "edit": None,
            "seed_next": {"tva": a2("tva_neplatitor").model_dump()},
        }
    )
    assert "exig" not in codits2.get(CUI, "2026-10").derive()  # the default followed tva
