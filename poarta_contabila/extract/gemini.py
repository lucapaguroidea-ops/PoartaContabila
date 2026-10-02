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
instruction, the PDF as inline data, JSON output, temperature 0. The answer must be the card's
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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from poarta_contabila.extract.contract import Extraction, ExtractMeta
from poarta_contabila.model_roles import ModelRole, RouteRefused, brief, record, route_check

KEY_ENV = "GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MAX_PDF_BYTES = 18 * 1024 * 1024  # inline data rides in a request Google caps at 20 MB
PROMPT = (
    "Read this bank statement. Answer with one JSON object in the output shape of your "
    "instructions: `header` and `tables`. Copy values exactly as printed."
)
_HEADER_FIELDS = ("iban", "holder_cui", "currency", "opening", "closing", "statement_date")


class GeminiError(ValueError):
    """The PDF was not read; nothing is emitted. Never carries the key."""


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

    def _record(self, payload: dict, cui: str, status: str, reason: str, output=None) -> None:
        self.calls.add(
            record(
                self.role,
                payload,
                mode=self.mode,
                tenant_cui=cui,
                status=status,
                reason=reason,
                output=output,
            )
        )

    def __call__(self, pdf: bytes, *, tenant_cui: str) -> Extraction:
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

        try:
            header, tables, version = self._generate(pdf)
        except GeminiError as exc:
            self._record(payload, tenant_cui, "failed", str(exc))
            raise
        self._record(
            payload,
            tenant_cui,
            "sent",
            "read by Gemini (Google AI Studio, synthetic)",
            output={
                "model_version": version,
                "header": header,
                "tables": len(tables),
                "rows": sum(len(t["rows"]) for t in tables),
            },
        )
        return Extraction(
            markdown=_markdown(header, tables),
            tables=tables,
            meta=ExtractMeta(
                backend="gemini",
                source_hash=source_hash,
                model_or_version=version or str(self.role.model),
                needs_ocr=False,  # Gemini did the reading
                identity_ok=_holder_is(header, tenant_cui),
            ),
        )

    def _generate(self, pdf: bytes) -> tuple[dict[str, str], list[dict[str, Any]], str]:
        url = f"{BASE_URL}/models/{self.role.model}:generateContent"
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
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
        }
        try:
            response = self.http.post(url, json=body, headers={"x-goog-api-key": self.key})
        except httpx.HTTPError as exc:
            raise GeminiError(f"Google AI Studio unreachable: {type(exc).__name__}") from None
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200:
            status = ((data or {}).get("error") or {}).get("status") or ""
            raise GeminiError(f"Google AI Studio answered HTTP {response.status_code} {status}")
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
        return header, tables, str(data.get("modelVersion") or "")


def gemini_reader_from_env(
    roles: dict[str, ModelRole], calls: Any, synthetic: Callable[[str | None], bool], mode: str
) -> GeminiStatementReader | None:
    """The reader when ``MODEL_CALLS=live`` and the key is set; else None."""
    key = os.environ.get(KEY_ENV)
    role = roles.get("ocr_extract")
    if mode != "live" or not key or role is None or role.route != "google_ai_studio":
        return None
    return GeminiStatementReader(role=role, key=key, calls=calls, synthetic=synthetic, mode=mode)
