"""WP-53 (00_LAW §8 A7): provider data policies, approved alternates, the operator's choice."""

from __future__ import annotations

import json
import os

import httpx
import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.jev import JevError, role_transport
from poarta_contabila.model_roles import InMemoryModelCallStore, ModelGateway, load_roles
from poarta_contabila.provider_policy import (
    POLICY_URL,
    InMemoryPolicyStore,
    InMemoryRoleChoiceStore,
    RoleChoice,
    Router,
    parse,
    pick,
)
from tests.test_explain import GOOD, QUESTION
from tests.test_jev_live import JUDGE_OK, PAYLOAD

KEY = "sk-or-test-never-shown"
NOW = "2026-10-03T12:00:00Z"


def _providers(**flags):
    """OpenRouter's provider list; ``z_ai="train"`` marks z-ai as training on prompts."""
    rows = []
    for slug in ("z-ai", "together", "moonshotai", "typesafe", "deepseek"):
        bad = flags.get(slug.replace("-", "_"))
        rows.append(
            {
                "slug": slug,
                "dataPolicy": {"training": bad == "train", "retainsPrompts": bad == "keep"},
            }
        )
    return {"data": rows}


def _policies(**flags):
    store = InMemoryPolicyStore()
    store.put_all(parse(_providers(**flags), NOW))
    return store


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


@pytest.fixture
def explain(cat):
    return cat.model_roles["sys2_explain_close"]


# ----- the policy and the pick -----


def test_a_provider_passes_only_when_it_neither_trains_nor_keeps_prompts():
    rows = {p.slug: p for p in parse(_providers(z_ai="train", together="keep"), NOW)}
    assert rows["moonshotai"].passes and not rows["z-ai"].passes and not rows["together"].passes
    assert rows["z-ai"].why() == "z-ai trains on prompts"


def test_the_main_pin_holds_while_its_provider_passes(explain):
    p = pick(explain, _policies())
    assert (p.on, p.model, p.provider["only"], p.reason) == ("main", "z-ai/glm-5.3", ["z-ai"], "")


def test_a_provider_not_yet_read_passes(explain):
    assert pick(explain, InMemoryPolicyStore()).on == "main"


@pytest.mark.parametrize(
    ("flags", "on", "model", "provider"),
    [
        ({"z_ai": "train"}, "alternate 1", "z-ai/glm-5.3", ["together"]),
        (
            {"z_ai": "train", "together": "keep"},
            "alternate 2",
            "moonshotai/kimi-k2.6",
            ["moonshotai"],
        ),
    ],
)
def test_a_failing_pin_moves_to_the_first_approved_alternate_that_passes(
    explain, flags, on, model, provider
):
    p = pick(explain, _policies(**flags))
    assert (p.on, p.model, p.provider["only"]) == (on, model, provider)
    assert p.provider["data_collection"] == "deny" and p.provider["allow_fallbacks"] is False
    assert "z-ai trains on prompts" in p.reason


def test_no_passing_pin_and_the_operator_choices(explain):
    flags = {"z_ai": "train", "together": "train", "moonshotai": "keep"}
    none = pick(explain, _policies(**flags))
    assert none.model is None and "no passing model" in none.reason

    def choose(choice, until=None):
        return RoleChoice(role_id=explain.role_id, choice=choice, until=until, at=NOW)

    allow = pick(explain, _policies(**flags), choose("allow_synthetic", "2026-10-10"), "2026-10-03")
    assert allow.on == "operator choice" and allow.model == "z-ai/glm-5.3"
    assert allow.provider["data_collection"] == "allow" and allow.provider["only"] == ["z-ai"]
    expired = pick(
        explain, _policies(**flags), choose("allow_synthetic", "2026-10-02"), "2026-10-03"
    )
    assert expired.model is None
    # pause: recorded only, even while the main pin passes
    assert pick(explain, _policies(), choose("pause"), "2026-10-03").model is None
    assert pick(explain, _policies(**flags), choose("wait"), "2026-10-03").model is None


def test_jev_has_no_alternate(cat):
    p = pick(cat.model_roles["jev_v3_judge"], _policies(typesafe="train"))
    assert p.model is None and "typesafe trains on prompts" in p.reason


# ----- the catalog -----


def _doc(cat_path, **alt):
    import yaml

    doc = yaml.safe_load(cat_path.read_text(encoding="utf-8"))
    row = next(r for r in doc["roles"] if r["role_id"] == "sys2_explain_close")
    row["alternates"] = [alt]
    return doc


@pytest.mark.parametrize(
    ("alt", "match"),
    [
        ({"model": "openrouter/auto", "provider": {"only": ["x"]}}, "not an exact model id"),
        ({"model": "z-ai/glm-5.3", "provider": {"only": []}}, "names its provider"),
        ({"model": "z-ai/glm-5.3", "provider": {"only": ["z-ai"]}}, "listed twice"),
        ({"model": "typesafe/jev-1.13", "provider": {"only": ["typesafe"]}}, "not a system_two"),
        (
            {"model": "z-ai/glm-5.3", "provider": {"only": ["x"], "data_collection": "allow"}},
            "deny",
        ),
    ],
)
def test_an_alternate_that_breaks_the_rules_does_not_load(alt, match):
    from tests.test_model_roles import ROLES_YAML

    with pytest.raises(ValueError, match=match):
        load_roles(_doc(ROLES_YAML, **alt))


# ----- the senders -----


class OpenRouter:
    """Chat, Decisions and the provider list; ``refuse`` = provider slugs answered with 404."""

    def __init__(self, refuse=(), providers=None):
        self.requests: list[httpx.Request] = []
        self.refuse, self.providers = set(refuse), providers or _providers()

    def sent(self):
        return [json.loads(r.content) for r in self.requests if r.method == "POST"]

    def __call__(self, request):
        self.requests.append(request)
        if str(request.url) == POLICY_URL:
            return httpx.Response(200, json=self.providers)
        body = json.loads(request.content)
        if set(body["provider"]["only"]) & self.refuse:
            msg = "No endpoints found matching your data policy (Paid model training)."
            return httpx.Response(404, json={"error": {"code": 404, "message": msg}})
        if request.url.path == "/api/alpha/decisions":
            return httpx.Response(200, json={"model": body["model"], "answers": JUDGE_OK})
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "provider": body["provider"]["only"][0],
                "choices": [{"message": {"content": json.dumps(GOOD)}}],
            },
        )


def _gateway(cat, api, policies):
    http = httpx.Client(transport=httpx.MockTransport(api))
    calls = InMemoryModelCallStore()
    gw = ModelGateway(
        roles=cat.model_roles,
        calls=calls,
        mode="live",
        synthetic=lambda cui: True,
        http=http,
        key=lambda name: KEY,
        router=Router(policies=policies, choices=InMemoryRoleChoiceStore(), http=http),
    )
    return gw, calls


def test_an_explanation_goes_by_the_alternate_and_says_so(cat):
    api = OpenRouter()
    gw, calls = _gateway(cat, api, _policies(z_ai="train"))
    gw.observe_question("v2_close", QUESTION, "1000009")
    (body,) = api.sent()
    assert body["model"] == "z-ai/glm-5.3" and body["provider"]["only"] == ["together"]
    (call,) = calls.rows
    assert call.status == "sent" and "on alternate 1: z-ai trains on prompts" in call.reason


def test_a_data_policy_refusal_reads_the_policies_and_retries_on_the_new_pin(cat):
    api = OpenRouter(refuse={"z-ai"}, providers=_providers(z_ai="train"))
    gw, calls = _gateway(cat, api, InMemoryPolicyStore())  # not read yet: z-ai assumed fine
    gw.observe_question("v2_close", QUESTION, "1000009")
    assert [b["provider"]["only"] for b in api.sent()] == [["z-ai"], ["together"]]
    assert [c.status for c in calls.rows] == ["failed", "sent"]
    assert "data policy" in calls.rows[0].reason and "alternate 1" in calls.rows[1].reason
    assert any(str(r.url) == POLICY_URL for r in api.requests)


def test_with_no_passing_pin_nothing_is_sent(cat):
    api = OpenRouter()
    flags = {"z_ai": "train", "together": "train", "moonshotai": "train"}
    gw, calls = _gateway(cat, api, _policies(**flags))
    gw.observe_question("v2_close", QUESTION, "1000009")
    assert api.sent() == []
    (call,) = calls.rows
    assert call.status == "failed" and "no passing model" in call.reason


def test_jev_with_a_failing_provider_sends_nothing_and_fails_closed(cat):
    api = OpenRouter()
    calls = InMemoryModelCallStore()
    send = role_transport(
        cat.model_roles,
        mode="live",
        calls=calls,
        synthetic=lambda cui: True,
        http=httpx.Client(transport=httpx.MockTransport(api)),
        key=lambda name: KEY,
        router=Router(policies=_policies(typesafe="keep")),
    )
    with pytest.raises(JevError, match="no passing model"):
        send("v3_judge", PAYLOAD, 20.0)
    assert api.sent() == [] and [c.status for c in calls.rows] == ["failed"]


# ----- the operator's view and choice -----


def test_the_view_shows_the_pin_and_an_operator_chooses(cat, monkeypatch):
    from tests.test_runtime import Ops, _runtime

    monkeypatch.setenv("OPENROUTER_SYS2_API_KEY", KEY)
    rt = _runtime(cat, model_mode="live", provider_policies=_policies(z_ai="train"))
    o = Ops(rt)
    roles = {r["role_id"]: r for r in o.http.get("/model-roles", headers=o.op).json()}
    pin = roles["sys2_explain_close"]["pin"]
    assert pin["on"] == "alternate 1" and pin["provider"] == ["together"]
    assert roles["jev_v3_judge"]["pin"]["on"] == "main" and roles["ocr_extract"]["pin"] is None

    url = "/model-roles/sys2_explain_close/choice"
    bad = o.http.post(url, json={"choice": "allow_synthetic"}, headers=o.op)
    assert bad.status_code == 422
    ok = o.http.post(url, json={"choice": "pause"}, headers=o.op).json()
    assert ok["pin"]["on"] == "none" and ok["choice"]["choice"] == "pause"
    assert (
        o.http.post(
            "/model-roles/ocr_extract/choice", json={"choice": "wait"}, headers=o.op
        ).status_code
        == 422
    )


def test_the_postgres_stores_keep_the_latest():
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    import psycopg

    from poarta_contabila.db import schema_sql
    from poarta_contabila.provider_policy import PostgresPolicyStore, PostgresRoleChoiceStore

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(schema_sql())
        conn.execute("DELETE FROM domain.provider_policies")
        conn.execute("DELETE FROM domain.model_role_choices")
    pol = PostgresPolicyStore(dsn)
    pol.put_all(parse(_providers(), NOW))
    pol.put_all(parse(_providers(z_ai="train"), "2026-10-04T00:00:00Z"))
    assert not pol.get("z-ai").passes and pol.get("together").passes
    assert pol.checked_at() == "2026-10-04T00:00:00Z" and pol.get("nobody") is None
    ch = PostgresRoleChoiceStore(dsn)
    assert ch.latest("sys2_explain_close") is None
    ch.put(RoleChoice(role_id="sys2_explain_close", choice="pause", at=NOW))
    ch.put(RoleChoice(role_id="sys2_explain_close", choice="wait", at=NOW))
    assert ch.latest("sys2_explain_close").choice == "wait"
