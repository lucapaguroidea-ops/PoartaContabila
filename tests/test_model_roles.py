"""Model roles (00_LAW §3.5): one pinned model per role; dry runs record and send nothing."""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest

from poarta_contabila.catalog import CatalogError, load_catalog
from poarta_contabila.model_roles import RouteRefused, load_roles, route_check
from tests.test_runtime import CUI, FOLDER, NEW_INVOICE, Ops, _runtime

CATALOG = Path(__file__).resolve().parents[1] / "catalog"
MODEL = "vendor/model-2026-09-15"  # placeholder id for tests; the owner picks real ones


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _pinned(cat, model=MODEL, **over):
    roles = {
        rid: r.model_copy(update={"model": model, **over}) for rid, r in cat.model_roles.items()
    }
    return dataclasses.replace(cat, model_roles=roles)


# ----- catalog -----


def test_every_model_call_site_has_one_role(cat):
    roles = cat.model_roles
    assert {r.role_id for r in roles.values() if r.status == "wired"} == {
        "jev_v3_judge",
        "jev_v2_gate",
        "jev_recon_review",
    }
    assert {r.pack for r in roles.values() if r.status == "wired"} == {
        "v3_judge",
        "v2_declaration_gate",
        "recon_review",
    }
    assert all(r.model is None for r in roles.values())  # chosen by the owner, not guessed
    assert all(r.provider.allow_fallbacks is False for r in roles.values())
    assert {r.system for r in roles.values()} == {"system_one", "system_two", "document_reading"}


@pytest.mark.parametrize(
    "model", ["openrouter/auto", "deepseek/deepseek-chat:free", "x/model-latest", "  "]
)
def test_an_alias_or_auto_model_is_refused(model):
    doc = {
        "roles": [
            {
                "role_id": "r",
                "graph_id": "monthly_close",
                "node": "layer2",
                "system": "system_one",
                "pack": "v2_declaration_gate",
                "output": "x",
                "status": "wired",
                "model": model,
            }
        ]
    }
    with pytest.raises(ValueError, match="exact model id"):
        load_roles(doc)


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"fallback_models": ["a/b"]}, "fallback"),
        ({"system": "system_two", "family": None}, "names its family"),
        ({"family": "deepseek"}, "is not system_one"),
        ({"pack": None}, "names its pack"),
        ({"provider": {"allow_fallbacks": True}}, "allow_fallbacks"),
    ],
)
def test_a_role_row_that_breaks_the_rules_is_refused(change, match):
    row = {
        "role_id": "r",
        "graph_id": "monthly_close",
        "node": "layer2",
        "system": "system_one",
        "pack": "v2_declaration_gate",
        "output": "x",
        "status": "wired",
        "model": None,
        **change,
    }
    with pytest.raises(ValueError, match=match):
        load_roles({"roles": [row]})


def test_a_role_on_an_unknown_graph_does_not_load(tmp_path):
    root = tmp_path / "catalog"
    shutil.copytree(CATALOG, root)
    path = root / "50_control" / "ARTICOLE_MODEL_ROLES_v1.yaml"
    path.write_text(path.read_text().replace("graph_id: monthly_close", "graph_id: no_such"))
    with pytest.raises(CatalogError, match="unknown graph_id 'no_such'"):
        load_catalog(root)


# ----- route_check -----


def test_route_check_fails_closed(cat):
    role = cat.model_roles["jev_v3_judge"]
    with pytest.raises(RouteRefused, match="'off'"):
        route_check(role.model_copy(update={"model": MODEL}), tenant_synthetic=True, mode="off")
    with pytest.raises(RouteRefused, match="no model chosen"):
        route_check(role, tenant_synthetic=True, mode="dry")
    with pytest.raises(RouteRefused, match="EU route"):
        route_check(role.model_copy(update={"model": MODEL}), tenant_synthetic=False, mode="dry")
    route_check(role.model_copy(update={"model": MODEL}), tenant_synthetic=True, mode="dry")


# ----- dry run on the real flow -----


def _ops(cat, *, mode="dry", data_class="synthetic", model=MODEL):
    rt = _runtime(_pinned(cat, model) if model else cat, model_mode=mode)
    o = Ops(rt)
    body = {"cui": CUI, "name": "FIRMA TEST SRL", "saga_firm_folder": FOLDER}
    if data_class:
        body["data_class"] = data_class
    o.http.put(f"/tenants/{CUI}", json=body, headers=o.op)
    o.upload_rj()
    return o


def _calls(o, role=None):
    params = {"role": role} if role else {}
    return o.http.get("/model-calls", params=params, headers=o.op).json()


def test_dry_run_records_what_jev_would_get_and_a_person_is_asked(cat):
    o = _ops(cat)
    out = o.ingest(NEW_INVOICE).json()
    assert out["question"]["kind"] == "v3_approve"  # no answer came: a person is asked
    assert "dry run" in out["question"]["judge"]["judge"]
    (call,) = _calls(o, "jev_v3_judge")
    assert call["status"] == "recorded" and call["model"] == MODEL and call["mode"] == "dry"
    assert call["provider"] == {"only": [], "allow_fallbacks": False, "data_collection": "deny"}
    assert call["tenant_cui"] == CUI and call["pack"] == "v3_judge"
    assert call["input"]["document"]["number"] == "AB 0099"  # exactly what Jev would see
    assert "job_id" not in call["input"]["document"]


def test_a_client_tenant_is_refused_and_the_refusal_recorded(cat):
    o = _ops(cat, data_class=None)  # data_class unset = client data
    o.ingest(NEW_INVOICE)
    (call,) = _calls(o, "jev_v3_judge")
    assert call["status"] == "refused" and "EU route" in call["reason"]


def test_a_role_without_a_model_is_refused(cat):
    o = _ops(cat, model=None)
    o.ingest(NEW_INVOICE)
    (call,) = _calls(o, "jev_v3_judge")
    assert call["status"] == "refused" and "no model chosen" in call["reason"]


def test_calls_off_records_nothing(cat):
    o = _ops(cat, mode="off")
    out = o.ingest(NEW_INVOICE).json()
    assert out["question"]["judge"]["judge"] == "not wired"
    assert _calls(o) == []


def test_recon_review_goes_through_its_role_and_abstains(cat):
    rt = _runtime(_pinned(cat), model_mode="dry")
    o = Ops(rt)
    body = {"cui": CUI, "name": "F", "saga_firm_folder": FOLDER, "data_class": "synthetic"}
    o.http.put(f"/tenants/{CUI}", json=body, headers=o.op)
    job_id = o.ingest(NEW_INVOICE).json()["job"]["job_id"]  # no books: waits at PRE
    o.upload_rj()
    view = o.http.post(f"/recon/{CUI}/2026-09", headers=o.op).json()
    assert view["settled"] == [{"job_id": job_id, "verdict": "absent", "by": "det"}]
    (call,) = _calls(o, "jev_recon_review")
    assert call["status"] == "recorded" and call["input"]["det"]["verdict"] == "absent"


def test_model_roles_view_never_shows_a_key(cat, monkeypatch):
    monkeypatch.setenv("OPENROUTER_JEV_API_KEY", "sk-or-test-secret")
    o = _ops(cat)
    resp = o.http.get("/model-roles", headers=o.op)
    assert "sk-or-test-secret" not in resp.text
    roles = {r["role_id"]: r for r in resp.json()}
    assert roles["jev_v3_judge"]["key_set"] is True
    assert roles["sys2_explain_approve"]["key_set"] is False
    assert roles["jev_v3_judge"]["callable_in_dry_run"] is True


# ----- role cards (WP-25) -----


def _row(system="system_one", **over):
    base = {
        "role_id": "r",
        "graph_id": "monthly_close",
        "node": "layer2",
        "system": system,
        "output": "x",
        "status": "not_wired",
        "pack": None,
        "model": None,
    }
    if system == "system_one":
        base["card"] = {
            "questions": {"q": {"type": "noul", "instructions": "Is it?"}},
            "fields": {"f": "q"},
        }
    elif system == "system_two":
        base["family"] = "deepseek"
        base["card"] = {
            "task": "Explain.",
            "limits": ["You do not decide."],
            "output_fields": ["explanation", "facts_cited", "missing"],
        }
    else:
        base["card"] = {"instructions": ["Copy what is printed."], "output": {"a": "b"}}
    base.update(over)
    return base


def test_wired_jev_cards_fill_exactly_their_closed_model(cat):
    from poarta_contabila.jev import PACKS

    for role in cat.model_roles.values():
        if role.status == "wired":
            assert set(role.card["fields"]) == set(PACKS[role.pack][1].model_fields)
            assert role.card["thresholds"] == {"noul_yes": 0.90, "choice": 0.80, "human": 0.10}


def test_system_two_roles_get_the_base_card_and_no_persona(cat):
    from poarta_contabila.model_roles import brief

    role = cat.model_roles["sys2_explain_recon"]
    assert role.card["output_fields"] == ["explanation", "facts_cited", "missing"]
    assert any("You do not decide" in limit for limit in role.card["limits"])
    text = brief(role)
    assert text.startswith("Reader: An accountant") and "Task: Explain this reconcile" in text
    assert "you are an" not in text.lower()
    assert brief(cat.model_roles["jev_v3_judge"]) is None


@pytest.mark.parametrize(
    ("row", "match"),
    [
        (
            _row(card={"questions": {"q": {"type": "choice"}}, "fields": {"f": "q"}}),
            "names no criteria",
        ),
        (
            _row(card={"questions": {"q": {"type": "noul"}}, "fields": {"f": "other"}}),
            "not asked",
        ),
        (
            _row(card={"questions": {"q": {"type": "guess"}}, "fields": {"f": "q"}}),
            "no type",
        ),
        (
            _row(
                card={
                    "questions": {"q": {"type": "noul", "criteria": {True: "x"}}},
                    "fields": {"f": "q"},
                }
            ),
            "not text",
        ),
        (
            _row(
                status="wired",
                pack="recon_review",
                card={"questions": {"q": {"type": "noul"}}, "fields": {"f": "q"}},
            ),
            "must be the pack's",
        ),
        (
            _row(
                "system_two",
                card={
                    "task": "You are an expert accountant. Explain.",
                    "limits": ["x"],
                    "output_fields": ["explanation", "facts_cited", "missing"],
                },
            ),
            "no persona",
        ),
        (
            _row(
                "system_two",
                card={
                    "task": "Explain.",
                    "limits": ["x"],
                    "output_fields": ["explanation", "recommendation"],
                },
            ),
            "output_fields must be exactly",
        ),
        (_row("system_two", card={"limits": ["x"]}), "has a task and limits"),
        (_row("document_reading", card={"instructions": ["x"]}), "an output shape"),
    ],
)
def test_a_card_the_role_cannot_honour_is_refused(row, match):
    with pytest.raises(ValueError, match=match):
        load_roles({"roles": [row]})


def test_a_changed_card_never_reuses_a_cached_answer(cat):
    from poarta_contabila.jev import input_hash, role_pin

    payload = {"x": 1}
    before = input_hash("v3_judge", payload, role_pin(_pinned(cat).model_roles)("v3_judge"))
    reworded = _pinned(cat)
    judge = reworded.model_roles["jev_v3_judge"]
    card = {**judge.card, "questions": {**judge.card["questions"]}}
    card["questions"]["needs_human"] = {"type": "noul", "instructions": "Reworded."}
    roles = {**reworded.model_roles, "jev_v3_judge": judge.model_copy(update={"card": card})}
    after = input_hash("v3_judge", payload, role_pin(roles)("v3_judge"))
    assert before != after
    other_model = role_pin(_pinned(cat, "vendor/model-2026-10-01").model_roles)("v3_judge")
    assert input_hash("v3_judge", payload, other_model) != before


def test_dry_run_records_the_card_and_its_questions(cat):
    o = _ops(cat)
    o.ingest(NEW_INVOICE)
    (call,) = _calls(o, "jev_v3_judge")
    role = cat.model_roles["jev_v3_judge"]
    assert call["card_hash"] == role.card_hash
    assert set(call["questions"]) == {"accounts_ok", "risk", "needs_human"}
    assert call["questions"]["risk"]["criteria"]["low"].startswith("A routine document")
    roles = {r["role_id"]: r for r in o.http.get("/model-roles", headers=o.op).json()}
    assert roles["jev_v3_judge"]["card_hash"] == role.card_hash
    assert roles["sys2_draft_rule"]["brief"].startswith("Reader:")


def test_postgres_model_call_store(cat):
    import os

    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    import psycopg

    from poarta_contabila.db import schema_sql
    from poarta_contabila.model_roles import PostgresModelCallStore, record

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(schema_sql())
        conn.execute("DELETE FROM domain.model_calls")
    store = PostgresModelCallStore(dsn)
    roles = _pinned(cat).model_roles
    judge, gate = roles["jev_v3_judge"], roles["jev_v2_gate"]
    store.add(
        record(
            judge, {"tenant_cui": CUI}, mode="dry", tenant_cui=CUI, status="recorded", reason="r"
        )
    )
    store.add(
        record(
            gate, {"diff": {"cui": CUI}}, mode="dry", tenant_cui=CUI, status="refused", reason="x"
        )
    )
    (got,) = store.recent("jev_v3_judge")
    assert got.card_hash == judge.card_hash and got.questions == judge.questions()
    assert {c.role_id for c in store.recent()} == {"jev_v3_judge", "jev_v2_gate"}


# ----- shadow roles at their place in the flow (WP-26) -----


def _roles_seen(o):
    return {c["role_id"]: c for c in _calls(o)}


def test_shadow_roles_record_at_triage_bind_and_the_approval_question(cat):
    o = _ops(cat)
    o.ingest(NEW_INVOICE)
    seen = _roles_seen(o)
    assert {"jev_source_doc", "jev_our_role", "jev_v3_classify", "sys2_explain_approve"} <= set(
        seen
    )
    assert "jev_flux" not in seen  # one articol matched: Jev is skipped (JevAnnex)
    for rid in ("jev_source_doc", "jev_our_role", "jev_v3_classify", "sys2_explain_approve"):
        assert seen[rid]["status"] == "recorded" and seen[rid]["reason"].startswith("shadow")
    assert seen["jev_our_role"]["input"]["supplier"]["cui"] == "20000005"
    explain = seen["sys2_explain_approve"]
    assert explain["input"]["kind"] == "v3_approve"
    assert explain["input"]["question"]["document"]["number"] == "AB 0099"
    assert explain["questions"] is None and explain["card_hash"]


def test_a_question_asked_again_is_recorded_once(cat):
    o = _ops(cat)
    job_id = o.ingest(NEW_INVOICE).json()["job"]["job_id"]
    o.resume(job_id, {"decision": "edit", "edit": None})  # refused: asked again
    assert len(_calls(o, "sys2_explain_approve")) == 1


def test_statement_upload_records_the_file_by_fingerprint_not_its_bytes(cat):
    import base64

    from tests.test_extras import META, PDF, TABLES

    o = _ops(cat)
    o.http.post(
        f"/extras/{CUI}",
        headers=o.op,
        json={"meta": META, "tables": TABLES, "pdf_b64": base64.b64encode(PDF).decode()},
    )
    (call,) = _calls(o, "ocr_extract")
    assert call["input"]["file"]["bytes"] == len(PDF) and len(call["input"]["file"]["sha256"]) == 64
    assert "pdf_b64" not in str(call["input"]) and call["input"]["header"]["iban"] == META["iban"]


def test_recon_and_close_questions_record_their_explainer(cat):
    o = _ops(cat)
    o.http.put(
        f"/tenants/{CUI}",
        json={"cui": CUI, "name": "F", "saga_firm_folder": FOLDER, "data_class": "synthetic"},
        headers=o.op,
    )
    from tests.test_runtime import INVOICE, _spv_zip

    o.ingest(_spv_zip(INVOICE))  # close to a journal line: waits at PRE
    o.http.post(f"/recon/{CUI}/2026-09", headers=o.op)
    (recon,) = _calls(o, "sys2_explain_recon")
    assert recon["input"]["kind"] == "recon_ambiguous"
    o.http.post(f"/close/{CUI}/2026-09", params={"tva": "tva_platitor"}, headers=o.op)
    (close,) = _calls(o, "sys2_explain_close")
    assert close["input"]["kind"] == "v2_close"


def test_shadow_recording_never_blocks_the_flow(cat):
    o = _ops(cat)

    def broken(call):
        raise RuntimeError("store down")

    o.rt.model_calls.add = broken
    out = o.ingest(NEW_INVOICE).json()
    assert out["question"]["kind"] == "v3_approve"  # the flow went on


def test_only_shadow_roles_are_observed(cat):
    from poarta_contabila.model_roles import InMemoryModelCallStore, ModelGateway

    calls = InMemoryModelCallStore()
    roles = _pinned(cat).model_roles
    gw = ModelGateway(roles=roles, calls=calls, mode="dry", synthetic=lambda cui: True)
    gw.observe("jev_v3_judge", {"tenant_cui": CUI}, CUI)  # wired: goes through Jev, not here
    gw.observe("ocr_decont_split", {"tenant_cui": CUI}, CUI)  # not_wired
    gw.observe("no_such_role", {"tenant_cui": CUI}, CUI)
    assert calls.rows == []
    ModelGateway(roles=roles, calls=calls, mode="off").observe("jev_our_role", {}, CUI)
    assert calls.rows == []
