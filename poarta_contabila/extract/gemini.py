"""WP-36: Gemini reads a statement PDF, directly through Google AI Studio — synthetic tenants only.

The owner's decision of 2026-10-02 (``00_LAW.md`` §3 invariant 5): document reading on
synthetic data goes straight to Google AI Studio with the key in
``GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC``; every other role stays on OpenRouter; client data only
ever takes the EU route. The AI Studio free tier may use what it is sent to improve Google's
products, so nothing but invented documents may reach it.

Before any request, in this order, the reader refuses:

1. a tenant that is not ``data_class: synthetic`` (checked here, again, whatever the caller
   checked) — nothing of a client's is ever sent;
2. ``MODEL_CALLS`` other than ``live``; a role without a model (``route_check``);
3. a missing key.

The request (Gemini API ``generateContent``, v1beta): the role card's brief as the system
instruction, the PDF as inline data, JSON output constrained to ``STATEMENT_SCHEMA``
(``responseSchema``), temperature 0. The answer must be the card's
output shape — ``header`` (strings) and ``tables`` (``[{headers, rows}]`` of strings) — or the
statement is refused. Nothing is trusted from it: ``parse_statement`` then checks one side per
line, whole cents, opening − debits + credits = closing, and the holder CUI.

Every call is recorded in ``domain.model_calls`` (``sent`` or ``failed``) with the PDF's
sha256 and size, never its bytes, and never the key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from poarta_contabila.extract.contract import Extraction, ExtractMeta
from poarta_contabila.model_roles import (
    ModelRole,
    RateLimit,
    RouteRefused,
    brief,
    record,
    route_check,
)

KEY_ENV = "GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# Google answers 503 UNAVAILABLE (and 500/504) when the model is busy; its guidance is to
# retry with backoff. Bounded: ATTEMPTS tries in all, BACKOFF seconds before each retry.
# 429 is a rate limit, not a busy model: the reader moves to the backup instead (A3).
TRANSIENT = frozenset({500, 503, 504})
ATTEMPTS = 3
BACKOFF = (2.0, 6.0)
WINDOW = 60.0  # the quotas are per minute
MAX_WAIT = 90.0  # longest wait for a free slot before the statement is refused
PAGE_TOKENS = 258  # Google counts a PDF page as 258 input tokens
BRIEF_TOKENS = 1_000  # the brief, the prompt and the schema, rounded up
MAX_PDF_BYTES = 18 * 1024 * 1024  # inline data rides in a request Google caps at 20 MB
PROMPT = (
    "Read this bank statement. Answer with one JSON object in the output shape of your "
    "instructions: `header` and `tables`. Copy values exactly as printed."
)
_HEADER_FIELDS = ("iban", "holder_cui", "currency", "opening", "closing", "statement_date")
_TEXT = {"type": "STRING"}
STATEMENT_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "header": {
            "type": "OBJECT",
            "properties": {name: _TEXT for name in _HEADER_FIELDS},
            "required": list(_HEADER_FIELDS),
        },
        "tables": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "headers": {"type": "ARRAY", "items": _TEXT},
                    "rows": {"type": "ARRAY", "items": {"type": "ARRAY", "items": _TEXT}},
                },
                "required": ["headers", "rows"],
            },
        },
    },
    "required": ["header", "tables"],
}
"""The card's output shape as the Gemini API's ``responseSchema`` (an OpenAPI subset): the
answer is constrained to it, and ``parse_answer`` still checks it (fail closed)."""


class GeminiError(ValueError):
    """The PDF was not read; nothing is emitted. Never carries the key."""


class RateLimited(GeminiError):
    """Google answered 429: this model's quota is spent for now."""


def estimate_tokens(pdf: bytes) -> int:
    """Input tokens a PDF will cost, before sending (its pages, plus the brief)."""
    pages = len(re.findall(rb"/Type\s*/Page(?!s)", pdf)) or 1
    return pages * PAGE_TOKENS + BRIEF_TOKENS


@dataclass
class RateLimiter:
    """Requests and tokens per model over the last minute, shared by every reader in the
    process (00_LAW §8 A3). Only counts what this process sent: Google stays the judge (429)."""

    clock: Callable[[], float] = time.monotonic
    _sent: dict[str, deque[list[float]]] = field(default_factory=dict)
    _blocked: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def take(self, model: str, limit: RateLimit, tokens: int) -> float:
        """0 and the slot is taken; else the seconds until one may be free."""
        with self._lock:
            now = self.clock()
            sent = self._sent.setdefault(model, deque())
            while sent and sent[0][0] <= now - WINDOW:
                sent.popleft()
            waits = [self._blocked.get(model, now) - now]
            if len(sent) >= limit.rpm:
                waits.append(sent[len(sent) - limit.rpm][0] + WINDOW - now)
            used = sum(t for _, t in sent)
            if sent and used + tokens > limit.tpm:  # alone over the limit: let Google judge
                freed = used + tokens - limit.tpm
                for at, spent in sent:
                    freed -= spent
                    if freed <= 0:
                        waits.append(at + WINDOW - now)
                        break
                else:  # fits only alone: once the whole minute has passed
                    waits.append(sent[-1][0] + WINDOW - now)
            wait = max(waits)
            if wait > 0:
                return wait
            sent.append([now, tokens])
            return 0.0

    def settle(self, model: str, estimated: int, actual: int) -> None:
        """Replace the newest estimate for *model* with the tokens Google counted."""
        with self._lock:
            for entry in reversed(self._sent.get(model, ())):
                if entry[1] == estimated:
                    entry[1] = actual
                    return

    def exhaust(self, model: str) -> None:
        """Google said 429: no request to *model* for a whole window."""
        with self._lock:
            self._blocked[model] = self.clock() + WINDOW


LIMITER = RateLimiter()


def _strings(value: Any, where: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise GeminiError(f"Gemini's answer: {where} is not a list of strings")
    return value


def parse_answer(text: str) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """The card's output shape, or :class:`GeminiError`. Strings only; no other keys."""
    try:
        data = json.loads(text)
    except ValueError:
        raise GeminiError("Gemini's answer is not JSON") from None
    if not isinstance(data, dict) or set(data) - {"header", "tables"}:
        raise GeminiError("Gemini's answer is not {header, tables}")
    header = data.get("header") or {}
    if not isinstance(header, dict) or not all(isinstance(v, str) for v in header.values()):
        raise GeminiError("Gemini's answer: header is not a map of strings")
    tables = []
    for i, table in enumerate(data.get("tables") or []):
        if not isinstance(table, dict) or set(table) - {"headers", "rows"}:
            raise GeminiError(f"Gemini's answer: table {i} is not {{headers, rows}}")
        rows = table.get("rows") or []
        if not isinstance(rows, list):
            raise GeminiError(f"Gemini's answer: table {i} rows are not a list")
        tables.append(
            {
                "headers": _strings(table.get("headers") or [], f"table {i} headers"),
                "rows": [_strings(r, f"table {i} row {j}") for j, r in enumerate(rows)],
            }
        )
    return {k: v for k, v in header.items() if k in _HEADER_FIELDS}, tables


def _markdown(header: dict[str, str], tables: list[dict[str, Any]]) -> str:
    """What the identity checks read: the printed header, labelled, then the tables."""
    lines = [
        f"IBAN: {header.get('iban', '')}",
        f"CUI titular: {header.get('holder_cui', '')}",
        f"Moneda: {header.get('currency', '')}",
        f"Sold initial: {header.get('opening', '')}",
        f"Sold final: {header.get('closing', '')}",
        f"Data extras: {header.get('statement_date', '')}",
    ]
    for table in tables:
        lines += ["", " | ".join(table["headers"])]
        lines += [" | ".join(r) for r in table["rows"]]
    return "\n".join(lines)


def _holder_is(header: dict[str, str], cui: str) -> bool:
    printed = re.sub(r"^RO", "", "".join(header.get("holder_cui", "").split()).upper())
    return printed == cui


@dataclass
class GeminiStatementReader:
    """Reads one synthetic tenant's statement PDF into the extract contract (WP-36)."""

    role: ModelRole
    key: str
    calls: Any  # the model-call store
    synthetic: Callable[[str | None], bool]
    mode: str = "live"
    http: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=180.0))
    backend: str = "gemini"
    sleep: Callable[[float], None] = time.sleep
    limiter: RateLimiter = field(default_factory=lambda: LIMITER)

    def _record(
        self, payload: dict, cui: str, status: str, reason: str, output=None, model=None
    ) -> None:
        role = self.role if model is None else self.role.model_copy(update={"model": model})
        self.calls.add(
            record(
                role,
                payload,
                mode=self.mode,
                tenant_cui=cui,
                status=status,
                reason=reason,
                output=output,
            )
        )

    def __call__(self, pdf: bytes, *, tenant_cui: str) -> Extraction:
        return self.read(pdf, tenant_cui=tenant_cui)[0]

    def read(self, pdf: bytes, *, tenant_cui: str) -> tuple[Extraction, dict[str, str]]:
        """The extraction and the header as printed (the evaluation scores both)."""
        source_hash = hashlib.sha256(pdf).hexdigest()
        payload = {
            "tenant_cui": tenant_cui,
            "file": {"sha256": source_hash, "bytes": len(pdf), "content_type": "application/pdf"},
        }
        if not self.synthetic(tenant_cui):  # 1: never a client's document
            reason = "client data never goes to Google AI Studio; only the EU route"
            self._record(payload, tenant_cui, "refused", reason)
            raise GeminiError(reason)
        try:  # 2
            route_check(self.role, tenant_synthetic=True, mode=self.mode)
            if self.mode != "live":
                raise RouteRefused(f"{self.role.role_id}: MODEL_CALLS is {self.mode!r}, not live")
        except RouteRefused as exc:
            self._record(payload, tenant_cui, "refused", str(exc))
            raise GeminiError(str(exc)) from None
        if not self.key:  # 3
            self._record(payload, tenant_cui, "refused", f"{KEY_ENV} is not set")
            raise GeminiError(f"{KEY_ENV} is not set")
        if len(pdf) > MAX_PDF_BYTES:
            self._record(payload, tenant_cui, "refused", "the PDF is over 18 MB")
            raise GeminiError("the PDF is over 18 MB; send its tables instead")

        model = str(self.role.model)
        try:
            header, tables, version, model = self._read_within_limits(pdf)
        except GeminiError as exc:
            self._record(payload, tenant_cui, "failed", str(exc))
            raise
        backup = model != self.role.model
        self._record(
            payload,
            tenant_cui,
            "sent",
            "read by Gemini (Google AI Studio, synthetic)"
            + (f"; backup: {self.role.model} was at its rate limit" if backup else ""),
            model=model,
            output={
                "model_version": version,
                "backup": backup,
                "header": header,
                "tables": len(tables),
                "rows": sum(len(t["rows"]) for t in tables),
            },
        )
        extraction = Extraction(
            markdown=_markdown(header, tables),
            tables=tables,
            meta=ExtractMeta(
                backend="gemini",
                source_hash=source_hash,
                model_or_version=version or model,
                needs_ocr=False,  # Gemini did the reading
                identity_ok=_holder_is(header, tenant_cui),
            ),
        )
        return extraction, header

    def _models(self) -> list[str]:
        return [m for m in (self.role.model, self.role.backup_model) if m]

    def _slot(self, models: list[str], tokens: int) -> str:
        """The first of *models* with a free slot, waiting (at most MAX_WAIT) when none has."""
        waited = 0.0
        while True:
            waits = {}
            for model in models:
                limit = self.role.rate_limits.get(model)
                wait = 0.0 if limit is None else self.limiter.take(model, limit, tokens)
                if wait <= 0:
                    return model
                waits[model] = wait
            wait = min(waits.values())
            if waited + wait > MAX_WAIT:
                raise GeminiError(
                    f"rate limit: {', '.join(models)} full for another {wait:.0f} s"
                    " (Google AI Studio free tier)"
                )
            self.sleep(wait)
            waited += wait

    def _read_within_limits(
        self, pdf: bytes
    ) -> tuple[dict[str, str], list[dict[str, Any]], str, str]:
        """The main model while it has quota, else the backup (00_LAW §8 A3)."""
        tokens = estimate_tokens(pdf)
        models = self._models()
        for _ in range(len(models) + 1):
            model = self._slot(models, tokens)
            try:
                header, tables, version, used = self._generate(pdf, model, tokens)
            except RateLimited:
                self.limiter.exhaust(model)
                continue
            self.limiter.settle(model, tokens, used or tokens)
            return header, tables, version, model
        raise GeminiError(
            f"Google AI Studio answered HTTP 429 RESOURCE_EXHAUSTED for {', '.join(models)}"
        )

    def _generate(
        self, pdf: bytes, model: str, tokens: int
    ) -> tuple[dict[str, str], list[dict[str, Any]], str, int]:
        url = f"{BASE_URL}/models/{model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": brief(self.role)}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "application/pdf",
                                "data": base64.b64encode(pdf).decode(),
                            }
                        },
                        {"text": PROMPT},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": STATEMENT_SCHEMA,
            },
        }
        data, attempt = {}, 0
        while True:
            attempt += 1
            last = attempt >= ATTEMPTS
            try:
                response = self.http.post(url, json=body, headers={"x-goog-api-key": self.key})
            except httpx.HTTPError as exc:
                if last:
                    raise GeminiError(
                        f"Google AI Studio unreachable: {type(exc).__name__}"
                        f" (after {attempt} attempts)"
                    ) from None
                self.sleep(BACKOFF[attempt - 1])
                self._slot([model], tokens)
                continue
            try:
                data = response.json()
            except ValueError:
                data = {}
            if response.status_code == 200:
                break
            status = ((data or {}).get("error") or {}).get("status") or ""
            message = f"Google AI Studio answered HTTP {response.status_code} {status}"
            if response.status_code == 429:
                raise RateLimited(message)
            if response.status_code not in TRANSIENT:
                raise GeminiError(message)
            if last:
                raise GeminiError(f"{message} (after {attempt} attempts)")
            self.sleep(BACKOFF[attempt - 1])
            self._slot([model], tokens)
        blocked = (data.get("promptFeedback") or {}).get("blockReason")
        if blocked:
            raise GeminiError(f"Google AI Studio blocked the request: {blocked}")
        candidates = data.get("candidates") or []
        if not candidates:
            raise GeminiError("Google AI Studio answered no candidate")
        first = candidates[0]
        if first.get("finishReason") not in (None, "STOP"):
            raise GeminiError(f"Gemini stopped early: {first.get('finishReason')}")
        text = "".join(p.get("text", "") for p in (first.get("content") or {}).get("parts") or [])
        header, tables = parse_answer(text)
        used = int((data.get("usageMetadata") or {}).get("totalTokenCount") or 0)
        return header, tables, str(data.get("modelVersion") or ""), used


def gemini_reader_from_env(
    roles: dict[str, ModelRole], calls: Any, synthetic: Callable[[str | None], bool], mode: str
) -> GeminiStatementReader | None:
    """The reader when ``MODEL_CALLS=live`` and the key is set; else None."""
    key = os.environ.get(KEY_ENV)
    role = roles.get("ocr_extract")
    if mode != "live" or not key or role is None or role.route != "google_ai_studio":
        return None
    return GeminiStatementReader(role=role, key=key, calls=calls, synthetic=synthetic, mode=mode)
