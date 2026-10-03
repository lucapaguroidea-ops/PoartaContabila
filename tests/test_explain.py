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
                "model": "z-ai/glm-5.3",
                "provider": "Z.AI",
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


def test_json_inside_prose_is_read_and_reasoning_is_off(cat):
    from poarta_contabila.explain import request_body

    out = check_explanation(QUESTION, "Iată răspunsul:\n" + json.dumps(GOOD) + "\nGata.")
    assert out == GOOD
    body = request_body(cat.model_roles["sys2_explain_close"], {"kind": "v2_close"})
    assert body["reasoning"] == {"effort": "low", "exclude": True} and body["max_tokens"] == 6000


def test_an_empty_answer_is_refused_and_a_bad_one_is_quoted():
    with pytest.raises(ExplainError, match="empty"):
        check_explanation(QUESTION, "")
    with pytest.raises(ExplainError, match="not JSON: 'Aprobați"):
        check_explanation(QUESTION, "Aprobați factura.")


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
    assert explanation["served_by"] == "z-ai/glm-5.3 via Z.AI"

    (req,) = api.chat()
    body = json.loads(req.content)
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    assert body["model"] == "z-ai/glm-5.3"
    assert body["provider"] == {
        "only": ["z-ai"],
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


def test_an_answer_off_the_card_is_asked_once_more_with_the_reason(cat, monkeypatch):
    answers = [json.dumps({**GOOD, "explanation": ""}), json.dumps(GOOD)]
    api = OpenRouter(content=lambda request: answers.pop(0))
    o = _ops(cat, api, monkeypatch)
    out = o.ingest(NEW_INVOICE).json()
    assert out["explanation"]["explanation"] == GOOD["explanation"]
    first, second = api.chat()
    retry = json.loads(second.content)["messages"]
    assert len(retry) == len(json.loads(first.content)["messages"]) + 2
    assert retry[-1]["role"] == "user" and "explanation is empty" in retry[-1]["content"]
    (call,) = _calls(o, "sys2_explain_approve")
    assert call["status"] == "sent" and call["output"]["answers"] == 2
    assert call["output"]["usage"]["cost"] == 0.0002  # both answers are paid for


def test_a_second_bad_answer_is_failed(cat, monkeypatch):
    api = OpenRouter(content="Aprobați factura.")
    o = _ops(cat, api, monkeypatch)
    assert o.ingest(NEW_INVOICE).json()["explanation"] is None
    assert len(api.chat()) == 2
    (call,) = _calls(o, "sys2_explain_approve")
    assert call["status"] == "failed" and call["reason"].endswith("(after 2 answers)")


def test_the_brief_forbids_empty_facts_and_an_empty_explanation(cat):
    from poarta_contabila.model_roles import brief

    text = brief(cat.model_roles["sys2_explain_close"])
    assert "never empty" in text and "an empty field is not a fact" in text


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


def test_the_alternates_are_compared_first_answer_only_and_nothing_is_recorded(cat, monkeypatch):
    def by_model(request):
        model = json.loads(request.content)["model"]
        return json.dumps(GOOD) if model.startswith("moonshotai/") else "Aprobați."

    api = OpenRouter(content=by_model)
    o = _ops(cat, api, monkeypatch)
    o.ingest(NEW_INVOICE)
    before = len(_calls(o, "sys2_explain_approve"))
    sent = len(api.chat())
    resp = o.http.post(
        "/model-roles/sys2_explain_approve/compare", params={"runs": 2}, headers=o.op
    )
    assert resp.status_code == 200
    rows = {r["on"]: r for r in resp.json()["candidates"]}
    assert set(rows) == {"main", "alternate 1", "alternate 2"}
    assert rows["main"]["first_try_ok"] == 0 and rows["main"]["tries"] == 2
    assert rows["alternate 2"]["model"] == "moonshotai/kimi-k2.6"
    assert rows["alternate 2"]["first_try_ok"] == 2
    assert len(api.chat()) - sent == 6  # 3 candidates x 1 question x 2 runs, no retries
    assert len(_calls(o, "sys2_explain_approve")) == before
    assert KEY not in resp.text
    # the build agent opens it too: only synthetic tenants' questions are compared
    from fastapi.testclient import TestClient

    from poarta_contabila.app import create_app

    sb = "s" * 40
    app = create_app(None, runtime=o.rt, operator_token="o" * 40, sysbuilder_token=sb)
    builder = TestClient(app, headers={"Authorization": f"Bearer {sb}"})
    assert builder.post("/model-roles/sys2_explain_approve/compare").status_code == 200


def test_compare_needs_a_system_two_role(cat, monkeypatch):
    o = _ops(cat, OpenRouter(), monkeypatch)
    resp = o.http.post("/model-roles/jev_v3_judge/compare", headers=o.op)
    assert resp.status_code == 422


@pytest.mark.parametrize("text", ["...", "N/A", "Vezi mai sus."])
def test_a_placeholder_explanation_is_refused(text):
    with pytest.raises(ExplainError, match="placeholder"):
        check_explanation(QUESTION, json.dumps({**GOOD, "explanation": text}))


def test_only_glm_is_sent_the_reasoning_settings(cat):
    from poarta_contabila.explain import request_body

    role = cat.model_roles["sys2_explain_close"]
    kimi = role.model_copy(update={"model": "moonshotai/kimi-k2.6"})
    assert "reasoning" in request_body(role, {"kind": "v2_close"})
    assert "reasoning" not in request_body(kimi, {"kind": "v2_close"})


def test_an_answer_written_only_as_reasoning_says_so(cat):
    from poarta_contabila.explain import send

    def api(request):
        message = {"role": "assistant", "content": "", "reasoning": "Luna are diferențe..."}
        return httpx.Response(200, json={"choices": [{"message": message}]})

    role = cat.model_roles["sys2_explain_close"]
    with pytest.raises(ExplainError, match="only reasoning"):
        send(role, {"kind": "v2_close"}, KEY, http=httpx.Client(transport=httpx.MockTransport(api)))
