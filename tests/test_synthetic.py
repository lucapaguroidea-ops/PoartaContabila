"""synthetic firms, documents and books — invented, seeded, read by the real readers."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.close import close_kind
from poarta_contabila.codit import CoditInput, write_codit
from poarta_contabila.extract.statement import StatementMeta, parse_statement
from poarta_contabila.extract.ubl import parse_ubl, read_spv_zip, to_canonical
from poarta_contabila.filings import due_filings
from poarta_contabila.sinks.exports import (
    ExportEye,
    read_firm_cui,
    read_nextup_balanta,
    read_nextup_rj,
    read_saga_balanta,
    read_saga_rj,
)
from poarta_contabila.sinks.saga_eye import read_saga_tva_journal
from poarta_contabila.sinks.spv_register import read_spv_register
from poarta_contabila.synthetic import FIRMS, firm
from poarta_contabila.synthetic.docs import Gen, money
from poarta_contabila.synthetic.months import DEFECTS, month, previous
from poarta_contabila.triage import DecontSplitResume, Pack, check_split
from poarta_contabila.types import JobRecord, SourceRef, TenantRef, cui_is_valid

PERIOD = "2026-05"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _file(tmp_path: Path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _canonical(f, data: bytes):
    inv = parse_ubl(read_spv_zip(data).invoice)
    job = JobRecord(
        job_id="j",
        tenant=TenantRef(cui=f.cui, saga_firm_folder=f.folder),
        period=PERIOD,
        status="ingested",
    )
    src = SourceRef(
        kind="ubl_spv", bucket_key="k", content_type="application/zip", source_hash="0" * 64
    )
    return to_canonical(inv, job=job, source=src)


def _eye(tmp_path, m) -> ExportEye:
    name, data, _ = m.exports()["rj"]
    lines = read_saga_rj(_file(tmp_path, name, data))
    name, data, _ = m.exports()["balanta"]
    rows = read_saga_balanta(_file(tmp_path, name, data))
    return ExportEye(
        product="saga", lines=lines, balance=rows, cui=m.firm.cui, periods=m.book.periods()
    )


def test_firms_are_invented_and_valid(cat):
    cuis = set()
    for f in [*FIRMS.values(), firm("platitor", book_of_record="nextup")]:
        assert cui_is_valid(f.cui) and f.cui != "1000009" and f.cui not in cuis
        cuis.add(f.cui)
        assert f.iban.startswith("RO") and "AAAA" in f.iban
        assert int("".join(str(int(c, 36)) for c in f.iban[4:] + f.iban[:4])) % 97 == 1
        for p in (*f.suppliers, *f.customers):
            assert cui_is_valid(p.cui) and p.cui not in ("1000009", "20000005")
        for p in f.foreign:
            assert p.cui is None and p.country != "RO"
        assert f.tenant()["data_class"] == "synthetic"


def test_the_five_profiles_differ_where_the_paths_do(cat):
    kinds, due = {}, set()
    for key, f in FIRMS.items():
        axes = write_codit(cat, f.cui, PERIOD, CoditInput.model_validate(f.codit())).derive()
        kinds[key] = close_kind(cat, axes)
        due |= {r["filing_id"] for r in due_filings(cat, axes)}
    assert kinds["incasare"] == "close_tva_incasare"
    assert {kinds[k] for k in ("platitor", "neplatitor", "abroad", "bonuri")} == {"close_standard"}
    assert due == set(cat.filings)  # between them every filing falls due
    assert FIRMS["neplatitor"].axes["tva"] == "tva_neplatitor"
    assert FIRMS["abroad"].axes["cross_border"] == "mixed"


def test_spv_documents_read_as_the_side_and_sign_they_say():
    f = FIRMS["platitor"]
    g = Gen(f, PERIOD, seed=4)
    buy, sell = g.purchase("p", rates=(21, 11), items=3), g.sale("s")
    for inv, doc_class in (
        (buy, "intrare"),
        (sell, "iesire"),
        (g.credit_note("pc", buy, share=50), "storn_intrare"),
        (g.credit_note("sc", sell), "storn_iesire"),
    ):
        zf = read_spv_zip(inv.spv_zip(f))
        assert zf.signature_name == f"semnatura_{inv.spv_id}.xml"
        doc = _canonical(f, inv.spv_zip(f))
        assert doc.doc_class == doc_class and doc.number == inv.number
        assert Decimal(doc.totals.gross) == Decimal(money(inv.signed))
        assert doc.partner.cui == inv.partner.cui
        if inv.is_credit:
            assert doc.is_storno and doc.storno_of == inv.credit_of
    # a neplătitor supplier charges no VAT
    assert g.purchase("n", partner="s4").vat == 0


def test_documents_from_abroad_receipts_payroll_and_statements():
    f = FIRMS["abroad"]
    g = Gen(f, PERIOD, seed=2)
    x = g.foreign_purchase("x", partner="x2", currency="EUR")
    inv = parse_ubl(x.xml(f))
    assert inv.supplier.cui is None and inv.supplier.country == "ES" and inv.currency == "EUR"
    assert x.pdf(f).startswith(b"%PDF")
    with_cui, without = g.bon("b1", our_cui=True), g.bon("b2", our_cui=False)
    assert f"RO{f.cui}".encode() in with_cui.pdf() and f.cui.encode() not in without.pdf()
    assert g.payroll("pay").pdf(f).startswith(b"%PDF")

    p, s = g.purchase("p"), g.sale("s")
    stmt = g.statement("e", [g.payment(p), g.receipt(s, amount=s.gross // 2), g.fee()])
    parsed = parse_statement(stmt.tables(), StatementMeta(**stmt.meta()), f.cui)
    assert sorted(ln.side for ln in parsed.lines) == ["credit", "debit", "debit"]
    assert stmt.pdf().startswith(b"%PDF") and stmt.upload(tables=False).keys() == {
        "meta",
        "pdf_b64",
    }


def test_an_expense_report_splits_into_the_catalogs_children(cat):
    m = month(FIRMS["bonuri"], PERIOD, seed=1)
    report = m.docs["decont"]
    answer = DecontSplitResume.model_validate(report.split_answer(m.firm))
    container = Pack(
        tenant_cui=m.firm.cui,
        saga_firm_folder=m.firm.folder,
        period=PERIOD,
        source_hash=hashlib.sha256(report.pdf(m.firm)).hexdigest(),
        source_doc_id="decont_cheltuieli",
        kinds=["pdf"],
        our_role="inbound",
        identity_ok=True,
    )
    assert check_split(cat, container, answer) is None
    ids = [p.source_doc_id for p in answer.parts]
    assert ids == ["decont_part_evidence", "decont_part_evidence", "ro_efactura_ubl", "workings"]
    assert [p.bon_our_cui_on_doc for p in answer.parts[:2]] == [True, False]
    # the invoice part is named by the hash of the SPV zip a person would upload later
    assert (
        answer.parts[2].part_hash == hashlib.sha256(m.docs["dec_inv"].spv_zip(m.firm)).hexdigest()
    )


@pytest.mark.parametrize("key", sorted(FIRMS))
def test_a_clean_months_books_read_and_hold_its_documents(tmp_path, key):
    m = month(FIRMS[key], PERIOD, seed=1)
    exports = m.exports()
    name, data, _ = exports["rj"]
    assert read_firm_cui(_file(tmp_path, name, data)) == m.firm.cui
    for kind in ("jurnal_cumparari", "jurnal_vanzari"):
        name, data, _ = exports[kind]
        read_saga_tva_journal(_file(tmp_path, name, data), kind.split("_")[1])
    name, data, _ = exports["spv_register"]
    assert read_spv_register(_file(tmp_path, name, data))
    eye = _eye(tmp_path, m)
    books = {(d.number, d.doc_class): d.gross for d in eye.documents(m.firm.cui, PERIOD)}
    for inv in m.invoices():
        if inv.foreign or inv.issued[:7] != PERIOD:
            continue
        assert books[(inv.number.replace(" ", ""), inv.doc_class)] == money(inv.signed)
    # the analytics under 401 / 4111 add up to their synthetic rows (M1 ties)
    sold = eye.solduri(m.firm.cui, PERIOD)
    for root in ("401", "4111"):
        kids = eye.analytic(m.firm.cui, PERIOD, root)
        net = sum(Decimal(v["debit"]) - Decimal(v["credit"]) for v in kids.values())
        assert net == Decimal(sold[root]["debit"]) - Decimal(sold[root]["credit"])
    # the statement opens where the books' bank account stood and lists every bank line
    stmt = m.docs["extras"]
    assert len(stmt.lines) == len(m.bank)


def test_nextup_books_read(tmp_path):
    m = month(firm("bonuri", book_of_record="nextup"), PERIOD, seed=1)
    exports = m.exports()
    assert set(exports) == {"rj", "balanta", "spv_register"}
    lines = read_nextup_rj(_file(tmp_path, "rj.xlsx", exports["rj"][1]))
    rows = read_nextup_balanta(_file(tmp_path, "b.xlsx", exports["balanta"][1]))
    eye = ExportEye(product="nextup", lines=lines, balance=rows, cui=m.firm.cui)
    docs = eye.documents(m.firm.cui, PERIOD)
    assert any(d.doc_class == "intrare" and d.partner_cui for d in docs)


def _doc(tmp_path, m, number):
    for d in _eye(tmp_path, m).documents(m.firm.cui, m.period):
        if d.number == number.replace(" ", ""):
            return d
    return None


def test_each_named_defect_does_what_it_says(tmp_path):
    f = FIRMS["platitor"]
    clean = month(f, PERIOD, seed=1)
    p2, s1, s2 = clean.docs["p2"], clean.docs["s1"], clean.docs["s2"]
    assert set(DEFECTS) == {
        "missing_from_books",
        "in_books_no_document",
        "amount_differs",
        "vat_differs",
        "posted_another_way",
        "duplicate_upload",
        "late_prior_month",
        "storno_of_acked",
        "bank_line_two_invoices",
        "partial_payment",
        "posted_on_other_accounts",
        "payables_skew",
        "receivables_skew",
        "trade_accounts",
        "trade_accounts_skew",
        "vat_on_4428",
        "vat_on_4423",
    }

    m = month(f, PERIOD, seed=1, defect="missing_from_books")
    assert _doc(tmp_path, m, p2.number) is None and "p2" in [u.ref for u in m.uploads]

    m = month(f, PERIOD, seed=1, defect="in_books_no_document")
    assert _doc(tmp_path, m, m.docs["hidden"].number) is not None
    assert "hidden" not in [u.ref for u in m.uploads]

    m = month(f, PERIOD, seed=1, defect="amount_differs")
    assert Decimal(_doc(tmp_path, m, s2.number).gross) == Decimal(money(s2.gross)) + 1

    m = month(f, PERIOD, seed=1, defect="vat_differs")
    assert Decimal(_doc(tmp_path, m, p2.number).vat) == Decimal(money(p2.vat)) + 1

    m = month(f, PERIOD, seed=1, defect="posted_another_way")
    d = _doc(tmp_path, m, p2.number)
    assert d.gross == money(p2.gross) and d.vat == "0.00"

    m = month(f, PERIOD, seed=1, defect="duplicate_upload")
    assert [u.ref for u in m.uploads].count("p2") == 2

    m = month(f, PERIOD, seed=1, defect="late_prior_month")
    late = m.docs["late"]
    assert late.issued[:7] == previous(PERIOD) and m.book.periods() == [previous(PERIOD), PERIOD]
    assert "late" in [u.ref for u in m.uploads]

    m = month(f, PERIOD, seed=1, defect="storno_of_acked")
    storno = m.docs["s1_storno"]
    assert storno.credit_of == s1.number and Decimal(_doc(tmp_path, m, storno.number).gross) < 0

    m = month(f, PERIOD, seed=1, defect="bank_line_two_invoices")
    paid = [ln for ln in m.bank if ln.side == "debit" and ln.kind == "invoice"][0]
    assert [r for r, _ in paid.settles] == ["p1", "p1b"]
    assert len([e for e in m.book.entries if e.number == paid.reference]) == 2

    m = month(f, PERIOD, seed=1, defect="partial_payment")
    got = [ln for ln in m.bank if ln.side == "credit"][0]
    assert got.amount == s1.gross // 2


def test_the_same_seed_gives_the_same_bytes_and_another_seed_does_not():
    def digest(seed):
        m = month(FIRMS["bonuri"], PERIOD, seed=seed, defect="storno_of_acked")
        h = hashlib.sha256()
        for u in m.uploads:
            if u.route == "ingest":
                h.update(u.doc.spv_zip(m.firm))
            elif u.route == "extras":
                h.update(u.doc.pdf() + repr(u.doc.tables()).encode())
            else:
                h.update(u.doc.pdf(m.firm) + repr(u.doc.split_answer(m.firm)).encode())
        for _, data, _ in m.exports().values():
            h.update(data)
        return h.hexdigest()

    assert digest(7) == digest(7)
    assert digest(7) != digest(8)


def test_the_account_level_defects(tmp_path):
    f = FIRMS["platitor"]
    m = month(f, PERIOD, seed=1, defect="posted_on_other_accounts")
    p2 = [e for e in m.book.entries if e.ref == "p2"]
    assert {e.credit.split(".")[0] for e in p2} == {"408"} and not any(
        e.debit in ("4426", "4428") for e in p2
    )
    for defect, root in (("payables_skew", "401"), ("receivables_skew", "4111")):
        eye = _eye(tmp_path, month(f, PERIOD, seed=1, defect=defect))
        kids = eye.analytic(f.cui, PERIOD, root)
        net = sum(Decimal(v["debit"]) - Decimal(v["credit"]) for v in kids.values())
        sold = eye.solduri(f.cui, PERIOD)[root]
        assert net != Decimal(sold["debit"]) - Decimal(sold["credit"])
    eye = _eye(tmp_path, month(f, PERIOD, seed=1, defect="trade_accounts"))
    assert eye.analytic(f.cui, PERIOD, "408") and eye.analytic(f.cui, PERIOD, "418")
    n = month(FIRMS["neplatitor"], PERIOD, seed=1, defect="vat_on_4423")
    assert any(e.debit == "4423" for e in n.book.entries if e.ref == "p1")
    a = month(FIRMS["abroad"], PERIOD, seed=1)
    ids = [p["source_doc_id"] for p in a.docs["decont_abroad"].split_answer(a.firm)["parts"]]
    assert ids == ["decont_part_evidence", "ro_efactura_pdf", "workings"]


def test_realistic_months_are_drawn_sized_and_repeatable():
    """two months of 30–60 documents each, the same bytes for the same seed."""
    from poarta_contabila.synthetic.months import realistic

    for key in ("abroad", "neplatitor", "bonuri"):
        m = realistic(FIRMS[key], ["2026-06", "2026-07"], seed=73)
        assert m.book.periods() == ["2026-06", "2026-07"]
        for yy in ("2606", "2607"):
            uploads = [u for u in m.uploads if u.ref.startswith(yy)]
            lines = m.docs[f"{yy}-extras"].lines
            assert 30 <= len(uploads) - 1 + len(lines) <= 60
        again = realistic(FIRMS[key], ["2026-06", "2026-07"], seed=73)
        assert [u.ref for u in again.uploads] == [u.ref for u in m.uploads]
        assert again.book.saga_rj() == m.book.saga_rj()
