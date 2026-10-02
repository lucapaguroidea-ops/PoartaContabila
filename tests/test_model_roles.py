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
    (call,) = _calls(o)
    assert call["status"] == "refused" and "EU route" in call["reason"]


def test_a_role_without_a_model_is_refused(cat):
    o = _ops(cat, model=None)
    o.ingest(NEW_INVOICE)
    (call,) = _calls(o)
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
