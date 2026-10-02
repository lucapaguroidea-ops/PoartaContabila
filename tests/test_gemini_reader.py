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
    RateLimiter,
    gemini_reader_from_env,
    parse_answer,
)
from poarta_contabila.model_roles import InMemoryModelCallStore, RateLimit, load_roles
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


class Clock:
    """A fake monotonic clock that the reader's sleep moves forward."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _reader(
    cat, google, *, synthetic=True, model=MODEL, mode="live", key=KEY, sleeps=None, backup=None
):
    limit = RateLimit(rpm=5, tpm=250_000)
    role = cat.model_roles["ocr_extract"].model_copy(
        update={
            "model": model,
            "backup_model": backup,
            "rate_limits": {m: limit for m in (model, backup) if m},
        }
    )
    clock, log = Clock(), sleeps if sleeps is not None else []

    def sleep(seconds):
        log.append(seconds)
        clock.now += seconds

    return GeminiStatementReader(
        role=role,
        key=key,
        calls=InMemoryModelCallStore(),
        synthetic=lambda cui: synthetic,
        mode=mode,
        http=httpx.Client(transport=httpx.MockTransport(google)),
        sleep=sleep,
        limiter=RateLimiter(clock=clock),
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
        "rate_limits": {"gemini-2.5-flash": {"rpm": 5, "tpm": 250000}},
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


class Busy(Google):
    """Google answering ``statuses`` in turn (a transport error for 0), then a good answer."""

    def __init__(self, *statuses):
        super().__init__()
        self.queue = list(statuses)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if not self.queue:
            return super().__call__(request)
        self.requests.append(request)
        code = self.queue.pop(0)
        if code == 0:
            raise httpx.ConnectError("reset", request=request)
        return httpx.Response(code, json={"error": {"status": "UNAVAILABLE"}})


@pytest.mark.parametrize("statuses", [(503,), (503, 503), (0,), (500, 504)])
def test_a_busy_google_is_asked_again_and_the_statement_read(cat, statuses):
    google, sleeps = Busy(*statuses), []
    reader = _reader(cat, google, sleeps=sleeps)
    extraction = reader(PDF, tenant_cui=CUI)
    assert extraction.meta.backend == "gemini"
    assert len(google.requests) == len(statuses) + 1
    assert sleeps == [2.0, 6.0][: len(statuses)]
    assert [c.status for c in reader.calls.rows] == ["sent"]  # one call, however many tries


def test_a_google_busy_every_time_fails_after_three_tries(cat):
    google, sleeps = Busy(503, 503, 503, 503), []
    reader = _reader(cat, google, sleeps=sleeps)
    with pytest.raises(GeminiError, match=r"HTTP 503 UNAVAILABLE \(after 3 attempts\)") as exc:
        reader(PDF, tenant_cui=CUI)
    assert KEY not in str(exc.value)
    assert len(google.requests) == 3 and sleeps == [2.0, 6.0]
    assert [c.status for c in reader.calls.rows] == ["failed"]


def test_a_refusal_is_not_asked_again(cat):
    google, sleeps = Google(status=403), []
    with pytest.raises(GeminiError, match="HTTP 403"):
        _reader(cat, google, sleeps=sleeps)(PDF, tenant_cui=CUI)
    assert len(google.requests) == 1 and sleeps == []


BACKUP = "gemini-test-000"


def _model_of(request: httpx.Request) -> str:
    return request.url.path.rsplit("/", 1)[-1].split(":")[0]


def test_the_catalog_pins_one_backup_and_both_free_tier_limits(cat):
    role = cat.model_roles["ocr_extract"]
    assert (role.model, role.backup_model) == ("gemini-3.8-flash", "gemini-3.7-flash")
    assert role.rate_limits["gemini-3.8-flash"] == RateLimit(rpm=5, tpm=250_000)
    assert role.rate_limits["gemini-3.7-flash"] == RateLimit(rpm=5, tpm=250_000)


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"backup_model": "gemini-2.5-flash"}, "backup differs"),
        ({"backup_model": "gemini-flash-latest"}, "exact model id"),
        ({"backup_model": "google/gemini-2.0-flash"}, "not a Google AI Studio model id"),
        ({"backup_model": "gemini-2.0-flash"}, "no rate limit for"),
        ({"rate_limits": {}}, "no rate limit for"),
        ({"fallback_models": ["gemini-2.0-flash"]}, "fallback model lists are forbidden"),
        (
            {"route": "openrouter", "model": "google/gemini-2.5-flash", "rate_limits": {}},
            None,
        ),
    ],
)
def test_one_backup_only_on_the_direct_route_and_every_model_limited(change, match):
    if match is None:  # the OpenRouter route takes no backup at all
        with pytest.raises(ValueError, match="only for Google AI Studio"):
            load_roles({"roles": [_row(**change, backup_model="gemini-2.0-flash")]})
        return
    with pytest.raises(ValueError, match=match):
        load_roles({"roles": [_row(**change)]})


def test_the_main_model_reads_while_under_its_limit(cat):
    google, sleeps = Google(), []
    reader = _reader(cat, google, backup=BACKUP, sleeps=sleeps)
    for _ in range(5):
        reader(PDF, tenant_cui=CUI)
    assert {_model_of(r) for r in google.requests} == {MODEL} and sleeps == []
    assert {c.model for c in reader.calls.rows} == {MODEL}


def test_the_backup_reads_once_the_main_model_is_at_its_rpm(cat):
    google, sleeps = Google(), []
    reader = _reader(cat, google, backup=BACKUP, sleeps=sleeps)
    for _ in range(7):
        reader(PDF, tenant_cui=CUI)
    assert [_model_of(r) for r in google.requests] == [MODEL] * 5 + [BACKUP] * 2
    assert sleeps == []
    last = reader.calls.rows[-1]
    assert last.status == "sent" and last.model == BACKUP and last.output["backup"] is True
    assert "backup" in last.reason


def test_both_full_waits_for_the_first_free_slot(cat):
    google, sleeps = Google(), []
    reader = _reader(cat, google, backup=BACKUP, sleeps=sleeps)
    for _ in range(11):
        reader(PDF, tenant_cui=CUI)
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 60
    assert _model_of(google.requests[-1]) == MODEL  # the main model's minute ended first


def test_without_a_backup_the_main_model_waits(cat):
    google, sleeps = Google(), []
    reader = _reader(cat, google, sleeps=sleeps)
    for _ in range(6):
        reader(PDF, tenant_cui=CUI)
    assert len(sleeps) == 1 and {_model_of(r) for r in google.requests} == {MODEL}


class Quota(Google):
    """Google answering 429 for the models in *spent*."""

    def __init__(self, *spent):
        super().__init__()
        self.spent = set(spent)

    def __call__(self, request):
        if _model_of(request) in self.spent:
            self.requests.append(request)
            return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})
        return super().__call__(request)


def test_a_429_moves_to_the_backup_at_once(cat):
    google, sleeps = Quota(MODEL), []
    reader = _reader(cat, google, backup=BACKUP, sleeps=sleeps)
    reader(PDF, tenant_cui=CUI)
    assert [_model_of(r) for r in google.requests] == [MODEL, BACKUP] and sleeps == []
    reader(PDF, tenant_cui=CUI)  # the main model stays blocked for its minute
    assert _model_of(google.requests[-1]) == BACKUP
    assert [c.status for c in reader.calls.rows] == ["sent", "sent"]


def test_a_429_on_both_fails_after_waiting_out_the_minute(cat):
    google, sleeps = Quota(MODEL, BACKUP), []
    reader = _reader(cat, google, backup=BACKUP, sleeps=sleeps)
    with pytest.raises(GeminiError, match="429 RESOURCE_EXHAUSTED") as exc:
        reader(PDF, tenant_cui=CUI)
    assert KEY not in str(exc.value)
    assert [c.status for c in reader.calls.rows] == ["failed"]
    assert sum(sleeps) <= 90


def test_a_blocked_model_with_no_backup_waits_out_its_minute(cat):
    google, sleeps = Google(), []
    reader = _reader(cat, google, sleeps=sleeps)
    reader.limiter.exhaust(MODEL)  # blocked a full minute: within MAX_WAIT, so it waits
    reader(PDF, tenant_cui=CUI)
    assert sleeps == [60.0]


def test_the_token_limit_counts_what_google_counted():
    clock = Clock()
    limiter, limit = RateLimiter(clock=clock), RateLimit(rpm=100, tpm=10_000)
    assert limiter.take("m", limit, 4_000) == 0
    limiter.settle("m", 4_000, 9_000)
    assert limiter.take("m", limit, 4_000) == 60.0  # 9 000 + 4 000 > 10 000
    clock.now += 60
    assert limiter.take("m", limit, 4_000) == 0
    assert limiter.take("m", limit, 50_000) > 0  # over the limit only once others are in
    clock.now += 60
    assert limiter.take("m", limit, 50_000) == 0  # alone: Google judges it


def test_a_wait_past_the_bound_refuses_rather_than_hangs(cat):
    google, sleeps = Google(), []
    reader = _reader(cat, google, sleeps=sleeps)
    reader.limiter._blocked[MODEL] = reader.limiter.clock() + 600
    with pytest.raises(GeminiError, match="rate limit: .* full for another 600 s"):
        reader(PDF, tenant_cui=CUI)
    assert google.requests == [] and sleeps == []
    assert [c.status for c in reader.calls.rows] == ["failed"]
