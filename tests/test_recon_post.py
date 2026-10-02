"""WP-27: POST recon — how SAGA posted an acked document, and the person's answer to a mismatch."""

from __future__ import annotations

import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.recon.post import how_check
from poarta_contabila.sinks.exports import ExportEye, SinkLine
from poarta_contabila.sinks.saga_xml import fixture_documents

CUI, PERIOD = "1000009", "2026-09"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _ln(row, debit, credit, amount, number="A-77", date="2026-09-20", journal="Intrari"):
    return SinkLine(
        product="saga",
        row=row,
        seq=None,
        date=date,
        journal=journal,
        doc_number=number,
        explanation="",
        debit=debit,
        credit=credit,
        amount=amount,
    )


def _eye(lines, periods=(PERIOD,)):
    return ExportEye(product="saga", lines=lines, cui=CUI, periods=list(periods))


def _check(cat, eye, *, articol="ro_efactura_inbound", **reconcile):
    doc = fixture_documents()["intrare"]  # A-77 of 2026-09-20, purchase, 242.00
    row = dict(cat.articol(articol))
    if reconcile:
        row["reconcile"] = {**(row.get("reconcile") or {}), **reconcile}
    return how_check(doc, row, cat.recon_profiles["post_doc_how"], eye, CUI)


POSTED = [_ln(1, "628", "401.00001", "200.00"), _ln(2, "4426", "401.00001", "42.00")]


def test_a_posting_on_the_expected_accounts_is_how_ok(cat):
    res = _check(cat, _eye(POSTED))
    assert res.verdict == "how_ok" and res.used == ["401", "4426", "628"]
    assert res.expected == ["401", "4426"] and res.rows == [1, 2]


def test_a_posting_paid_straight_from_cash_is_a_mismatch(cat):
    res = _check(cat, _eye([_ln(1, "628", "5311", "242.00")]))
    assert res.verdict == "how_mismatch" and "expected any of ['401', '4426']" in res.reason


def test_require_all_needs_every_expected_account(cat):
    only_401 = [_ln(1, "628", "401.00001", "242.00")]
    assert _check(cat, _eye(only_401)).verdict == "how_ok"  # catalog: require_all false
    res = _check(cat, _eye(only_401), require_all_accounts=True)
    assert res.verdict == "how_mismatch" and "all of" in res.reason


def test_no_posting_in_a_covered_month_is_a_mismatch(cat):
    other = [_ln(1, "628", "401.00002", "10.00", number="B-1")]
    res = _check(cat, _eye(other))
    assert res.verdict == "how_mismatch" and "shows no posting of A-77" in res.reason


def test_digits_alone_name_no_posting(cat):
    res = _check(cat, _eye([_ln(1, "628", "401.00001", "242.00", number="77")]))
    assert res.verdict == "how_mismatch" and res.rows == []


@pytest.mark.parametrize(
    "eye", [None, _eye(POSTED, periods=("2026-08",)), object()], ids=["none", "uncovered", "pack"]
)
def test_without_the_journal_for_the_month_post_asks_for_it(cat, eye):
    res = _check(cat, eye)
    assert res.verdict == "need_rj_export" and res.missing == [PERIOD]


def test_the_snapshot_follows_the_posting_not_the_rest_of_the_journal(cat):
    a = _check(cat, _eye(POSTED))
    b = _check(cat, _eye([*POSTED, _ln(9, "628", "401.00003", "1.00", number="Z-9")]))
    c = _check(cat, _eye([POSTED[0]]))
    assert a.snapshot_id == b.snapshot_id != c.snapshot_id


def test_no_expected_accounts_asks_a_person(cat):
    res = _check(cat, _eye(POSTED), expect_accounts=[])
    assert res.verdict == "how_ok"  # empty on the articol: the profile's fallback applies
    res = how_check(
        fixture_documents()["intrare"],
        {"reconcile": {"expect_accounts": []}},
        {**cat.recon_profiles["post_doc_how"], "fallback_accounts": []},
        _eye(POSTED),
        CUI,
    )
    assert res.verdict == "how_mismatch" and "WP-D3" in res.reason


# ----- on the reconcile_sink thread, and what the close sees -----


def _acked(cat):
    from tests.test_runtime import NEW_INVOICE, Ops, _runtime

    o = Ops(_runtime(cat))
    o.tenant()
    o.upload_rj()  # covers 2026-09 but holds no posting of AB 0099
    job_id = o.ingest(NEW_INVOICE).json()["job"]["job_id"]
    rt = o.rt
    w = rt._thread_job(rt.jobs.get(job_id))
    rt.post_waiting = lambda cui, period: [w]  # as if SAGA showed it validated
    return o, job_id


def _recon(o, body=None):
    if body is None:
        return o.http.post(f"/recon/{CUI}/{PERIOD}", headers=o.op).json()
    return o.http.post(f"/recon/{CUI}/{PERIOD}/resume", json=body, headers=o.op).json()


def test_a_mismatch_is_asked_and_a_storno_request_stays_open_for_the_close(cat):
    o, job_id = _acked(cat)
    view = _recon(o)
    q = view["question"]
    assert q["kind"] == "recon_how_mismatch" and q["job_id"] == job_id
    assert "no posting of AB 0099" in q["reason"] and q["expected"] == ["401", "4426"]
    assert view["post_open"] == [job_id]
    bad = _recon(o, {"ack_mismatch": False, "open_storno": False})
    assert "choose ack_mismatch" in bad["question"]["error"]
    view = _recon(o, {"ack_mismatch": False, "open_storno": True})
    assert view["question"] is None
    assert view["settled"][-1] == {
        "job_id": job_id,
        "verdict": "storno_requested",
        "by": "person",
        "stage": "post",
    }
    assert _recon(o)["question"] is None  # not asked again for the same posting
    assert o.rt.post_open(CUI, PERIOD) == [job_id]  # but open until SAGA's posting changes
    close = o.http.post(f"/close/{CUI}/{PERIOD}", params={"tva": "tva_platitor"}, headers=o.op)
    assert any("reconcile_sink" in b for b in close.json()["question"]["blockers"])


def test_an_acknowledged_posting_is_settled(cat):
    o, job_id = _acked(cat)
    _recon(o)
    view = _recon(o, {"ack_mismatch": True, "open_storno": False})
    assert view["settled"][-1]["verdict"] == "how_mismatch_acknowledged"
    assert view["post_open"] == []
