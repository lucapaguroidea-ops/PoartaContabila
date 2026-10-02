"""WP-36: Gemini reads synthetic statements directly through Google AI Studio — never a client's."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta

import httpx
import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.extract.gemini import (
    PACIFIC,
    GeminiError,
    GeminiStatementReader,
    RateLimiter,
    gemini_reader_from_env,
    parse_answer,
)
from poarta_contabila.model_roles import InMemoryModelCallStore, RateLimit, Tiers, load_roles
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


class Wall:
    """A fake Pacific wall clock, moved with the monotonic one."""

    def __init__(self, clock):
        self.clock, self.start = clock, datetime(2026, 10, 2, 9, 0, tzinfo=PACIFIC)

    def __call__(self):
        return self.start + timedelta(seconds=self.clock.now - 1000.0)


LITE, LITE2, STRONG, STRONG2 = (
    "gemini-lite-a",
    "gemini-lite-b",
    "gemini-strong-a",
    "gemini-strong-b",
)
LIMITS = {
    LITE: RateLimit(rpm=15, tpm=250_000),
    LITE2: RateLimit(rpm=15, tpm=250_000),
    STRONG: RateLimit(rpm=5, tpm=250_000, rpd=20),
    STRONG2: RateLimit(rpm=5, tpm=250_000, rpd=20),
}


def _reader(
    cat, google, *, synthetic=True, model=MODEL, mode="live", key=KEY, sleeps=None, tiers=False
):
    """One model (*model*) by default; ``tiers=True``: the two-tier ladder above."""
    update = {"model": model, "tiers": None, "rate_limits": {model: RateLimit(rpm=5, tpm=250_000)}}
    if tiers:
        update = {
            "model": LITE,
            "tiers": Tiers(everyday=[LITE, LITE2], strong=[STRONG, STRONG2]),
            "rate_limits": LIMITS,
        }
    role = cat.model_roles["ocr_extract"].model_copy(update=update)
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
        limiter=RateLimiter(clock=clock, wall=Wall(clock)),
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


def _ops(cat, google, data_class="synthetic", tiers=False):
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
    rt.gemini_reader = _reader(cat, google, tiers=tiers)
    rt.gemini_reader.synthetic = rt._synthetic  # the registry decides, as in production
    rt.gemini_reader.calls = rt.model_calls
    return o


def _upload(o, pdf=PDF, **extra):
    return o.http.post(
        f"/extras/{CUI}",
        headers=o.op,
        json={"meta": META, "pdf_b64": base64.b64encode(pdf).decode(), **extra},  # no tables
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


def _model_of(request: httpx.Request) -> str:
    return request.url.path.rsplit("/", 1)[-1].split(":")[0]


@pytest.mark.parametrize("status", [503, 0, 500, 504])
def test_a_busy_google_is_asked_once_more_after_ten_seconds(cat, status):
    google, sleeps = Busy(status), []
    reader = _reader(cat, google, sleeps=sleeps)
    assert reader(PDF, tenant_cui=CUI).meta.backend == "gemini"
    assert len(google.requests) == 2 and sleeps == [10.0]
    assert [c.status for c in reader.calls.rows] == ["sent"]  # one call, however many tries


def test_a_google_busy_twice_fails_with_one_model(cat):
    google, sleeps = Busy(503, 503, 503), []
    reader = _reader(cat, google, sleeps=sleeps)
    with pytest.raises(GeminiError, match=r"HTTP 503 UNAVAILABLE \(after 2 attempts\)") as exc:
        reader(PDF, tenant_cui=CUI)
    assert KEY not in str(exc.value)
    assert len(google.requests) == 2 and sleeps == [10.0]
    assert [c.status for c in reader.calls.rows] == ["failed"]


def test_a_refusal_is_not_asked_again(cat):
    google, sleeps = Google(status=403), []
    with pytest.raises(GeminiError, match="HTTP 403"):
        _reader(cat, google, sleeps=sleeps)(PDF, tenant_cui=CUI)
    assert len(google.requests) == 1 and sleeps == []


# ----- tiers and limits (00_LAW §8 A4) -----


def test_the_catalog_reads_lite_first_and_flash_to_escalate(cat):
    for role_id in ("ocr_extract", "ocr_decont_split"):
        role = cat.model_roles[role_id]
        assert role.tiers.everyday == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
        assert role.tiers.strong == ["gemini-3.8-flash", "gemini-3.7-flash"]
        assert role.model == "gemini-3.5-flash-lite"
        assert role.rate_limits["gemini-3.8-flash"] == RateLimit(rpm=5, tpm=250_000, rpd=20)
        assert role.rate_limits["gemini-3.7-flash"] == RateLimit(rpm=5, tpm=250_000, rpd=20)
        assert role.rate_limits["gemini-3.5-flash-lite"].rpd is None  # [de confirmat]


def _tiered_row(**change):
    tiered = {
        "model": "gemini-a",
        "tiers": {"everyday": ["gemini-a"], "strong": ["gemini-b"]},
        "rate_limits": {m: {"rpm": 5, "tpm": 1000} for m in ("gemini-a", "gemini-b")},
    }
    return _row(**{**tiered, **change})


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ({"model": "gemini-b"}, "first everyday model"),
        ({"tiers": {"everyday": ["gemini-a"], "strong": ["gemini-a"]}}, "listed twice"),
        ({"tiers": {"everyday": ["gemini-a"], "strong": ["gemini-flash-latest"]}}, "exact"),
        ({"tiers": {"everyday": ["gemini-a"], "strong": ["google/gemini-b"]}}, "exact"),
        ({"tiers": {"everyday": ["gemini-a"], "strong": []}}, "at least 1"),
        ({"rate_limits": {"gemini-a": {"rpm": 5, "tpm": 1000}}}, "no rate limit for"),
        (
            {"rate_limits": {f"gemini-{m}": {"rpm": 5, "tpm": 1, "rpd": 0} for m in "ab"}},
            "greater than 0",
        ),
        ({"fallback_models": ["gemini-c"]}, "fallback model lists are forbidden"),
        ({"route": "openrouter", "rate_limits": {}}, "only for Google AI Studio"),
    ],
)
def test_tiers_only_on_the_direct_route_exact_and_every_model_limited(change, match):
    with pytest.raises(ValueError, match=match):
        load_roles({"roles": [_tiered_row(**change)]})
    assert load_roles({"roles": [_tiered_row()]})["r"].tiers.all == ["gemini-a", "gemini-b"]


def _pages(n: int) -> bytes:
    return b"%PDF-1.4 " + b" ".join(b"<< /Type /Page >>" for _ in range(n)) + b" /Type /Pages"


@pytest.mark.parametrize(
    ("pdf", "kw", "order"),
    [
        (_pages(1), {}, [LITE, LITE2, STRONG, STRONG2]),
        (_pages(2), {}, [STRONG, STRONG2, LITE, LITE2]),  # a hard statement
        (_pages(1), {"strong": True}, [STRONG, STRONG2, LITE, LITE2]),  # asked for
        (_pages(1), {"escalate": True}, [STRONG, STRONG2]),  # a second run
    ],
)
def test_the_order_of_models(cat, pdf, kw, order):
    assert _reader(cat, Google(), tiers=True).order(pdf, **kw) == order


def test_everyday_reads_until_its_minute_is_full_then_the_next_everyday(cat):
    google, sleeps = Google(), []
    reader = _reader(cat, google, tiers=True, sleeps=sleeps)
    for _ in range(17):
        reader(PDF, tenant_cui=CUI)
    assert [_model_of(r) for r in google.requests] == [LITE] * 15 + [LITE2] * 2
    assert sleeps == []
    last = reader.calls.rows[-1]
    assert last.model == LITE2 and last.output["tier"] == "everyday"
    assert last.output["first_choice"] is False


def test_the_strong_tier_stops_at_its_daily_limit(cat):
    google, sleeps = Google(), []
    reader = _reader(cat, google, tiers=True, sleeps=sleeps)
    for _ in range(41):  # one every 13 s: under 5 a minute, so only the day stops them
        reader(_pages(2), tenant_cui=CUI)
        reader.limiter.clock.now += 13
    models = [_model_of(r) for r in google.requests]
    assert models.count(STRONG) == 20 and models.count(STRONG2) == 20
    assert models[-1] == LITE  # both strong models spent for the Pacific day
    assert reader.limiter.used_today(STRONG) == 20


def test_a_daily_429_skips_the_model_for_the_day_and_names_the_quota(cat):
    daily = {
        "error": {
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                    ],
                }
            ],
        }
    }

    class Spent(Google):
        def __call__(self, request):
            if _model_of(request) == LITE:
                self.requests.append(request)
                return httpx.Response(429, json=daily)
            return super().__call__(request)

    google, sleeps = Spent(), []
    reader = _reader(cat, google, tiers=True, sleeps=sleeps)
    reader(PDF, tenant_cui=CUI)
    assert [_model_of(r) for r in google.requests] == [LITE, LITE2] and sleeps == []
    reader.limiter.clock.now += 120  # past the minute: still spent for the day
    reader(PDF, tenant_cui=CUI)
    assert _model_of(google.requests[-1]) == LITE2


def test_a_busy_model_hands_over_to_the_next_after_its_retry(cat):
    google, sleeps = Busy(503, 503), []
    reader = _reader(cat, google, tiers=True, sleeps=sleeps)
    reader(PDF, tenant_cui=CUI)
    assert [_model_of(r) for r in google.requests] == [LITE, LITE, LITE2]
    assert sleeps == [10.0]


def test_every_model_failing_names_each(cat):
    class Down(Google):
        def __call__(self, request):
            self.requests.append(request)
            return httpx.Response(429, json={"error": {"status": "RESOURCE_EXHAUSTED"}})

    reader = _reader(cat, Down(), tiers=True)
    with pytest.raises(GeminiError) as exc:
        reader(PDF, tenant_cui=CUI)
    for model in (LITE, LITE2, STRONG, STRONG2):
        assert f"{model}: Google AI Studio answered HTTP 429" in str(exc.value)
    assert KEY not in str(exc.value)


def test_a_wait_past_the_bound_refuses_rather_than_hangs(cat):
    google, sleeps = Google(), []
    reader = _reader(cat, google, sleeps=sleeps)
    reader.limiter._blocked[MODEL] = reader.limiter.clock() + 600
    with pytest.raises(GeminiError, match="rate limit: .* full for another 600 s"):
        reader(PDF, tenant_cui=CUI)
    assert google.requests == [] and sleeps == []
    assert [c.status for c in reader.calls.rows] == ["failed"]


def test_the_token_limit_counts_what_google_counted():
    clock = Clock()
    limiter, limit = RateLimiter(clock=clock, wall=Wall(clock)), RateLimit(rpm=100, tpm=10_000)
    assert limiter.take("m", limit, 4_000) == 0
    limiter.settle("m", 4_000, 9_000)
    assert limiter.take("m", limit, 4_000) == 60.0  # 9 000 + 4 000 > 10 000
    clock.now += 60
    assert limiter.take("m", limit, 4_000) == 0
    assert limiter.take("m", limit, 50_000) > 0  # over the limit only once others are in
    clock.now += 60
    assert limiter.take("m", limit, 50_000) == 0  # alone: Google judges it


def test_the_day_resets_at_pacific_midnight():
    clock = Clock()
    limiter, limit = (
        RateLimiter(clock=clock, wall=Wall(clock)),
        RateLimit(rpm=100, tpm=10**6, rpd=2),
    )
    assert limiter.take("m", limit, 1) == 0 and limiter.take("m", limit, 1) == 0
    wait = limiter.take("m", limit, 1)
    assert wait == 15 * 3600  # 09:00 → midnight Pacific
    clock.now += wait
    assert limiter.take("m", limit, 1) == 0


# ----- the second run (00_LAW §8 A4) -----


class ByModel(Google):
    """Google answering per model: *answers* maps a model to its answer."""

    def __init__(self, answers):
        super().__init__()
        self.answers = answers

    def __call__(self, request):
        self.answer = self.answers.get(_model_of(request), ANSWER)
        return super().__call__(request)


UNTIED = {  # a credit misread: 5 000 − 1 210 + 50 ≠ 4 290
    **ANSWER,
    "tables": [
        TABLES[0],
        {
            **TABLES[1],
            "rows": [[*r[:4], "50,00"] if r[4] == "500,00" else r for r in TABLES[1]["rows"]],
        },
    ],
}


def test_a_lite_read_that_does_not_tie_is_read_again_by_the_strong_tier(cat):
    google = ByModel({LITE: UNTIED})
    o = _ops(cat, google, tiers=True)
    resp = _upload(o)
    assert resp.status_code == 200, resp.text
    assert [_model_of(r) for r in google.requests] == [LITE, STRONG]
    calls = o.http.get("/model-calls", params={"role": "ocr_extract"}, headers=o.op).json()
    assert [(c["model"], c["output"]["tier"]) for c in calls] == [
        (STRONG, "strong"),
        (LITE, "everyday"),
    ]
    assert "second run" in calls[0]["reason"]
    _upload(o)  # the stored extract is the strong one: no third call
    assert len(google.requests) == 2


def test_a_read_that_never_ties_is_refused_and_not_stored(cat):
    google = ByModel({LITE: UNTIED, STRONG: UNTIED})
    o = _ops(cat, google, tiers=True)
    resp = _upload(o)
    assert resp.status_code == 422
    assert f"read by {LITE}, then {STRONG}" in resp.json()["detail"]
    _upload(o)  # nothing was stored: it is read again
    assert [_model_of(r) for r in google.requests] == [LITE, STRONG, LITE, STRONG]


def test_a_strong_read_is_not_run_twice(cat):
    google = ByModel({STRONG: UNTIED})
    o = _ops(cat, google, tiers=True)
    resp = _upload(o, strong=True)
    assert resp.status_code == 422 and f"(read by {STRONG})" in resp.json()["detail"]
    assert [_model_of(r) for r in google.requests] == [STRONG]


def test_the_evaluation_reads_with_one_model_only(cat):
    google = Google(status=429)
    o = _ops(cat, google, tiers=True)
    out = o.rt.ocr_eval(CUI, "simple", None)
    assert {_model_of(r) for r in google.requests} == {LITE}  # never another tier
    assert out["scores"][0]["read"] is False
