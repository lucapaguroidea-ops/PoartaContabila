"""WP-20: Jev Layer 1 (v3_judge) and Layer 2 (v2_declaration_gate) — JSON only, closed
models, cached on (pack, input_hash), fail closed. The transport is mocked: the wire is not
built until it is read from the official docs."""

from __future__ import annotations

import os

import pytest
from langgraph.types import Command

from poarta_contabila.catalog import load_catalog
from poarta_contabila.jev import (
    PACKS,
    InMemoryJevCache,
    Jev,
    JevError,
    input_hash,
    jev_from_env,
    judge_input,
    make_judge,
    make_v2,
    validate,
)
from poarta_contabila.sinks.saga_xml import fixture_documents
from tests.test_close import Month, _clean
from tests.test_controls import PURCHASE, _exp
from tests.test_ingest import World

CONFIDENT = {"accounts_ok": True, "risk": "low", "needs_human": False}
FILE_IT = {"books_support_declaration": True, "gap_materiality": "none", "action": "file"}


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


class FakeTransport:
    """Answers in order (the last one repeats); an exception instance is raised."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, pack, payload, timeout_s):
        self.calls.append((pack, payload))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


# ----- closed models, JSON only -----


@pytest.mark.parametrize(
    "raw",
    [
        {**CONFIDENT, "confidence": 0.99},  # extra key
        {**CONFIDENT, "accounts_ok": "true"},  # not coerced
        {**CONFIDENT, "risk": "unknown"},  # off the closed list
        {"accounts_ok": True, "needs_human": False},  # missing key
        "the accounts look fine",  # not JSON
        [CONFIDENT],  # not an object
        None,
    ],
)
def test_an_answer_must_be_the_closed_model(raw):
    with pytest.raises(JevError):
        validate("v3_judge", raw)


def test_json_text_and_objects_validate():
    assert validate("v3_judge", CONFIDENT).risk == "low"
    assert validate("v3_judge", b'{"accounts_ok": true, "risk": "high", "needs_human": true}')
    assert validate("v2_declaration_gate", FILE_IT).action == "file"


# ----- cache on (pack, input_hash) -----


def test_the_same_question_is_paid_for_once():
    transport = FakeTransport(CONFIDENT)
    jev = Jev(transport=transport)
    first = jev.ask("v3_judge", {"x": 1})
    again = jev.ask("v3_judge", {"x": 1})
    assert not first.cached and again.cached and len(transport.calls) == 1
    assert again.input_hash == first.input_hash == input_hash("v3_judge", {"x": 1})
    jev.ask("v3_judge", {"x": 2})
    assert len(transport.calls) == 2


def test_a_new_pack_version_does_not_reuse_answers(monkeypatch):
    before = input_hash("v3_judge", {"x": 1})
    monkeypatch.setitem(PACKS, "v3_judge", ("2", PACKS["v3_judge"][1]))
    assert input_hash("v3_judge", {"x": 1}) != before


def test_an_invalid_answer_is_not_cached():
    transport = FakeTransport({"accounts_ok": True}, CONFIDENT)
    jev = Jev(transport=transport)
    with pytest.raises(JevError, match="not V3Judge JSON"):
        jev.ask("v3_judge", {"x": 1})
    assert not jev.cache.rows
    assert jev.ask("v3_judge", {"x": 1}).body.risk == "low"
    assert len(transport.calls) == 2


def test_a_cache_row_the_model_refuses_is_asked_again():
    cache = InMemoryJevCache()
    cache.put("v3_judge", input_hash("v3_judge", {"x": 1}), {"accounts_ok": True})
    transport = FakeTransport(CONFIDENT)
    assert not Jev(transport=transport, cache=cache).ask("v3_judge", {"x": 1}).cached


def test_the_document_identity_is_not_in_the_question(cat):
    doc = fixture_documents()["iesire"]
    other = doc.model_copy(update={"job_id": "another-job"})
    articol = cat.articol("ro_efactura_outbound")
    assert judge_input(doc, articol) == judge_input(other, articol)
    assert "job_id" not in judge_input(doc, articol)["document"]
    assert "iesire_factura_xml" in judge_input(doc, articol)["articol"]["write_modules"]


def test_unknown_pack_is_refused():
    with pytest.raises(JevError, match="unknown Jev pack"):
        Jev(transport=FakeTransport(CONFIDENT)).ask("v3_classify", {})


# ----- Layer 1: fail closed -----


@pytest.mark.parametrize(
    "answer, says",
    [
        (TimeoutError("read timed out"), "TimeoutError"),
        (ConnectionError("refused"), "ConnectionError"),
        ('{"accounts_ok": true}', "not V3Judge JSON"),
    ],
)
def test_layer1_without_an_answer_asks_a_person(cat, answer, says):
    verdict = make_judge(Jev(transport=FakeTransport(answer)))(
        fixture_documents()["iesire"], cat.articol("ro_efactura_outbound")
    )
    assert verdict["needs_human"] is True and verdict["accounts_ok"] is False
    assert says in verdict["judge"]


def test_layer1_not_wired_asks_a_person(cat):
    verdict = make_judge(None)(fixture_documents()["iesire"], cat.articol("ro_efactura_outbound"))
    assert verdict["needs_human"] is True and verdict["judge"] == "not wired"


def test_env_wiring_sends_nothing_until_the_wire_is_documented(cat, monkeypatch):
    monkeypatch.delenv("JEV_BASE_URL", raising=False)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    assert jev_from_env(InMemoryJevCache()) is None
    monkeypatch.setenv("JEV_BASE_URL", "https://jev.invalid")
    assert jev_from_env(InMemoryJevCache()) is None  # both are needed
    monkeypatch.setenv("JEV_API_KEY", "test-key")
    jev = jev_from_env(InMemoryJevCache())
    verdict = make_judge(jev)(fixture_documents()["iesire"], cat.articol("ro_efactura_outbound"))
    assert verdict["needs_human"] is True and "official docs" in verdict["judge"]
    assert not jev.cache.rows


def _past_first_n(w, cat):
    first_n = cat.articol("ro_efactura_outbound")["first_n"]
    w.jobs.packaged_count = lambda cui, articol_id: first_n


def test_confident_jev_packages_past_first_n(cat):
    transport = FakeTransport(CONFIDENT)
    w = World(cat, judge=make_judge(Jev(transport=transport)))
    _past_first_n(w, cat)
    job, doc = w.emit()
    _, out = w.run(job, doc)
    assert out["status"] == "packaged" and out["judge"]["judge"] == "jev"
    assert len(transport.calls) == 1


def test_jev_needs_human_asks_with_its_verdict(cat):
    w = World(
        cat,
        judge=make_judge(
            Jev(transport=FakeTransport({**CONFIDENT, "risk": "high", "needs_human": True}))
        ),
    )
    _past_first_n(w, cat)
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    question = w.interrupt(cfg)
    assert question["kind"] == "v3_approve" and question["judge"]["risk"] == "high"
    assert w.blobs.puts == 0


def test_a_resume_never_asks_jev_again(cat):
    """The verdict is on the thread before the question: a replay that would now get a
    confident answer cannot skip the question and drop the person's answer."""
    transport = FakeTransport(TimeoutError("read timed out"), CONFIDENT)
    w = World(cat, judge=make_judge(Jev(transport=transport)))
    _past_first_n(w, cat)
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    assert w.interrupt(cfg)["kind"] == "v3_approve"
    out = w.graph.invoke(Command(resume={"decision": "reject", "edit": None}), cfg)
    assert out["status"] == "rejected" and w.jobs.get(job.job_id).status == "rejected"
    assert len(transport.calls) == 1 and w.blobs.puts == 0


def test_a_judge_that_raises_asks_a_person(cat):
    def judge(doc, articol):
        raise RuntimeError("boom")

    w = World(cat, judge=judge)
    _past_first_n(w, cat)
    job, doc = w.emit()
    cfg, _ = w.run(job, doc)
    question = w.interrupt(cfg)
    assert question["kind"] == "v3_approve" and "boom" in question["judge"]["judge"]


# ----- Layer 2 -----


def _v2(transport, axes=None):
    return make_v2(Jev(transport=transport), lambda cui, period: axes or {"tva": "platitor"})


def test_layer2_suggests_once_and_the_person_decides(cat):
    transport = FakeTransport(FILE_IT)
    m = _clean(cat, jev=_v2(transport))
    m.start()
    q = m.question()
    assert q["kind"] == "v2_close" and q["jev"]["action"] == "file"
    ((pack, payload),) = transport.calls
    assert pack == "v2_declaration_gate" and payload["axes"] == {"tva": "platitor"}
    m.answer({"action": "hold", "explained_rule": None})  # the suggestion is not the decision
    assert m.run.status == "hold" and m.run.jev["action"] == "file"
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "answer, says",
    [
        (TimeoutError("read timed out"), "Layer 2 unavailable: JevError"),
        ({**FILE_IT, "confidence": 0.9}, "not V2Gate JSON"),
    ],
)
def test_layer2_without_an_answer_is_no_suggestion(cat, answer, says):
    m = _clean(cat, jev=_v2(FakeTransport(answer)))
    m.start()
    q = m.question()
    assert q["kind"] == "v2_close" and says in q["jev"]["ignored"]
    assert "action" not in q["jev"]


def test_layer2_cannot_clear_material(cat):
    m = Month(cat, [_exp(*PURCHASE)], [], jev=_v2(FakeTransport(FILE_IT)))  # hole: material
    m.start()
    q = m.question()
    assert q["material"] is True
    jev = q["jev"]
    assert jev["action"] is None and jev["gap_materiality"] is None
    assert jev["books_support_declaration"] is None and "may not clear material" in jev["ignored"]
    m.answer({"action": "file", "explained_rule": None})
    assert "cannot file" in m.question()["error"]


def test_layer2_material_answer_on_a_material_month_stands(cat):
    hold = {"books_support_declaration": False, "gap_materiality": "material", "action": "hold"}
    m = Month(cat, [_exp(*PURCHASE)], [], jev=_v2(FakeTransport(hold)))
    m.start()
    assert m.question()["jev"] == hold


# ----- runtime + Postgres -----


def test_runtime_wires_jev_into_both_layers(cat):
    from tests.test_runtime import _runtime

    rt = _runtime(cat, jev=Jev(transport=FakeTransport(CONFIDENT)))
    verdict = rt.deps.judge(fixture_documents()["iesire"], cat.articol("ro_efactura_outbound"))
    assert verdict["judge"] == "jev"
    unwired = _runtime(cat)
    verdict = unwired.deps.judge(fixture_documents()["iesire"], cat.articol("ro_efactura_outbound"))
    assert verdict["judge"] == "not wired"


def test_postgres_cache_keeps_the_first_answer():
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    import psycopg

    from poarta_contabila.db import schema_sql
    from poarta_contabila.jev import PostgresJevCache

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(schema_sql())
        conn.execute("DELETE FROM domain.jev_answers")
    transport = FakeTransport(CONFIDENT)
    jev = Jev(transport=transport, cache=PostgresJevCache(dsn))
    assert not jev.ask("v3_judge", {"x": 1}).cached
    fresh = Jev(transport=FakeTransport(TimeoutError("down")), cache=PostgresJevCache(dsn))
    assert fresh.ask("v3_judge", {"x": 1}).cached  # another process: no second call
    PostgresJevCache(dsn).put("v3_judge", input_hash("v3_judge", {"x": 1}), {"risk": "high"})
    assert fresh.ask("v3_judge", {"x": 1}).body.risk == "low"


def test_layer2_sees_the_declarations_due_for_the_period(cat):
    from poarta_contabila.filings import due_filings

    transport = FakeTransport(FILE_IT)
    v2 = make_v2(
        Jev(transport=transport),
        lambda cui, period: {"tva": "tva_platitor", "impozit": "micro_1"},
        lambda axes: due_filings(cat, axes),
    )
    m = _clean(cat, jev=v2)
    m.start()
    ((_, payload),) = transport.calls
    due = {f["filing_id"]: f["books_gate"] for f in payload["filings_due"]}
    assert "d300_platitor" in due and "d100_profit" not in due  # micro, not profit
    assert "C0_synthetic_parity" in due["d300_platitor"]
    assert list(due) == sorted(due)  # stable order: the same month asks the same question
