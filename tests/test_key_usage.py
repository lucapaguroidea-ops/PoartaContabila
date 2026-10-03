"""WP-56: each OpenRouter key's spend, read from OpenRouter — never computed, never the key."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from poarta_contabila.app import create_app
from poarta_contabila.catalog import load_catalog
from poarta_contabila.key_usage import CREDITS_URL, KEY_URL, KEYS_URL, describe, key_usage
from tests.test_runtime import _runtime

SYS1, SYS2, MGMT = "sk-or-v1-sys1-never-shown", "sk-or-v1-sys2-never-shown", "sk-or-v1-mgmt"
OP, AG, SB = "o" * 40, "a" * 40, "s" * 40

KEY_SYS1 = {
    "label": "sk-or-v1-sys...own",  # OpenRouter's label can show part of the key: not passed on
    "usage": 0.0123,
    "usage_daily": 0.0021,
    "usage_weekly": 0.0123,
    "usage_monthly": 0.0123,
    "limit": 5.0,
    "limit_remaining": 4.9877,
    "limit_reset": "monthly",
    "is_free_tier": False,
}


class OpenRouter:
    """The key, credits and keys endpoints; answers by which key is asking."""

    def __init__(self, sys2_status=200):
        self.requests: list[httpx.Request] = []
        self.sys2_status = sys2_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        secret = request.headers["Authorization"].removeprefix("Bearer ")
        url = str(request.url)
        if url == KEY_URL and secret == SYS1:
            return httpx.Response(200, json={"data": KEY_SYS1})
        if url == KEY_URL and secret == SYS2:
            if self.sys2_status != 200:
                msg = {"error": {"code": self.sys2_status, "message": "User not found."}}
                return httpx.Response(self.sys2_status, json=msg)
            return httpx.Response(200, json={"data": {**KEY_SYS1, "limit": None}})
        if url == CREDITS_URL and secret == MGMT:
            return httpx.Response(200, json={"data": {"total_credits": 10.0, "total_usage": 2.5}})
        if url == KEYS_URL and secret == MGMT:
            rows = [{"name": "system-1", "hash": "abc", "label": "sk-or-v1-x...y", **KEY_SYS1}]
            return httpx.Response(200, json={"data": rows})
        return httpx.Response(401, json={"error": {"code": 401, "message": "No auth"}})


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _read(cat, api, env):
    return key_usage(
        cat.model_roles, http=httpx.Client(transport=httpx.MockTransport(api)), key=env.get
    )


def test_each_key_reports_openrouters_own_figures_and_never_the_key(cat):
    api = OpenRouter()
    view = _read(cat, api, {"OPENROUTER_SYS1_API_KEY": SYS1, "OPENROUTER_SYS2_API_KEY": SYS2})
    keys = {k["key_env"]: k for k in view["keys"]}
    assert set(keys) == {"OPENROUTER_SYS1_API_KEY", "OPENROUTER_SYS2_API_KEY"}
    sys1 = keys["OPENROUTER_SYS1_API_KEY"]
    assert sys1["usage_daily"] == 0.0021 and sys1["limit_remaining"] == 4.9877
    assert "jev_v3_judge" in sys1["roles"] and "label" not in sys1
    assert "sys2_explain_close" in keys["OPENROUTER_SYS2_API_KEY"]["roles"]
    assert view["account"] is None  # no management key: the account is not read
    text = json.dumps(view)
    assert SYS1 not in text and SYS2 not in text and "sk-or-v1-sys...own" not in text
    assert [str(r.url) for r in api.requests] == [KEY_URL, KEY_URL]


def test_an_unset_key_is_not_asked_and_an_error_is_reported(cat):
    api = OpenRouter(sys2_status=401)
    view = _read(cat, api, {"OPENROUTER_SYS2_API_KEY": SYS2})
    keys = {k["key_env"]: k for k in view["keys"]}
    assert keys["OPENROUTER_SYS1_API_KEY"] == {
        "key_env": "OPENROUTER_SYS1_API_KEY",
        "roles": keys["OPENROUTER_SYS1_API_KEY"]["roles"],
        "set": False,
    }
    assert (
        keys["OPENROUTER_SYS2_API_KEY"]["error"] == "OpenRouter answered HTTP 401: User not found."
    )
    assert len(api.requests) == 1


def test_a_management_key_adds_the_account(cat):
    api = OpenRouter()
    view = _read(cat, api, {"OPENROUTER_SYS1_API_KEY": SYS1, "OPENROUTER_MANAGEMENT_KEY": MGMT})
    account = view["account"]
    assert account["total_credits"] == 10.0 and account["total_usage"] == 2.5
    (row,) = account["keys"]
    assert row["name"] == "system-1" and row["limit_remaining"] == 4.9877
    assert "label" not in row and "hash" not in row
    assert all(r.method == "GET" for r in api.requests)  # read only
    assert MGMT not in json.dumps(view)


def test_the_smoke_lines_read_as_openrouter_gave_them(cat):
    view = _read(
        cat,
        OpenRouter(),
        {
            "OPENROUTER_SYS1_API_KEY": SYS1,
            "OPENROUTER_SYS2_API_KEY": SYS2,
            "OPENROUTER_MANAGEMENT_KEY": MGMT,
        },
    )
    assert describe(view) == [
        "OPENROUTER_SYS1_API_KEY: spent $0.0021 today, $0.0123 in all;"
        " $4.9877 left of $5.0000 (monthly)",
        "OPENROUTER_SYS2_API_KEY: spent $0.0021 today, $0.0123 in all; no limit",
        "account: $2.5000 used of $10.0000 bought",
    ]


def test_the_route_answers_the_owner_and_the_build_agent(cat, monkeypatch):
    monkeypatch.setenv("OPENROUTER_SYS1_API_KEY", SYS1)
    monkeypatch.setenv("OPENROUTER_SYS2_API_KEY", SYS2)
    monkeypatch.delenv("OPENROUTER_MANAGEMENT_KEY", raising=False)
    api = OpenRouter()
    rt = _runtime(cat, jev_http=httpx.Client(transport=httpx.MockTransport(api)))
    app = create_app(None, runtime=rt, operator_token=OP, agent_token=AG, sysbuilder_token=SB)
    for token in (OP, SB):
        resp = TestClient(app, headers={"Authorization": f"Bearer {token}"}).get("/model-keys")
        assert resp.status_code == 200
        assert SYS1 not in resp.text and SYS2 not in resp.text
        assert {k["key_env"] for k in resp.json()["keys"] if k["set"]} == {
            "OPENROUTER_SYS1_API_KEY",
            "OPENROUTER_SYS2_API_KEY",
        }
    agent = TestClient(app, headers={"Authorization": f"Bearer {AG}"}).get("/model-keys")
    assert agent.status_code in (401, 403)
