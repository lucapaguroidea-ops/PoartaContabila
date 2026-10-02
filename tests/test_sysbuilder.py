"""WP-38: the owner's token names, and the build agent's token — synthetic tenants only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from poarta_contabila.app import create_app, env_token
from poarta_contabila.catalog import load_catalog
from poarta_contabila.smoke import run
from tests.test_runtime import CUI, NEW_INVOICE, _runtime

OP, AG, SB = "o" * 40, "a" * 40, "s" * 40
CLIENT = "20000005"  # invented, valid check digit; registered as client data


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


class Two:
    """One app, two callers: the owner (operator token) and the build agent (sysbuilder)."""

    def __init__(self, cat, sysbuilder=SB):
        self.rt = _runtime(cat, model_mode="dry")
        app = create_app(
            None, runtime=self.rt, operator_token=OP, agent_token=AG, sysbuilder_token=sysbuilder
        )
        self.owner = TestClient(app, headers={"Authorization": f"Bearer {OP}"})
        self.builder = TestClient(app, headers={"Authorization": f"Bearer {SB}"})
        self.owner.put(
            f"/tenants/{CLIENT}",
            json={"cui": CLIENT, "name": "CLIENT REAL SRL", "saga_firm_folder": "0002"},
        )


def test_the_owners_names_are_read_and_the_old_ones_only_as_a_fallback(monkeypatch):
    for name in ("GRAPHUSERTOKEN_OPERATOR", "OPERATOR_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPERATOR_TOKEN", "old")
    assert env_token(("GRAPHUSERTOKEN_OPERATOR", "OPERATOR_TOKEN")) == "old"
    monkeypatch.setenv("GRAPHUSERTOKEN_OPERATOR", "new")
    assert env_token(("GRAPHUSERTOKEN_OPERATOR", "OPERATOR_TOKEN")) == "new"
    monkeypatch.setenv("GRAPHUSERTOKEN_OPERATOR", "  ")
    assert env_token(("GRAPHUSERTOKEN_OPERATOR", "OPERATOR_TOKEN")) == "old"  # blank = unset


def test_the_app_takes_its_tokens_from_the_new_names(cat, monkeypatch):
    monkeypatch.setenv("GRAPHUSERTOKEN_OPERATOR", OP)
    monkeypatch.setenv("GRAPHUSERTOKEN_AGENT_SHARED", AG)
    monkeypatch.setenv("GRAPHUSERTOKEN_CLAUDE_SYSBUILDER", SB)
    monkeypatch.delenv("OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_SHARED_TOKEN", raising=False)
    app = create_app(None, runtime=_runtime(cat))
    with TestClient(app) as client:
        checks = client.get("/ready").json()["checks"]
        assert (checks["operator_token"], checks["agent_token"]) == ("ok", "ok")
        assert checks["sysbuilder_token"] == "ok"
        assert client.get("/model-roles", headers={"Authorization": f"Bearer {OP}"}).is_success
        assert client.get("/model-roles", headers={"Authorization": f"Bearer {SB}"}).is_success
        assert (
            client.get("/agent/pull", headers={"Authorization": f"Bearer {SB}"}).status_code == 401
        )


def test_the_build_agent_runs_the_whole_smoke_on_its_synthetic_firm(cat):
    two = Two(cat)
    report = run(two.builder)
    assert report.ok, [s for s in report.steps if not s.ok]
    answers = two.owner.get("/answers", params={"cui": CUI}).json()
    assert answers and {a["operator"] for a in answers} == {"claude-sysbuilder"}


def test_the_build_agent_never_touches_a_client_tenant(cat):
    two = Two(cat)
    b = two.builder
    refused = [
        b.put(
            f"/tenants/{CLIENT}",
            json={"cui": CLIENT, "name": "X", "saga_firm_folder": "1", "data_class": "synthetic"},
        ),  # flip it: no
        b.post(
            f"/tenants/{CLIENT}/exports/rj",
            params={"filename": "rj.xls"},
            content=b"x",
            headers={"Content-Type": "application/octet-stream"},
        ),
        b.post(
            "/ingest",
            params={"cui": CLIENT, "filename": "spv.zip"},
            content=NEW_INVOICE,
            headers={"Content-Type": "application/octet-stream"},
        ),
        b.post(f"/recon/{CLIENT}/2026-09"),
        b.get(f"/close/{CLIENT}/2026-09"),
        b.get(f"/rules/{CLIENT}"),
        b.get("/answers", params={"cui": CLIENT}),
        b.post(
            "/rules",
            json={
                "cui": CLIENT,
                "rule_id": "r1",
                "description": "abc",
                "scope": "document",
                "document": {"partner_cui": CUI},
            },
        ),
    ]
    assert [r.status_code for r in refused] == [403] * len(refused)
    assert "synthetic tenants only" in refused[0].json()["detail"]


def test_a_new_tenant_by_the_build_agent_is_synthetic_or_nothing(cat):
    b = Two(cat).builder
    body = {"cui": CUI, "name": "F", "saga_firm_folder": "0001"}
    assert b.put(f"/tenants/{CUI}", json=body).status_code == 403  # default class: client
    assert b.put(f"/tenants/{CUI}", json={**body, "data_class": "synthetic"}).is_success


def test_a_client_tenants_job_is_out_of_reach(cat):
    two = Two(cat)
    two.owner.post(
        "/ingest",
        params={"cui": CLIENT, "filename": "spv.zip"},
        content=NEW_INVOICE,  # the client tenant is its supplier: an outbound invoice
        headers={"Content-Type": "application/octet-stream"},
    )
    job_ids = [job.job_id for job in two.rt.jobs.jobs.values()]
    assert job_ids
    for job_id in job_ids:
        assert two.builder.get(f"/jobs/{job_id}").status_code == 403
        resp = two.builder.post(f"/jobs/{job_id}/resume", json={"decision": "approve"})
        assert resp.status_code == 403
    assert two.builder.get("/jobs/nope").status_code == 404
    assert two.builder.get("/triage/nope").status_code == 404


def test_the_logs_show_the_build_agent_only_synthetic_rows(cat):
    two = Two(cat)
    run(two.builder)  # synthetic answers and model calls
    rows = two.owner.get("/answers").json()
    from poarta_contabila.answers import record

    two.rt.answers.add(
        record(
            graph_id="g",
            thread_id="job:x",
            tenant_cui=CLIENT,
            before={"kind": "v3_approve"},
            after=None,
            answer={"secret": "client"},
            operator="A. Popescu",
        )
    )
    mine = two.builder.get("/answers").json()
    assert len(two.owner.get("/answers").json()) == len(rows) + 1
    assert all(r["tenant_cui"] == CUI for r in mine) and "client" not in str(mine)
    calls = two.builder.get("/model-calls", params={"limit": 500}).json()
    assert calls and all(c["tenant_cui"] == CUI for c in calls)


def test_a_route_with_no_tenant_is_closed_to_the_build_agent(cat):
    """Default deny: a route that names no tenant and is not listed stays closed to it."""
    from fastapi import HTTPException
    from starlette.requests import Request

    from poarta_contabila.operator_api import _synthetic_only

    rt = Two(cat).rt
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/a-later-route",
        "query_string": b"",
        "headers": [],
        "path_params": {},
    }
    with pytest.raises(HTTPException) as exc:
        _synthetic_only(rt, Request(scope))
    assert exc.value.status_code == 403 and "does not open this route" in exc.value.detail


@pytest.mark.parametrize("same", [OP, AG])
def test_a_sysbuilder_token_equal_to_another_is_ignored(cat, same):
    two = Two(cat, sysbuilder=same)
    client = TestClient(two.owner.app, headers={"Authorization": f"Bearer {SB}"})
    assert client.get("/model-roles").status_code == 401
