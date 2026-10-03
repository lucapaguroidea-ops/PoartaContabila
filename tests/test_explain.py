"""WP-50: System Two explains a person's question through OpenRouter — never decides."""

from __future__ import annotations

import json

import httpx
import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.explain import CHAT_URL, ExplainError, check_explanation
from poarta_contabila.model_roles import InMemoryModelCallStore, ModelGateway
from tests.test_jev_live import JUDGE_OK
from tests.test_runtime import CUI, FOLDER, NEW_INVOICE, Ops, _runtime

KEY = "sk-or-test-never-shown"
QUESTION = {
    "document": {"number": "AB 0099", "totals": {"gross": "807.81"}},
    "articol_id": "ro_efactura_inbound",
}
GOOD = {
    "explanation": "Factura AB 0099 este pe articolul ro_efactura_inbound. Totalul este 807.81.",
    "facts_cited": [
        {"field": "document.number", "value": "AB 0099"},
        {"field": "document.totals.gross", "value": "807.81"},
    ],
    "missing": [],
}


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


class OpenRouter:
    """Decisions (Jev) and chat (System Two): records requests, answers what it is told."""

    def __init__(self, content=None, status=200):
        self.requests: list[httpx.Request] = []
        self.content = json.dumps(GOOD) if content is None else content
        self.status = status

    def chat(self) -> list[httpx.Request]:
        return [r for r in self.requests if str(r.url) == CHAT_URL]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/alpha/decisions":
            return httpx.Response(200, json={"model": "typesafe/jev-1.13", "answers": JUDGE_OK})
        if self.status != 200:
            return httpx.Response(
                self.status,
                json={"error": {"code": self.status, "message": "Insufficient credits"}},
            )
        content = self.content(request) if callable(self.content) else self.content
        return httpx.Response(
            200,
            json={
                "model": "deepseek/deepseek-v4.1-flash",
                "provider": "DeepSeek",
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 900, "completion_tokens": 120, "cost": 0.0001},
            },
        )


def _ops(cat, api, monkeypatch, *, key=True, data_class="synthetic"):
    if key:
        monkeypatch.setenv("OPENROUTER_SYS2_API_KEY", KEY)
    else:
        monkeypatch.delenv("OPENROUTER_SYS2_API_KEY", raising=False)
    rt = _runtime(cat, model_mode="live", jev_http=httpx.Client(transport=httpx.MockTransport(api)))
    o = Ops(rt)
    body = {"cui": CUI, "name": "F", "saga_firm_folder": FOLDER, "data_class": data_class}
    o.http.put(f"/tenants/{CUI}", json=body, headers=o.op)
    o.upload_rj()
    return o


def _calls(o, role):
    return o.http.get("/model-calls", params={"role": role}, headers=o.op).json()


# ----- the answer must be the card's output -----


def test_a_good_answer_is_kept_as_written():
    out = check_explanation(QUESTION, "```json\n" + json.dumps(GOOD) + "\n```")
    assert out == GOOD


@pytest.mark.parametrize(
    ("content", "match"),
    [
        ("Aprobați factura.", "not JSON"),
        (json.dumps({**GOOD, "decision": "approve"}), "exactly"),
        (json.dumps({**GOOD, "explanation": " "}), "empty"),
        (json.dumps({**GOOD, "explanation": "Unu. Doi. Trei. Patru. Cinci. Șase."}), "5 sentences"),
        (json.dumps({**GOOD, "missing": "nimic"}), "list of strings"),
        (
            json.dumps({**GOOD, "facts_cited": [{"field": "document.vat", "value": "1"}]}),
            "not in the question",
        ),
        # a figure the question does not hold is made up
        (
            json.dumps({**GOOD, "facts_cited": [{"field": "document.number", "value": "AB 0100"}]}),
            "is not in the question",
        ),
    ],
)
def test_an_answer_off_the_card_is_refused(content, match):
    with pytest.raises(ExplainError, match=match):
        check_explanation(QUESTION, content)


# ----- on the real flow -----


def test_the_approval_question_comes_with_its_explanation(cat, monkeypatch):
    api = OpenRouter()
    o = _ops(cat, api, monkeypatch)
    out = o.ingest(NEW_INVOICE).json()
    assert out["question"]["kind"] == "v3_approve"
    explanation = out["explanation"]
    assert explanation["role_id"] == "sys2_explain_approve"
    assert explanation["explanation"] == GOOD["explanation"]
    assert explanation["served_by"] == "deepseek/deepseek-v4.1-flash via DeepSeek"

    (req,) = api.chat()
    body = json.loads(req.content)
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    assert body["model"] == "deepseek/deepseek-v4.1-flash"
    assert body["provider"] == {
        "only": ["deepseek"],
        "allow_fallbacks": False,
        "data_collection": "deny",
    }
    assert body["messages"][0]["content"].startswith("Reader: An accountant")
    assert json.loads(body["messages"][1]["content"])["kind"] == "v3_approve"

    (call,) = _calls(o, "sys2_explain_approve")
    assert call["status"] == "sent" and call["output"]["usage"]["cost"] == 0.0001
    assert KEY not in json.dumps(call)

    # looking again neither sends nor changes the explanation
    job_id = out["job"]["job_id"]
    again = o.http.get(f"/jobs/{job_id}", headers=o.op).json()
    assert again["explanation"] == explanation and len(api.chat()) == 1


def test_a_bad_answer_is_failed_and_the_question_is_shown_without_one(cat, monkeypatch):
    api = OpenRouter(content="Aprobați factura, e în regulă.")
    o = _ops(cat, api, monkeypatch)
    out = o.ingest(NEW_INVOICE).json()
    assert out["question"]["kind"] == "v3_approve" and out["explanation"] is None
    (call,) = _calls(o, "sys2_explain_approve")
    assert call["status"] == "failed" and "not JSON" in call["reason"]


def test_openrouter_refusing_is_failed_and_nothing_waits(cat, monkeypatch):
    api = OpenRouter(status=402)
    o = _ops(cat, api, monkeypatch)
    out = o.ingest(NEW_INVOICE).json()
    assert out["question"]["kind"] == "v3_approve" and out["explanation"] is None
    (call,) = _calls(o, "sys2_explain_approve")
    assert call["status"] == "failed" and call["reason"].startswith("OpenRouter answered HTTP 402")


def test_without_the_key_it_records_and_sends_nothing(cat, monkeypatch):
    api = OpenRouter()
    o = _ops(cat, api, monkeypatch, key=False)
    out = o.ingest(NEW_INVOICE).json()
    assert out["explanation"] is None and api.chat() == []
    (call,) = _calls(o, "sys2_explain_approve")
    assert call["status"] == "recorded"
    assert call["reason"] == "OPENROUTER_SYS2_API_KEY is not set: recorded, not sent"


def test_a_client_tenant_is_never_sent(cat, monkeypatch):
    calls = InMemoryModelCallStore()
    api = OpenRouter()
    gw = ModelGateway(
        roles=cat.model_roles,
        calls=calls,
        mode="live",
        synthetic=lambda cui: False,
        http=httpx.Client(transport=httpx.MockTransport(api)),
        key=lambda name: KEY,
    )
    gw.observe_question("v3_approve", QUESTION, "1000009")
    assert api.requests == []
    assert [c.status for c in calls.rows] == ["refused"]
    assert gw.explanation({"kind": "v3_approve", **QUESTION}, "1000009") is None


def test_the_close_question_is_explained_and_still_asked(cat, monkeypatch):
    api = OpenRouter(
        content=json.dumps(
            {"explanation": "Luna are diferențe materiale.", "facts_cited": [], "missing": []}
        )
    )
    o = _ops(cat, api, monkeypatch)
    o.ingest(NEW_INVOICE)
    close = o.http.post(
        f"/close/{CUI}/2026-09", params={"tva": "tva_platitor"}, headers=o.op
    ).json()
    assert close["question"]["kind"] == "v2_close"
    assert close["explanation"]["role_id"] == "sys2_explain_close"
    assert close["explanation"]["explanation"] == "Luna are diferențe materiale."
    # the rule drafter stays shadow: recorded, never sent
    drafts = _calls(o, "sys2_draft_rule")
    assert all(c["status"] == "recorded" for c in drafts)
