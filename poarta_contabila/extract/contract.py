"""The extract contract (ARCHITECTURE.md §15): what a backend leaves under the source's prefix.

    {prefix}/normalized/markdown.md        text the graph may read
    {prefix}/normalized/tables.json        [{headers, rows}] as strings
    {prefix}/normalized/extract_meta.json  backend, source_hash, model_or_version, needs_ocr,
                                           identity_ok

An extract is done once per ``(source_hash, backend)`` (ARCHITECTURE.md §16): the files are
written first, then the row (``domain.extracts``) that proves them; a second upload of the
same file reuses them and never calls the backend again.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field

from poarta_contabila.types import Closed

Backend = Literal["document_ai", "gemini", "ubl", "mt940", "docling", "none"]


class ExtractMeta(Closed):
    backend: Backend
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_or_version: str
    needs_ocr: bool
    identity_ok: bool


@dataclass(frozen=True)
class Extraction:
    markdown: str
    tables: list[dict[str, Any]]
    meta: ExtractMeta


def _keys(prefix: str) -> dict[str, str]:
    return {
        name: f"{prefix}/normalized/{name}"
        for name in ("markdown.md", "tables.json", "extract_meta.json")
    }


def write_extraction(blobs: Any, prefix: str, extraction: Extraction) -> None:
    keys = _keys(prefix)
    blobs.put(keys["markdown.md"], extraction.markdown.encode())
    blobs.put(
        keys["tables.json"], json.dumps(extraction.tables, ensure_ascii=False, indent=1).encode()
    )
    blobs.put(keys["extract_meta.json"], extraction.meta.model_dump_json(indent=1).encode())


def read_extraction(blobs: Any, prefix: str) -> Extraction:
    keys = _keys(prefix)
    return Extraction(
        markdown=blobs.get(keys["markdown.md"]).decode(),
        tables=json.loads(blobs.get(keys["tables.json"])),
        meta=ExtractMeta.model_validate_json(blobs.get(keys["extract_meta.json"])),
    )


@dataclass
class InMemoryExtractStore:
    rows: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)

    def get(self, source_hash: str, backend: str) -> dict[str, Any] | None:
        """``{"prefix", "meta"}`` of the stored extract, or None."""
        return self.rows.get((source_hash, backend))

    def put(self, meta: ExtractMeta, prefix: str) -> None:
        self.rows.setdefault(
            (meta.source_hash, meta.backend), {"prefix": prefix, "meta": meta.model_dump()}
        )


class PostgresExtractStore:
    """``domain.extracts``, one row per ``(source_hash, backend)``."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def get(self, source_hash: str, backend: str) -> dict[str, Any] | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT prefix, meta FROM domain.extracts WHERE source_hash = %s AND backend = %s",
                (source_hash, backend),
            ).fetchone()
        return {"prefix": row[0], "meta": row[1]} if row else None

    def put(self, meta: ExtractMeta, prefix: str) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.extracts (source_hash, backend, meta, prefix)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (source_hash, backend) DO NOTHING",
                (meta.source_hash, meta.backend, meta.model_dump_json(), prefix),
            )
