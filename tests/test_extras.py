"""WP-13: PDF bank statements — a pack, one Job per movement line, never the statement total."""

from __future__ import annotations

import base64

import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.extract.statement import (
    StatementError,
    StatementMeta,
    line_source_hash,
    parse_statement,
)
from poarta_contabila.triage import decide_emit
from tests.test_controls import CUI, PERIOD
from tests.test_triage import _pack

IBAN = "RO49AAAA1B31007593840000"  # the textbook example IBAN, not a client's
META = {
    "iban": IBAN,
    "holder_cui": "RO1000009",
    "currency": "RON",
    "opening": "5000.00",
    "closing": "4290.00",
    "statement_date": "2026-09-30",
}
TABLES = [
    {"headers": ["Extras de cont", "", ""], "rows": [["Sold initial", "", "5.000,00"]]},
    {
        "headers": ["Data", "Descriere", "Referinta", "Debit", "Credit"],
        "rows": [
            ["15.09.2026", "Plata FURNIZOR TEST SRL fact 1427", "OP-77", "1.210,00", ""],
            ["", "  continuare descriere", "", "", ""],
            ["20.09.2026", "Incasare CLIENT TEST SRL FX-101", "", "", "500,00"],
            ["", "Total rulaje", "", "1.210,00", "500,00"],
        ],
    },
]
PDF = b"%PDF-1.4 synthetic statement"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _meta(**over):
    return StatementMeta.model_validate({**META, **over})


# ----- parsing -----


def test_two_line_statement_parses_and_balances():
    st = parse_statement(TABLES, _meta(), CUI)
    assert [(ln.seq, ln.date, ln.side, ln.amount) for ln in st.lines] == [
        (1, "2026-09-15", "debit", "1210.00"),
        (2, "2026-09-20", "credit", "500.00"),
    ]
    assert st.lines[0].reference == "OP-77" and st.holder_cui == CUI
    again = parse_statement(TABLES, _meta(), CUI)
    assert again.statement_id == st.statement_id  # same statement, same id
    assert line_source_hash(st.statement_id, 1) != line_source_hash(st.statement_id, 2)


@pytest.mark.parametrize(
    ("over", "tables", "match"),
    [
        ({"closing": "4290.01"}, TABLES, "≠ closing"),
        ({"holder_cui": "RO20000005"}, TABLES, "not the tenant"),
        ({"holder_cui": "ACME"}, TABLES, "no valid account-holder"),
        ({"currency": "EUR"}, TABLES, "RON statements only"),
        ({}, [{"headers": ["Data", "Suma"], "rows": [["15.09.2026", "1"]]}], "no movement table"),
        (
            {},
            [
                {
                    "headers": ["Data", "Descriere", "Debit", "Credit"],
                    "rows": [["15.09.2026", "x", "1,00", "2,00"]],
                }
            ],
            "exactly one side",
        ),
        (
            {},
            [
                {
                    "headers": ["Data", "Descriere", "Debit", "Credit"],
                    "rows": [["15.09.2026", "x", "1,005", ""]],
                }
            ],
            "whole number of cents",
        ),
    ],
)
def test_a_statement_that_does_not_read_or_add_up_is_refused(over, tables, match):
    with pytest.raises(StatementError, match=match):
        parse_statement(tables, _meta(**over), CUI)


def test_extras_without_tenant_identity_do_not_emit(cat):
    pack = _pack(
        source_doc_id="extras_statement_pdf", kinds=["pdf"], our_role="n/a", identity_ok=False
    )
    d = decide_emit(cat, pack)
    assert not d.emit and "identity_gate" in d.failed


# ----- runtime -----


def _ops(cat):
    from tests.test_runtime import Ops, _runtime

    o = Ops(_runtime(cat))
    o.tenant()
    o.upload_rj()
    return o


def _post(o, meta=None, tables=TABLES, pdf=PDF):
    return o.http.post(
        f"/extras/{CUI}",
        headers=o.op,
        json={"meta": meta or META, "tables": tables, "pdf_b64": base64.b64encode(pdf).decode()},
    )


def test_a_two_line_statement_mints_two_movement_jobs(cat):
    o = _ops(cat)
    out = _post(o).json()
    assert out["lines"] == 2 and [j["created"] for j in out["jobs"]] == [True, True]
    kinds = {j["job"]["job_kind"] for j in out["jobs"]}
    assert kinds == {"job_extras_line"}
    pay, cash_in = out["jobs"]
    # the payment is in the SAGA journal (Banca, 15.09, 1210.00): already in the books
    assert pay["job"]["status"] == "already_in_sink"
    # the receipt is not: approved as read, it names no partner, so a person posts it in SAGA
    assert cash_in["question"]["kind"] == "v3_approve"
    view = o.resume(cash_in["job"]["job_id"], {"decision": "approve", "edit": None})
    assert view["job"]["status"] == "needs_human" and "partner" in view["job"]["error"]
    again = _post(o).json()
    assert [j["created"] for j in again["jobs"]] == [False, False]


def test_a_statement_of_another_holder_emits_nothing(cat):
    o = _ops(cat)
    bad = _post(o, meta={**META, "holder_cui": "RO20000005"})
    assert bad.status_code == 422 and "not the tenant" in bad.json()["detail"]
    assert o.rt.jobs.jobs == {}
    assert _post(o, pdf=b"not a pdf").status_code == 422


def test_statement_lines_are_the_source_of_bank_movements(cat):
    o = _ops(cat)
    _post(o)
    out = o.http.get(
        f"/periods/{CUI}/{PERIOD}/diff", params={"tva": "tva_platitor"}, headers=o.op
    ).json()
    by_number = {b["sink"]["number"]: b["kind"] for b in out["diff"]["inbound"]}
    assert by_number["1"] == "expected"  # the SAGA bank entry matches the statement line
    assert out["diff"]["synthetic_delta"]["5121:credit"]["delta"] == "0.00"
    assert out["diff"]["synthetic_delta"]["5121:debit"]["delta"] == "-500.00"  # not in SAGA


# ----- WP-19: the bank mouths -----

PARTNER = "20000005"  # invented, valid check digit
BIND = {
    "partner": {"cui": PARTNER, "name": "CLIENT TEST SRL", "role": "customer"},
    "maps": {"factura_numar": "FX-101"},
}


def _bank_tenant(o, accounts=None):
    body = {
        "cui": CUI,
        "name": "FIRMA TEST SRL",
        "saga_firm_folder": "0001",
        "bank_accounts": {"RO49 AAAA 1B31 0075 9384 0000": "5121.01"}
        if accounts is None
        else accounts,
    }
    return o.http.put(f"/tenants/{CUI}", json=body, headers=o.op)


def _receipt(o):
    return [j for j in _post(o).json()["jobs"] if j["job"]["status"] != "already_in_sink"][0]


def test_a_bound_receipt_is_packaged_through_incasare_xml(cat):
    o = _ops(cat)
    assert _bank_tenant(o).status_code == 200
    job_id = _receipt(o)["job"]["job_id"]
    view = o.resume(job_id, {"decision": "edit", "edit": BIND})
    assert view["job"]["status"] == "packaged"
    assert view["job"]["module_id"] == "incasare_xml"
    pulled = o.http.get("/agent/pull", headers=o.ag).json()
    (item,) = [i for b in pulled["batches"] for i in b["items"]]
    assert item["filename"] == "I_20-09-2026.xml"
    xml = base64.b64decode(item["content_b64"]).decode()
    for tag in (
        "<Incasari>",
        "<Data>20.09.2026</Data>",
        "<Suma>500.00</Suma>",
        "<Cont>5121.01</Cont>",
        "<FacturaNumar>FX-101</FacturaNumar>",
        f"<CodFiscal>{PARTNER}</CodFiscal>",
    ):
        assert tag in xml
    assert "<FacturaID>" not in xml  # optional and unknown: not written
    # the edit added keys to maps; the statement's IBAN stayed
    assert o.rt.canonical(job_id).maps["iban"] == IBAN


@pytest.mark.parametrize(
    ("accounts", "edit", "match"),
    [
        ({}, BIND, "treasury account"),
        (None, {**BIND, "maps": {}}, "name the invoice"),
        (None, {"maps": {"factura_numar": "FX-101"}}, "partner"),
    ],
)
def test_a_receipt_missing_a_binding_is_posted_by_a_person(cat, accounts, edit, match):
    o = _ops(cat)
    _bank_tenant(o, accounts)
    job_id = _receipt(o)["job"]["job_id"]
    view = o.resume(job_id, {"decision": "edit", "edit": edit})
    assert view["job"]["status"] == "needs_human" and match in view["job"]["error"]
    assert o.http.get("/agent/pull", headers=o.ag).json()["batches"] == []


def test_bank_accounts_must_be_iban_to_a_class_5_account(cat):
    o = _ops(cat)
    assert _bank_tenant(o, {IBAN: "401"}).status_code == 422
    assert _bank_tenant(o, {"not an iban": "5121"}).status_code == 422
    assert _bank_tenant(o, {IBAN.lower(): "5121"}).status_code == 200
    assert o.rt.registry.tenant(CUI).treasury_account(IBAN) == "5121"


def test_two_receipts_of_one_day_go_in_two_runs(cat):
    o = _ops(cat)
    _bank_tenant(o)
    tables = [
        {
            "headers": ["Data", "Descriere", "Debit", "Credit"],
            "rows": [
                ["20.09.2026", "Incasare CLIENT TEST SRL FX-101", "", "500,00"],
                ["20.09.2026", "Incasare CLIENT TEST SRL FX-102", "", "210,00"],
            ],
        }
    ]
    out = _post(o, meta={**META, "closing": "5710.00"}, tables=tables).json()
    for n, j in enumerate(out["jobs"], 1):
        edit = {**BIND, "maps": {"factura_numar": f"FX-10{n}"}}
        assert (
            o.resume(j["job"]["job_id"], {"decision": "edit", "edit": edit})["job"]["status"]
            == "packaged"
        )
    pulled = o.http.get("/agent/pull", headers=o.ag).json()
    names = [i["filename"] for b in pulled["batches"] for i in b["items"]]
    assert names == ["I_20-09-2026.xml"]
    assert [h["reason"] for h in pulled["held"]] == ["I_20-09-2026.xml is already in this run"]


def _line_docs(tables):
    from poarta_contabila.extract.statement import statement_line_document
    from poarta_contabila.types import JobRecord, TenantRef

    meta = {**META, "closing": "5000.00", "opening": "5000.00"}
    st = parse_statement(tables, _meta(**meta), CUI)
    job = JobRecord(
        job_id="j",
        tenant=TenantRef(cui=CUI, saga_firm_folder="0001"),
        period=PERIOD,
        status="ingested",
    )
    return [
        statement_line_document(st, ln, job=job, bucket_key="k", source_hash="a" * 64)
        for ln in st.lines
    ]


def test_a_bank_reference_names_the_line_only_when_unique():
    head = ["Data", "Descriere", "Referinta", "Debit", "Credit"]
    unique = _line_docs(
        [
            {
                "headers": head,
                "rows": [
                    ["20.09.2026", "a", "OP-1", "", "10,00"],
                    ["20.09.2026", "b", "OP-2", "10,00", ""],
                ],
            }
        ]
    )
    assert [d.maps.get("referinta") for d in unique] == ["OP-1", "OP-2"]
    shared = _line_docs(
        [
            {
                "headers": head,
                "rows": [
                    ["20.09.2026", "a", "OP-1", "", "10,00"],
                    ["20.09.2026", "b", "OP-1", "10,00", ""],
                ],
            }
        ]
    )
    assert [d.maps.get("referinta") for d in shared] == [None, None]


# ----- WP-22: the proposal on the question -----


def test_an_unbound_payment_is_asked_with_the_invoice_it_settles(cat):
    from tests.test_runtime import NEW_INVOICE

    o = _ops(cat)
    _bank_tenant(o)
    invoice = o.ingest(NEW_INVOICE).json()  # AB 0099 of 10.09.2026, 807.81, supplier 20000005
    invoice_id = invoice["job"]["job_id"]
    tables = [
        {
            "headers": ["Data", "Descriere", "Debit", "Credit"],
            "rows": [["15.09.2026", "Plata ALT FURNIZOR SRL fact AB 0099", "807,81", ""]],
        }
    ]
    out = _post(o, meta={**META, "closing": "4192.19"}, tables=tables).json()
    (line,) = out["jobs"]
    question = line["question"]
    assert question["kind"] == "v3_approve"
    proposal = question["proposal"]
    assert proposal["edit"] == {
        "partner": {"cui": PARTNER, "name": "ALT FURNIZOR SRL", "role": "supplier"},
        "maps": {"factura_numar": "AB 0099", "factura_id": invoice_id},
    }
    # the person sends the proposal back as their edit: packaged through plata_xml
    view = o.resume(line["job"]["job_id"], {"decision": "edit", "edit": proposal["edit"]})
    assert view["job"]["status"] == "packaged" and view["job"]["module_id"] == "plata_xml"


def test_an_invoice_paid_in_two_lines_is_proposed_for_what_stays_open(cat):
    from tests.test_runtime import NEW_INVOICE

    o = _ops(cat)
    _bank_tenant(o)
    invoice_id = o.ingest(NEW_INVOICE).json()["job"]["job_id"]  # AB 0099, 807.81
    head = ["Data", "Descriere", "Debit", "Credit"]
    first = _post(
        o,
        meta={**META, "closing": "4500.00"},
        tables=[{"headers": head, "rows": [["12.09.2026", "Plata fact AB 0099", "500,00", ""]]}],
    ).json()["jobs"][0]
    proposal = first["question"]["proposal"]
    assert proposal["candidates"][0]["cover"] == "partial"
    assert proposal["candidates"][0]["open_after"] == "307.81"
    o.resume(first["job"]["job_id"], {"decision": "edit", "edit": proposal["edit"]})

    second = _post(
        o,
        meta={**META, "opening": "4500.00", "closing": "4192.19"},
        tables=[{"headers": head, "rows": [["16.09.2026", "Plata rest", "307,81", ""]]}],
    ).json()["jobs"][0]
    rest = second["question"]["proposal"]
    (c,) = rest["candidates"]
    assert c["cover"] == "full" and c["factura_id"] == invoice_id and c["hits"] == ["amount"]
    assert rest["edit"]["maps"] == {"factura_numar": "AB 0099", "factura_id": invoice_id}
