"""Google Document AI reads statement PDFs (ARCHITECTURE.md §15 backend ``document_ai``).

Built only from Google's official REST description of the Cloud Document AI API v1 (the
Discovery document, revision 20260915; quoted in RESEARCH_LOG.md R3):

- ``POST v1/{+name}:process`` — "Processes a single document". ``name`` is
  ``projects/{project}/locations/{location}/processors/{processor}`` or a
  ``…/processorVersions/{processorVersion}``; OAuth scope ``cloud-platform``.
- Request ``rawDocument {content, mimeType}`` (``content`` is bytes, base64 in JSON) and
  ``skipHumanReview``. Response ``document``: ``text``; ``pages[].tables[]`` with
  ``headerRows`` / ``bodyRows`` of ``cells`` (``colSpan``, ``rowSpan``,
  ``layout.textAnchor``: ``content`` or ``textSegments`` indexing ``Document.text``);
  ``error``; ``shardInfo``.
- Regional endpoints by processor location (``eu`` → ``documentai.eu.rep.googleapis.com``).

Only the tables are read: the header (IBAN, holder, balances, date) is typed by a person,
and ``parse_statement`` checks that the lines tie to it, so a misread cell refuses the
statement instead of minting a wrong Job. Nothing here guesses a counterparty.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from poarta_contabila.extract.contract import Extraction, ExtractMeta
from poarta_contabila.extract.statement import _plain

SCOPE = "https://www.googleapis.com/auth/cloud-platform"
DISCOVERY_REVISION = "20260915"

ENDPOINTS: dict[str, str] = {
    "us": "https://documentai.us.rep.googleapis.com/",
    "eu": "https://documentai.eu.rep.googleapis.com/",
    "asia-south1": "https://documentai.asia-south1.rep.googleapis.com/",
    "asia-southeast1": "https://documentai.asia-southeast1.rep.googleapis.com/",
    "northamerica-northeast1": "https://documentai.northamerica-northeast1.rep.googleapis.com/",
    "australia-southeast1": "https://documentai.australia-southeast1.rep.googleapis.com/",
    "europe-west2": "https://documentai.europe-west2.rep.googleapis.com/",
    "europe-west3": "https://documentai.europe-west3.rep.googleapis.com/",
}
"""The Discovery document's regional endpoints. A location not listed is refused."""

_NAME = re.compile(
    r"^projects/[^/]+/locations/(?P<location>[^/]+)/processors/[^/]+"
    r"(/processorVersions/[^/]+)?$"
)


class DocumentAiError(ValueError):
    """The PDF was not read; nothing is emitted."""


def endpoint(processor: str) -> str:
    """The regional endpoint for a processor resource name."""
    match = _NAME.match(processor)
    if match is None:
        raise DocumentAiError(
            "DOCUMENT_AI_PROCESSOR must be projects/{project}/locations/{location}/processors/"
            "{processor}[/processorVersions/{version}]"
        )
    location = match["location"]
    if location not in ENDPOINTS:
        raise DocumentAiError(f"no Document AI regional endpoint is documented for {location!r}")
    return ENDPOINTS[location]


# ----- Document → tables -----


def _text(layout: dict[str, Any] | None, text: str) -> str:
    anchor = (layout or {}).get("textAnchor") or {}
    if anchor.get("content") is not None:
        raw = str(anchor["content"])
    else:
        parts = []
        for segment in anchor.get("textSegments") or []:
            start, end = int(segment.get("startIndex", 0)), int(segment.get("endIndex", 0))
            if not 0 <= start <= end <= len(text):
                raise DocumentAiError("a table cell points outside the document text")
            parts.append(text[start:end])
        raw = "".join(parts)
    return " ".join(raw.split())


def _grid(rows: list[dict[str, Any]], text: str) -> list[list[str]]:
    """Rows of cell texts, one string per column (HTML table layout: spans leave blanks)."""
    grid: list[list[str]] = []
    taken: set[tuple[int, int]] = set()  # (row, column) slots a cell above spans into
    for r, row in enumerate(rows):
        out: list[str] = []
        for cell in row.get("cells") or []:
            while (r, len(out)) in taken:
                out.append("")
            cols = max(int(cell.get("colSpan") or 1), 1)
            spans = max(int(cell.get("rowSpan") or 1), 1)
            start = len(out)
            out.append(_text(cell.get("layout"), text))
            out.extend([""] * (cols - 1))
            taken.update((r + dr, start + dc) for dr in range(1, spans) for dc in range(cols))
        while (r, len(out)) in taken:
            out.append("")
        grid.append(out)
    return grid


def _header(rows: list[list[str]]) -> list[str]:
    """One label per column: the lowest non-empty header cell above it."""
    width = max((len(r) for r in rows), default=0)
    labels = []
    for c in range(width):
        cells = [r[c] for r in rows if c < len(r) and r[c]]
        labels.append(cells[-1] if cells else "")
    return labels


def tables_from_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    """The extract contract's ``tables.json``: every detected table, page by page.

    A table without header rows whose rows have the previous table's width continues it
    (a statement's movements run over pages) and takes its labels; otherwise it keeps no
    labels, so ``parse_statement`` cannot mistake it for the movement table.
    """
    text = document.get("text") or ""
    out: list[dict[str, Any]] = []
    previous: list[str] | None = None
    for page in document.get("pages") or []:
        for table in page.get("tables") or []:
            header_rows = _grid(table.get("headerRows") or [], text)
            body = _grid(table.get("bodyRows") or [], text)
            if header_rows:
                headers = _header(header_rows)
                previous = headers
            elif previous is not None and body and all(len(r) == len(previous) for r in body):
                headers = previous
            else:
                headers = []
            out.append({"headers": headers, "rows": body})
    return out


_FISCAL_LABEL = (
    r"(?:\bro ?"  # RO1000009, RO 1000009
    r"|\b(?:c\.? ?u\.? ?i|c\.? ?i\.? ?f|cod (?:unic|fiscal|de identificare))\b[^\d]{0,40})"
)


def shows_cui(text: str, cui: str) -> bool:
    """The tenant's CUI is printed on the document: after ``RO`` or a fiscal-code label
    (CUI, CIF, cod fiscal, cod unic …), so a date or an amount never stands in for it."""
    plain = _plain(text)
    return re.search(rf"{_FISCAL_LABEL}{re.escape(cui)}(?!\d)", plain) is not None


def shows_iban(text: str, iban: str) -> bool:
    flat = "".join(text.split()).upper()
    return "".join(iban.split()).upper() in flat


# ----- the call -----


def service_account_token(credentials_json: str | None) -> Callable[[], str]:
    """A bearer token for the ``cloud-platform`` scope, refreshed when it expires.

    From the service-account key in *credentials_json*, else Application Default
    Credentials (``GOOGLE_APPLICATION_CREDENTIALS``). Built on first use, so a bad key
    refuses a statement instead of stopping the service.
    """
    lock = threading.Lock()
    state: dict[str, Any] = {}

    def token() -> str:
        import google.auth
        import urllib3
        from google.auth.transport.urllib3 import Request
        from google.oauth2 import service_account

        with lock:
            try:
                if "creds" not in state:
                    if credentials_json:
                        state["creds"] = service_account.Credentials.from_service_account_info(
                            json.loads(credentials_json), scopes=[SCOPE]
                        )
                    else:
                        state["creds"], _ = google.auth.default(scopes=[SCOPE])
                    state["request"] = Request(urllib3.PoolManager())
                creds = state["creds"]
                if not creds.valid:
                    creds.refresh(state["request"])
                return str(creds.token)
            except Exception as exc:  # never echo key material
                raise DocumentAiError(f"Document AI credentials: {type(exc).__name__}") from None

    return token


@dataclass
class DocumentAiReader:
    """Reads one statement PDF into the extract contract."""

    processor: str
    token: Callable[[], str]
    http: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=120.0))

    def process(self, pdf: bytes) -> dict[str, Any]:
        url = f"{endpoint(self.processor)}v1/{self.processor}:process"
        body = {
            "rawDocument": {
                "content": base64.b64encode(pdf).decode(),
                "mimeType": "application/pdf",
            },
            "skipHumanReview": True,
        }
        try:
            response = self.http.post(
                url, json=body, headers={"Authorization": f"Bearer {self.token()}"}
            )
        except httpx.HTTPError as exc:
            raise DocumentAiError(f"Document AI unreachable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise DocumentAiError(f"Document AI answered HTTP {response.status_code}")
        try:
            document = response.json().get("document")
        except ValueError as exc:
            raise DocumentAiError("Document AI answered no JSON") from exc
        if not isinstance(document, dict):
            raise DocumentAiError("Document AI answered no document")
        if document.get("error"):
            message = (document["error"] or {}).get("message") or "error"
            raise DocumentAiError(f"Document AI could not read the PDF: {message}")
        if int((document.get("shardInfo") or {}).get("shardCount") or 1) > 1:
            raise DocumentAiError("Document AI returned a shard of a larger document")
        return document

    def __call__(self, pdf: bytes, *, tenant_cui: str) -> Extraction:
        document = self.process(pdf)
        text = document.get("text") or ""
        processors = sorted(
            {r["processor"] for r in document.get("revisions") or [] if r.get("processor")}
        )
        return Extraction(
            markdown=text,
            tables=tables_from_document(document),
            meta=ExtractMeta(
                backend="document_ai",
                source_hash=hashlib.sha256(pdf).hexdigest(),
                model_or_version=", ".join(processors) or self.processor,
                needs_ocr=False,  # Document AI did the reading, OCR included
                identity_ok=shows_cui(text, tenant_cui),
            ),
        )


def document_ai_from_env() -> DocumentAiReader | None:
    """The reader from ``DOCUMENT_AI_PROCESSOR`` (+ ``DOCUMENT_AI_CREDENTIALS_JSON``, else
    Application Default Credentials); None when no processor is configured."""
    processor = os.environ.get("DOCUMENT_AI_PROCESSOR")
    if not processor:
        return None
    return DocumentAiReader(
        processor=processor,
        token=service_account_token(os.environ.get("DOCUMENT_AI_CREDENTIALS_JSON") or None),
    )
