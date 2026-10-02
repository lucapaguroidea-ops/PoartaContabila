"""WP-36: Gemini reads synthetic statements directly through Google AI Studio — never a client's."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.extract.gemini import (
    GeminiError,
    GeminiStatementReader,
    gemini_reader_from_env,
    parse_answer,
)
from poarta_contabila.model_roles import InMemoryModelCallStore, load_roles
from tests.test_extras import IBAN, META, PDF, TABLES
from tests.test_runtime import CUI, Ops, _runtime

KEY = "test-ai-studio-key-never-shown"
MODEL = "gemini-test-001"  # placeholder id for tests; the owner sends the real one
ANSWER = {"header": {**META, "opening": "5.000,00", "closing": "4.290,00"}, "tables": TABLES}


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


class Google:
    """A stand-in for Google AI Studio: records each request, answers what it is told."""

    def __init__(self, status=200, answer=ANSWER, extra=None):
        self.requests: list[httpx.Request] = []
        self.status, self.answer, self.extra = status, answer, extra or {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"status": "PERMISSION_DENIED"}})
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        body = {
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
            "modelVersion": "gemini-test-001-0915",
            **self.extra,
        }
        return httpx.Response(200, json=body)


def _reader(cat, google, *, synthetic=True, model=MODEL, mode="live", key=KEY):
    role = cat.model_roles["ocr_extract"].model_copy(update={"model": model})
    return GeminiStatementReader(
        role=role,
        key=key,
        calls=InMemoryModelCallStore(),
        synthetic=lambda cui: synthetic,
        mode=mode,
        http=httpx.Client(transport=httpx.MockTransport(google)),
    )


def test_a_synthetic_statement_is_read_and_the_call_recorded(cat):
    google = Google()
    reader = _reader(cat, google)
    extraction = reader(PDF, tenant_cui=CUI)
    (req,) = google.requests
    assert str(req.url).endswith(f"/v1beta/models/{MODEL}:generateContent")
    assert req.headers["x-goog-api-key"] == KEY
    body = json.loads(req.content)
    (pdf_part, _) = body["contents"][0]["parts"]
    assert pdf_part["inlineData"]["mimeType"] == "application/pdf"
    assert base64.b64decode(pdf_part["inlineData"]["data"]) == PDF
    assert "bank statement" in body["systemInstruction"]["parts"][0]["text"]
    config = body["generationConfig"]
    assert config["temperature"] == 0 and config["responseMimeType"] == "application/json"
    schema = config["responseSchema"]
    assert schema["required"] == ["header", "tables"]
    assert set(schema["properties"]["header"]["properties"]) == {
        "iban",
        "holder_cui",
        "currency",
        "opening",
        "closing",
        "statement_date",
    }
    rows = schema["properties"]["tables"]["items"]["properties"]["rows"]
    assert rows == {"type": "ARRAY", "items": {"type": "ARRAY", "items": {"type": "STRING"}}}

    assert extraction.tables == TABLES and extraction.meta.backend == "gemini"
    assert extraction.meta.identity_ok and IBAN in extraction.markdown
    (call,) = reader.calls.rows
    assert call.status == "sent" and call.output["rows"] == 5
    assert call.input["file"]["bytes"] == len(PDF) and "data" not in json.dumps(call.input)
    assert KEY not in call.model_dump_json()


@pytest.mark.parametrize(
    ("over", "match"),
    [
        ({"synthetic": False}, "client data never goes to Google AI Studio"),
        ({"mode": "dry"}, "not live"),
        ({"model": None}, "no model chosen"),
        ({"key": ""}, "GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC is not set"),
    ],
)
def test_nothing_is_sent_unless_every_guard_passes(cat, over, match):
    google = Google()
    reader = _reader(cat, google, **over)
    with pytest.raises(GeminiError, match=match):
        reader(PDF, tenant_cui=CUI)
    assert google.requests == []  # refused before any request
    assert [c.status for c in reader.calls.rows] == ["refused"]


@pytest.mark.parametrize(
    ("google", "match"),
    [
        (Google(status=403), "HTTP 403 PERMISSION_DENIED"),
        (Google(answer="not json"), "not JSON"),
        (Google(answer={"header": {}, "tables": [], "total": "1"}), "not {header, tables}"),
        (Google(answer={"header": {}, "tables": [{"headers": ["a"], "rows": [[1]]}]}), "row 0"),
        (Google(extra={"promptFeedback": {"blockReason": "SAFETY"}}), "blocked"),
    ],
)
def test_a_bad_answer_refuses_the_statement_and_never_shows_the_key(cat, google, match):
    reader = _reader(cat, google)
    with pytest.raises(GeminiError, match=match) as exc:
        reader(PDF, tenant_cui=CUI)
    assert KEY not in str(exc.value)
    assert [c.status for c in reader.calls.rows] == ["failed"]


def test_only_the_card_shape_is_taken():
    header, tables = parse_answer(json.dumps({"header": {"iban": "X", "other": "y"}}))
    assert header == {"iban": "X"} and tables == []  # unknown header fields are dropped


# ----- through the runtime -----


def _ops(cat, google, data_class="synthetic"):
    rt = _runtime(cat)
    o = Ops(rt)
    body = {
        "cui": CUI,
        "name": "FIRMA TEST SRL",
        "saga_firm_folder": "0001",
        "data_class": data_class,
        "bank_accounts": {IBAN: "5121.01"},
    }
    o.http.put(f"/tenants/{CUI}", json=body, headers=o.op)
    o.upload_rj()
    rt.gemini_reader = _reader(cat, google)
    rt.gemini_reader.synthetic = rt._synthetic  # the registry decides, as in production
    rt.gemini_reader.calls = rt.model_calls
    return o


def _upload(o):
    return o.http.post(
        f"/extras/{CUI}",
        headers=o.op,
        json={"meta": META, "pdf_b64": base64.b64encode(PDF).decode()},  # no tables: read it
    )


def test_a_synthetic_tenants_statement_pdf_is_read_once_and_minted(cat):
    google = Google()
    o = _ops(cat, google)
    out = _upload(o).json()
    assert out["lines"] == 2 and len(google.requests) == 1
    again = _upload(o).json()  # the same PDF: the stored extract, no second call
    assert [j["created"] for j in again["jobs"]] == [False, False]
    assert len(google.requests) == 1
    calls = o.http.get("/model-calls", params={"role": "ocr_extract"}, headers=o.op).json()
    assert [c["status"] for c in calls] == ["sent"]


def test_a_client_tenants_statement_is_never_sent(cat):
    google = Google()
    o = _ops(cat, google, data_class="client")
    resp = _upload(o)
    assert resp.status_code == 422 and "no statement reader" in resp.json()["detail"]
    assert google.requests == []


def test_a_statement_of_another_holder_is_refused(cat):
    other = {**ANSWER, "header": {**ANSWER["header"], "holder_cui": "RO20000005"}}
    o = _ops(cat, Google(answer=other))
    resp = _upload(o)
    assert resp.status_code == 422 and "stmt_no_identity" in resp.json()["detail"]


# ----- the catalog and the switch -----


def _row(**change):
    return {
        "role_id": "r",
        "graph_id": "ingest_source_doc",
        "node": "extract",
        "system": "document_reading",
        "output": "x",
        "status": "wired",
        "route": "google_ai_studio",
        "model": "gemini-2.5-flash",
        "card": {"instructions": ["copy"], "output": {"header": "{}"}},
        **change,
    }


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"model": "google/gemini-2.5-flash"}, "not a Google AI Studio model id"),
        ({"model": "gemini-flash-latest"}, "exact model id"),
        (
            {"system": "system_two", "family": "glm", "card": {}},
            "only document reading goes direct",
        ),
        ({"provider": {"only": ["google-ai-studio"]}}, "provider pins are OpenRouter's"),
    ],
)
def test_the_direct_route_is_only_for_document_reading_with_a_bare_gemini_id(change, match):
    with pytest.raises(ValueError, match=match):
        load_roles({"roles": [_row(**change)]})
    assert load_roles({"roles": [_row()]})["r"].route == "google_ai_studio"


def test_the_reader_exists_only_live_with_the_key(cat, monkeypatch):
    calls = InMemoryModelCallStore()
    monkeypatch.delenv("GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC", raising=False)
    assert gemini_reader_from_env(cat.model_roles, calls, lambda c: True, "live") is None
    monkeypatch.setenv("GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC", KEY)
    assert gemini_reader_from_env(cat.model_roles, calls, lambda c: True, "dry") is None
    reader = gemini_reader_from_env(cat.model_roles, calls, lambda c: True, "live")
    assert reader is not None and reader.key == KEY and reader.mode == "live"


def test_the_model_roles_view_shows_the_direct_key_as_set_or_not(cat, monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC", KEY)
    o = Ops(_runtime(cat))
    resp = o.http.get("/model-roles", headers=o.op)
    role = {r["role_id"]: r for r in resp.json()}["ocr_extract"]
    assert role["key_env"] == "GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC" and role["key_set"] is True
    assert role["route"] == "google_ai_studio" and KEY not in resp.text
