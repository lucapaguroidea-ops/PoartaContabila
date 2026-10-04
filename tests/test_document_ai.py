"""Google Document AI reads statement PDFs into the extract contract (ARCHITECTURE.md §15),
which feeds parse_statement. The HTTP client is mocked; the Document is synthetic and
shaped as the official v1 Discovery document describes it (RESEARCH_LOG.md R3)."""

from __future__ import annotations

import base64
import hashlib
import json
import os

import httpx
import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.extract.contract import ExtractMeta, InMemoryExtractStore
from poarta_contabila.extract.document_ai import (
    DocumentAiError,
    DocumentAiReader,
    document_ai_from_env,
    endpoint,
    service_account_token,
    shows_iban,
    tables_from_document,
)
from tests.test_controls import CUI
from tests.test_extras import IBAN, META, PDF

PROCESSOR = "projects/test-project/locations/eu/processors/0123abcd"
HEADER = (
    "EXTRAS DE CONT\nTitular: FIRMA TEST SRL, C.U.I. RO1000009\n"
    "IBAN: RO49 AAAA 1B31 0075 9384 0000\n"  # the textbook example IBAN, not a client's
)


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


class DocBuilder:
    """A synthetic Document: cells index into ``text`` as textSegments."""

    def __init__(self, header=HEADER):
        self.text = header

    def cell(self, value, **span):
        start = len(self.text)
        self.text += value + "\n"
        segment = {"startIndex": str(start), "endIndex": str(start + len(value))}
        return {"layout": {"textAnchor": {"textSegments": [segment]}}, **span}

    def row(self, *values):
        return {
            "cells": [
                self.cell(v[0], **v[1]) if isinstance(v, tuple) else self.cell(v) for v in values
            ]
        }

    def document(self, pages):
        return {"text": self.text, "pages": pages}


def _statement_document(header=HEADER):
    b = DocBuilder(header)
    span2 = {"rowSpan": 2}
    movements = {
        "headerRows": [
            b.row(
                ("Data", span2),
                ("Descriere", span2),
                ("Referinta", span2),
                ("Suma", {"colSpan": 2}),
            ),
            b.row("Debit", "Credit"),
        ],
        "bodyRows": [
            b.row("15.09.2026", "Plată FURNIZOR TEST SRL fact 1427", "OP-77", "1.210,00", ""),
        ],
    }
    page2 = {  # the same table running on: no header rows, same width
        "bodyRows": [
            b.row("20.09.2026", "Încasare CLIENT TEST SRL FX-101", "", "", "500,00"),
            b.row("", "Total rulaje", "", "1.210,00", "500,00"),
        ]
    }
    return b.document(
        [{"pageNumber": 1, "tables": [movements]}, {"pageNumber": 2, "tables": [page2]}]
    )


# ----- Document → tables -----


def test_tables_read_cells_spans_and_page_continuations():
    tables = tables_from_document(_statement_document())
    assert tables[0]["headers"] == ["Data", "Descriere", "Referinta", "Debit", "Credit"]
    assert tables[0]["rows"] == [
        ["15.09.2026", "Plată FURNIZOR TEST SRL fact 1427", "OP-77", "1.210,00", ""]
    ]
    assert tables[1]["headers"] == tables[0]["headers"]  # page 2 continues page 1
    assert tables[1]["rows"][0][1] == "Încasare CLIENT TEST SRL FX-101"


def test_a_headerless_table_of_another_width_keeps_no_labels():
    b = DocBuilder()
    doc = b.document(
        [
            {"tables": [{"headerRows": [b.row("Data", "Debit", "Credit")], "bodyRows": []}]},
            {"tables": [{"bodyRows": [b.row("Sold final", "4.290,00")]}]},
        ]
    )
    assert tables_from_document(doc)[1] == {"headers": [], "rows": [["Sold final", "4.290,00"]]}


def test_anchor_content_wins_and_a_missing_start_index_is_zero():
    doc = {
        "text": "Data\nx",
        "pages": [
            {
                "tables": [
                    {
                        "headerRows": [
                            {
                                "cells": [
                                    {
                                        "layout": {
                                            "textAnchor": {"textSegments": [{"endIndex": "4"}]}
                                        }
                                    },
                                    {"layout": {"textAnchor": {"content": "Debit\n (RON)"}}},
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
    }
    assert tables_from_document(doc)[0]["headers"] == ["Data", "Debit (RON)"]


def test_a_cell_outside_the_text_is_refused():
    doc = {
        "text": "abc",
        "pages": [
            {
                "tables": [
                    {
                        "bodyRows": [
                            {
                                "cells": [
                                    {
                                        "layout": {
                                            "textAnchor": {
                                                "textSegments": [
                                                    {"startIndex": "1", "endIndex": "9"}
                                                ]
                                            }
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
    }
    with pytest.raises(DocumentAiError, match="outside the document text"):
        tables_from_document(doc)


def test_iban_is_found_across_print_spacing():
    assert shows_iban(HEADER, IBAN) and not shows_iban(HEADER, "RO49AAAA1B31007593840001")


# ----- the call -----


class FakeDocumentAi:
    """The Document AI endpoint behind httpx.MockTransport; records requests."""

    def __init__(self, document=None, status=200, raise_exc=None):
        self.document = document if document is not None else _statement_document()
        self.status, self.raise_exc = status, raise_exc
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.raise_exc:
            raise self.raise_exc
        return httpx.Response(self.status, json={"document": self.document})

    def reader(self, processor=PROCESSOR):
        return DocumentAiReader(
            processor=processor,
            token=lambda: "test-token",
            http=httpx.Client(transport=httpx.MockTransport(self.handler)),
        )


def test_the_request_is_the_documented_process_call():
    fake = FakeDocumentAi()
    extraction = fake.reader()(PDF, tenant_cui=CUI)
    (request,) = fake.requests
    assert request.method == "POST"
    assert str(request.url) == f"https://documentai.eu.rep.googleapis.com/v1/{PROCESSOR}:process"
    assert request.headers["Authorization"] == "Bearer test-token"
    body = json.loads(request.content)
    assert base64.b64decode(body["rawDocument"]["content"]) == PDF
    assert body["rawDocument"]["mimeType"] == "application/pdf" and body["skipHumanReview"] is True
    assert extraction.meta == ExtractMeta(
        backend="document_ai",
        source_hash=hashlib.sha256(PDF).hexdigest(),
        model_or_version=PROCESSOR,
        needs_ocr=False,
        identity_ok=True,
    )
    assert extraction.markdown.startswith("EXTRAS DE CONT")


@pytest.mark.parametrize(
    "fake, says",
    [
        (FakeDocumentAi(status=403), "HTTP 403"),
        (FakeDocumentAi(raise_exc=httpx.ConnectError("refused")), "unreachable: ConnectError"),
        (FakeDocumentAi(document={"error": {"code": 3, "message": "bad pdf"}}), "bad pdf"),
        (FakeDocumentAi(document={"text": "", "shardInfo": {"shardCount": "2"}}), "shard"),
    ],
)
def test_a_failed_read_is_refused(fake, says):
    with pytest.raises(DocumentAiError, match=says):
        fake.reader()(PDF, tenant_cui=CUI)


@pytest.mark.parametrize(
    "processor, says",
    [
        ("my-processor", "must be projects/"),
        ("projects/p/locations/mars/processors/x", "no Document AI regional endpoint"),
    ],
)
def test_the_processor_name_and_location_must_be_documented(processor, says):
    with pytest.raises(DocumentAiError, match=says):
        endpoint(processor)


def test_a_pinned_processor_version_is_accepted():
    pinned = f"{PROCESSOR}/processorVersions/pretrained-v1"
    assert endpoint(pinned) == "https://documentai.eu.rep.googleapis.com/"


def test_env_wiring_and_bad_credentials_never_echo_the_key(monkeypatch):
    monkeypatch.delenv("DOCUMENT_AI_PROCESSOR", raising=False)
    assert document_ai_from_env() is None
    monkeypatch.setenv("DOCUMENT_AI_PROCESSOR", PROCESSOR)
    monkeypatch.setenv("DOCUMENT_AI_CREDENTIALS_JSON", '{"private_key": "secret-material"}')
    reader = document_ai_from_env()
    assert reader is not None and reader.processor == PROCESSOR
    with pytest.raises(DocumentAiError) as err:
        reader.token()
    assert "secret-material" not in str(err.value) and "credentials" in str(err.value)
    with pytest.raises(DocumentAiError):
        service_account_token("not json")()


# ----- runtime: upload without tables -----


def _ops(cat, fake=None, **over):
    from tests.test_runtime import Ops, _runtime

    o = Ops(_runtime(cat, statement_reader=fake.reader() if fake else None, **over))
    o.tenant()
    o.upload_rj()
    return o


def _post(o, meta=None, pdf=PDF):
    return o.http.post(
        f"/extras/{CUI}",
        headers=o.op,
        json={"meta": meta or META, "pdf_b64": base64.b64encode(pdf).decode()},
    )


def test_document_ai_feeds_the_statement_once(cat):
    fake = FakeDocumentAi()
    o = _ops(cat, fake)
    out = _post(o).json()
    assert out["lines"] == 2 and [j["created"] for j in out["jobs"]] == [True, True]
    assert {j["job"]["job_kind"] for j in out["jobs"]} == {"job_extras_line"}
    source_hash = hashlib.sha256(PDF).hexdigest()
    prefix = f"tenants/{CUI}/default/2026-09/extras/source/{source_hash}"
    for name in ("markdown.md", "tables.json", "extract_meta.json"):
        assert f"{prefix}/normalized/{name}" in o.rt.blobs.data
    meta = json.loads(o.rt.blobs.data[f"{prefix}/normalized/extract_meta.json"])
    assert meta["backend"] == "document_ai" and meta["identity_ok"] is True
    assert o.rt.extracts.get(source_hash, "document_ai")["prefix"] == prefix
    again = _post(o).json()  # the same PDF: the stored extract, no second call
    assert [j["created"] for j in again["jobs"]] == [False, False]
    assert len(fake.requests) == 1


def test_a_statement_that_does_not_show_the_tenant_is_refused(cat):
    no_cui = FakeDocumentAi(
        _statement_document(header="EXTRAS\nIBAN: RO49 AAAA 1B31 0075 9384 0000\n")
    )
    o = _ops(cat, no_cui)
    bad = _post(o)
    assert bad.status_code == 422 and "stmt_no_identity" in bad.json()["detail"]
    assert o.rt.jobs.jobs == {}
    other_iban = _post(
        _ops(cat, FakeDocumentAi()), meta={**META, "iban": "RO49AAAA1B31007593840001"}
    )
    assert other_iban.status_code == 422 and "does not show the IBAN" in other_iban.json()["detail"]


def test_a_misread_amount_refuses_the_statement(cat):
    doc = _statement_document()
    raw = json.dumps(doc).replace("1.210,00", "1.270,00")  # a cell read wrong: lines do not tie
    o = _ops(cat, FakeDocumentAi(json.loads(raw)))
    bad = _post(o)
    assert bad.status_code == 422 and "≠ closing" in bad.json()["detail"]
    assert o.rt.jobs.jobs == {}


def test_without_a_reader_the_tables_must_be_sent(cat):
    o = _ops(cat)
    bad = _post(o)
    assert bad.status_code == 422 and "no statement reader" in bad.json()["detail"]


def test_an_extract_of_another_tenant_is_not_reused(cat):
    extracts = InMemoryExtractStore()
    source_hash = hashlib.sha256(PDF).hexdigest()
    meta = ExtractMeta(
        backend="document_ai",
        source_hash=source_hash,
        model_or_version=PROCESSOR,
        needs_ocr=False,
        identity_ok=True,
    )
    extracts.put(meta, f"tenants/20000005/default/2026-09/extras/source/{source_hash}")
    fake = FakeDocumentAi()
    o = _ops(cat, fake, extracts=extracts)
    bad = _post(o)
    assert bad.status_code == 422 and "another tenant" in bad.json()["detail"]
    assert fake.requests == []


def test_postgres_extract_store_keeps_the_first_row():
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    import psycopg

    from poarta_contabila.db import schema_sql
    from poarta_contabila.extract.contract import PostgresExtractStore

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(schema_sql())
        conn.execute("DELETE FROM domain.extracts")
    store = PostgresExtractStore(dsn)
    meta = ExtractMeta(
        backend="document_ai",
        source_hash="a" * 64,
        model_or_version=PROCESSOR,
        needs_ocr=False,
        identity_ok=True,
    )
    store.put(meta, "tenants/1000009/default/2026-09/extras/source/" + "a" * 64)
    store.put(meta.model_copy(update={"identity_ok": False}), "tenants/other")
    row = store.get("a" * 64, "document_ai")
    assert row["prefix"].startswith("tenants/1000009/") and row["meta"]["identity_ok"] is True
    assert store.get("a" * 64, "ubl") is None
