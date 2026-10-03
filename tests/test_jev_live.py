"""WP-20: Jev through OpenRouter's Decisions endpoint — synthetic tenants only, fail closed."""

from __future__ import annotations

import json

import httpx
import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.jev import (
    DECISIONS_URL,
    JevError,
    decision_questions,
    map_answers,
    role_transport,
)
from poarta_contabila.model_roles import InMemoryModelCallStore
from tests.test_runtime import CUI, FOLDER, NEW_INVOICE, Ops, _runtime

KEY = "sk-or-test-never-shown"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _noul(p):
    return {"type": "noul", "noul": p}


def _choice(c, conf):
    return {"type": "choice", "choice": c, "confidence": conf, "probabilities": {c: conf}}


JUDGE_OK = {"accounts_ok": _noul(0.97), "risk": _choice("low", 0.93), "needs_human": _noul(0.02)}
GATE = {
    "books_support_declaration": _noul(0.40),
    "gap_materiality": _choice("material", 0.95),
    "action": _choice("hold", 0.91),
}


class OpenRouter:
    """A stand-in for the Decisions endpoint: records requests, answers what it is told."""

    def __init__(self, answers=None, status=200):
        self.requests: list[httpx.Request] = []
        self.answers, self.status = answers or {}, status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(
                self.status,
                json={"error": {"code": self.status, "message": "Insufficient credits"}},
            )
        body = json.loads(request.content)
        answers = self.answers.get(body["model"], self.answers.get("*"))
        if callable(answers):
            answers = answers(body)
        return httpx.Response(
            200,
            json={
                "id": "gen-dec-1",
                "model": "typesafe/jev-1.13-20260917",
                "provider": "TypeSafe",
                "answers": answers,
                "usage": {"input_tokens": 400, "output_tokens": 30, "cost": 0.00002},
            },
        )


# ----- the card as questions, the answers as fields -----


def test_the_card_questions_are_sent_as_written(cat):
    q = decision_questions(cat.model_roles["jev_v3_judge"])
    assert set(q) == {"accounts_ok", "risk", "needs_human"}
    assert q["risk"]["type"] == "choice" and set(q["risk"]["criteria"]) == {"low", "medium", "high"}
    assert q["accounts_ok"]["criteria"] == {
        "true": "Accounts, side and VAT treatment all fit the document.",
        "false": "An account, the side or the VAT treatment does not fit.",
    }
    with pytest.raises(JevError, match="criteria from"):
        decision_questions(cat.model_roles["jev_v3_classify"])  # criteria_from: not sendable


@pytest.mark.parametrize(
    ("answers", "fields"),
    [
        (JUDGE_OK, {"accounts_ok": True, "risk": "low", "needs_human": False}),
        # an unsure yes is a no; a small chance a person is needed asks one (thresholds 0.9 / 0.1)
        (
            {**JUDGE_OK, "accounts_ok": _noul(0.85), "needs_human": _noul(0.12)},
            {"accounts_ok": False, "risk": "low", "needs_human": True},
        ),
        # an unsure risk is high, and a person judges it
        (
            {**JUDGE_OK, "risk": _choice("low", 0.79)},
            {"accounts_ok": True, "risk": "high", "needs_human": True},
        ),
    ],
)
def test_judge_answers_map_by_the_card_thresholds(cat, answers, fields):
    assert map_answers(cat.model_roles["jev_v3_judge"], "v3_judge", answers) == fields


def test_gate_and_review_take_their_cautious_values(cat):
    gate = cat.model_roles["jev_v2_gate"]
    unsure = {**GATE, "gap_materiality": _choice("none", 0.5), "action": _choice("file", 0.6)}
    assert map_answers(gate, "v2_declaration_gate", unsure) == {
        "books_support_declaration": False,
        "gap_materiality": "material",
        "action": "hold",
    }
    review = cat.model_roles["jev_recon_review"]
    assert map_answers(review, "recon_review", {"verdict": _choice("confirm", 0.4)}) == {
        "verdict": "abstain"
    }


@pytest.mark.parametrize(
    "answers",
    [
        None,
        {},
        {**JUDGE_OK, "risk": _choice("trivial", 0.99)},  # off the card
        {**JUDGE_OK, "accounts_ok": _noul(1.7)},  # not a probability
        {**JUDGE_OK, "accounts_ok": _choice("low", 0.9)},  # the wrong type
        {**JUDGE_OK, "needs_human": {"type": "noul"}},  # no value
    ],
)
def test_an_answer_off_the_card_is_no_answer(cat, answers):
    with pytest.raises(JevError):
        map_answers(cat.model_roles["jev_v3_judge"], "v3_judge", answers)


# ----- the transport -----


def _transport(cat, api, *, synthetic=True, key=KEY, mode="live"):
    calls = InMemoryModelCallStore()
    send = role_transport(
        cat.model_roles,
        mode=mode,
        calls=calls,
        synthetic=lambda cui: synthetic,
        http=httpx.Client(transport=httpx.MockTransport(api)),
        key=lambda name: key if name == "OPENROUTER_SYS1_API_KEY" else None,
    )
    return send, calls


PAYLOAD = {"tenant_cui": CUI, "articol": {"articol_id": "x"}, "document": {"number": "AB 1"}}


def test_a_synthetic_tenant_is_decided_through_openrouter(cat):
    api = OpenRouter({"*": JUDGE_OK})
    send, calls = _transport(cat, api)
    assert send("v3_judge", PAYLOAD, 20.0) == {
        "accounts_ok": True,
        "risk": "low",
        "needs_human": False,
    }
    (req,) = api.requests
    assert str(req.url) == DECISIONS_URL and req.headers["Authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["model"] == "typesafe/jev-1.13" and body["state"] == PAYLOAD
    assert body["provider"] == {
        "only": ["typesafe"],
        "allow_fallbacks": False,
        "data_collection": "deny",
    }
    assert set(body["questions"]) == {"accounts_ok", "risk", "needs_human"}
    (row,) = calls.rows
    assert row.status == "sent" and row.role_id == "jev_v3_judge"
    assert row.output["fields"]["risk"] == "low" and row.output["usage"]["input_tokens"] == 400
    assert "jev-1.13-20260917" in row.reason and KEY not in row.model_dump_json()


def test_without_the_key_it_records_and_sends_nothing(cat):
    api = OpenRouter({"*": JUDGE_OK})
    send, calls = _transport(cat, api, key=None)
    with pytest.raises(JevError, match="OPENROUTER_SYS1_API_KEY is not set"):
        send("v3_judge", PAYLOAD, 20.0)
    assert api.requests == [] and [r.status for r in calls.rows] == ["recorded"]


def test_a_client_tenant_is_never_sent(cat):
    api = OpenRouter({"*": JUDGE_OK})
    send, calls = _transport(cat, api, synthetic=False)
    with pytest.raises(JevError, match="EU route"):
        send("v3_judge", PAYLOAD, 20.0)
    assert api.requests == [] and [r.status for r in calls.rows] == ["refused"]


def test_dry_mode_never_sends(cat):
    api = OpenRouter({"*": JUDGE_OK})
    send, calls = _transport(cat, api, mode="dry")
    with pytest.raises(JevError, match="dry run"):
        send("v3_judge", PAYLOAD, 20.0)
    assert api.requests == [] and [r.status for r in calls.rows] == ["recorded"]


@pytest.mark.parametrize(
    ("api", "match"),
    [
        (OpenRouter(status=402), "HTTP 402"),
        (OpenRouter({"*": {"risk": _choice("low", 0.99)}}), "no noul answer"),
    ],
)
def test_a_failed_call_is_recorded_and_fails_closed(cat, api, match):
    send, calls = _transport(cat, api)
    with pytest.raises(JevError, match=match) as exc:
        send("v3_judge", PAYLOAD, 20.0)
    assert KEY not in str(exc.value)
    (row,) = calls.rows
    assert row.status == "failed" and KEY not in row.reason


def test_an_unreachable_openrouter_fails_closed(cat):
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    send, calls = _transport(cat, down)
    with pytest.raises(JevError, match="unreachable"):
        send("v3_judge", PAYLOAD, 20.0)
    assert [r.status for r in calls.rows] == ["failed"]


# ----- on the real flow -----


def _ops(cat, api, monkeypatch):
    monkeypatch.setenv("OPENROUTER_SYS1_API_KEY", KEY)
    rt = _runtime(cat, model_mode="live", jev_http=httpx.Client(transport=httpx.MockTransport(api)))
    o = Ops(rt)
    body = {"cui": CUI, "name": "F", "saga_firm_folder": FOLDER, "data_class": "synthetic"}
    o.http.put(f"/tenants/{CUI}", json=body, headers=o.op)
    o.upload_rj()
    return o


def test_the_judge_answers_live_on_the_real_flow(cat, monkeypatch):
    api = OpenRouter({"*": JUDGE_OK})
    o = _ops(cat, api, monkeypatch)
    out = o.ingest(NEW_INVOICE).json()
    judge = out["question"]["judge"]
    assert judge["judge"] == "jev" and judge["risk"] == "low" and judge["accounts_ok"] is True
    assert out["question"]["kind"] == "v3_approve"  # first_n: a person still approves
    assert [r.url.path for r in api.requests].count("/api/alpha/decisions") == 1
    calls = o.http.get("/model-calls", params={"role": "jev_v3_judge"}, headers=o.op).json()
    assert [c["status"] for c in calls] == ["sent"]


def test_layer2_suggests_live_and_never_clears_material(cat, monkeypatch):
    api = OpenRouter({"*": {**GATE, "action": _choice("file", 0.99)}})
    o = _ops(cat, api, monkeypatch)
    o.ingest(NEW_INVOICE)
    close = o.http.post(
        f"/close/{CUI}/2026-09", params={"tva": "tva_platitor"}, headers=o.op
    ).json()
    jev = close["question"]["jev"]
    assert close["question"]["material"] is True
    assert jev["action"] is None and "may not clear material" in jev["ignored"]
    calls = o.http.get("/model-calls", params={"role": "jev_v2_gate"}, headers=o.op).json()
    assert [c["status"] for c in calls] == ["sent"]
