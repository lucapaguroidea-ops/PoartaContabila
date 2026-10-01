"""WP-08: ArticoleControls Layer 1 + PeriodDiff; hard failures block package and file."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import pytest

from poarta_contabila.catalog import load_catalog
from poarta_contabila.period_diff import (
    ExpectedJob,
    InMemoryPeriodStore,
    build_period_diff,
    can_file,
    expected_turnover,
    prefile_failures,
)
from poarta_contabila.sinks.exports import ExportEye, read_saga_balanta, read_saga_rj
from poarta_contabila.sinks.saga_eye import FakeSagaEye
from poarta_contabila.types import JobRecord, SinkDoc, TenantRef
from tests.test_recon_pre import _doc

SINK = Path(__file__).resolve().parents[1] / "fixtures" / "sink"
CUI, PERIOD = "1000009", "2026-09"
PAYER = {"tva": "tva_platitor"}


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _exp(number, day, gross, vat, *, doc_class="intrare", status="acked", key=None, n=1):
    doc = _doc(number, day, gross, doc_class=doc_class)
    doc = doc.model_copy(
        update={
            "job_id": f"job-{n}",
            "totals": doc.totals.model_copy(
                update={"vat": vat, "net": str(Decimal(gross) - Decimal(vat))}
            ),
        }
    )
    job = JobRecord(
        job_id=f"job-{n}",
        tenant=TenantRef(cui=CUI, saga_firm_folder="0001"),
        period=PERIOD,
        status=status,
        saga={"saga_doc_key": key} if key else {},
    )
    return ExpectedJob(job=job, doc=doc)


def _sd(number, day, gross, vat, doc_class="intrare"):
    return SinkDoc(
        saga_key=f"saga:{number}",
        doc_class=doc_class,
        number=number,
        date=day,
        partner_cui=None,
        gross=gross,
        net=str(Decimal(gross) - Decimal(vat)),
        vat=vat,
        validated=True,
    )


class CleanEye(FakeSagaEye):
    """Books that hold exactly the given documents (and their invoice postings)."""

    def __init__(self, docs, *, covered=True, extra_turnover=None, solduri=None, analytic=None):
        self.docs, self._covered = docs, covered
        self.extra = extra_turnover or {}
        self._solduri, self._analytic = solduri or {}, analytic or {}

    def covers(self, cui, period):
        return self._covered

    def documents(self, cui, period):
        return self.docs

    def turnover(self, cui, period):
        t = {
            a: {s: f"{v:.2f}" for s, v in sides.items()}
            for a, sides in expected_turnover(
                [
                    _exp(d.number, d.date, d.gross, d.vat, doc_class=d.doc_class).item()
                    for d in self.docs
                ]
            ).items()
        }
        t.update(self.extra)
        return t

    def solduri(self, cui, period):
        return self._solduri

    def analytic(self, cui, period, root):
        return {k: v for k, v in self._analytic.items() if k.startswith(root + ".")}


PURCHASE = ("1427", "2026-09-03", "1210.00", "210.00")
SALE = ("FX-101", "2026-09-10", "182.11", "31.61")


def _status(runs, cid):
    return next(r.status for r in runs if r.control_id == cid)


def test_clean_month_can_file(cat):
    expected = [_exp(*PURCHASE), _exp(*SALE, doc_class="iesire", n=2)]
    eye = CleanEye([_sd(*PURCHASE), _sd(*SALE, doc_class="iesire")])
    diff, runs = build_period_diff(cat, CUI, PERIOD, expected, eye, axes=PAYER)
    assert diff.hard_failures == 0 and not diff.material and can_file(diff)
    assert {b.kind for b in diff.inbound} == {"expected"}
    assert diff.synthetic_delta["401:credit"].delta == "0.00"
    assert _status(runs, "C0_synthetic_parity") == "PASS"
    assert _status(runs, "M1_1_payables_tie") == "INFO"  # no analytics shown yet
    assert _status(runs, "M1_8_4428_open") == "INFO"  # not a TVA-la-încasare tenant


def test_unexplained_inbound_makes_filing_impossible(cat):
    expected = [_exp(*PURCHASE)]
    eye = CleanEye([_sd(*PURCHASE), _sd("Z-9", "2026-09-20", "50.00", "8.68")])
    diff, runs = build_period_diff(cat, CUI, PERIOD, expected, eye, axes=PAYER)
    assert _status(runs, "C2_unexplained_empty") == "FAIL"
    assert [b.sink.number for b in diff.inbound if b.kind == "unexplained"] == ["Z-9"]
    assert diff.material and not can_file(diff)


def test_outbound_hole_blocks(cat):
    expected = [_exp(*PURCHASE), _exp(*SALE, doc_class="iesire", status="wait_validare", n=2)]
    eye = CleanEye([_sd(*PURCHASE)])
    diff, runs = build_period_diff(cat, CUI, PERIOD, expected, eye, axes=PAYER)
    assert diff.outbound_holes == ["job-2"] and _status(runs, "C1_outbound_complete") == "FAIL"
    assert not can_file(diff)


def test_a_payment_with_no_source_is_a_difference_not_a_plug(cat):
    eye = ExportEye(product="saga", lines=read_saga_rj(SINK / "saga_rj.xls"), cui=CUI)
    expected = [
        _exp(*PURCHASE, n=1),
        _exp("AB0058", "2026-09-10", "167.06", "16.56", n=2),
        _exp(*SALE, doc_class="iesire", n=3),
    ]
    diff, runs = build_period_diff(cat, CUI, PERIOD, expected, eye, axes=PAYER)
    kinds = {b.sink.number: b.kind for b in diff.inbound}
    assert kinds == {
        "1427": "expected",
        "AB0058": "expected",
        "FX-101": "expected",
        "1": "unexplained",
    }  # the bank payment: in the books, no source here
    assert diff.synthetic_delta["401:credit"].delta == "0.00"
    assert diff.synthetic_delta["401:debit"].delta == "1210.00"
    assert diff.synthetic_delta["5121:credit"].sink == "1210.00"
    assert _status(runs, "C0_synthetic_parity") == "FAIL" and not can_file(diff)


def test_no_books_for_the_month(cat):
    diff, runs = build_period_diff(cat, CUI, PERIOD, [_exp(*PURCHASE)], CleanEye([], covered=False))
    assert diff.material and diff.blockers[0].startswith("need_rj_export")
    assert _status(runs, "C2_unexplained_empty") == "FAIL"


def test_tva_regime_must_be_known(cat):
    diff, runs = build_period_diff(cat, CUI, PERIOD, [_exp(*PURCHASE)], CleanEye([_sd(*PURCHASE)]))
    assert _status(runs, "T_regime_4428") == "FAIL" and not can_file(diff)
    eye = CleanEye([_sd(*PURCHASE)], extra_turnover={"4428": {"debit": "5.00", "credit": "0.00"}})
    _, runs = build_period_diff(
        cat, CUI, PERIOD, [_exp(*PURCHASE)], eye, axes={"tva": "neplatitor"}
    )
    assert _status(runs, "T_regime_4428") == "FAIL"


def test_vat_on_collection_control_fails_closed_until_built(cat):
    _, runs = build_period_diff(
        cat, CUI, PERIOD, [], CleanEye([]), axes={"tva": "tva_platitor", "exig": "tva_la_incasare"}
    )
    assert _status(runs, "M1_8_4428_open") == "FAIL"  # blocking, not computed yet


def test_analytic_ties_on_the_saga_balance(cat):
    balance = read_saga_balanta(SINK / "saga_balanta.xlsx")
    eye = ExportEye(product="saga", lines=[], balance=balance, cui=CUI, periods=[PERIOD])
    diff, runs = build_period_diff(cat, CUI, PERIOD, [], eye, axes=PAYER)
    assert _status(runs, "M1_1_payables_tie") == "PASS"
    assert diff.analytic_delta["401"].delta == "0.00"
    off = CleanEye(
        [],
        solduri={"401": {"debit": "0.00", "credit": "100.00"}},
        analytic={"401.00001": {"debit": "0.00", "credit": "90.00"}},
    )
    _, runs = build_period_diff(cat, CUI, PERIOD, [], off, axes=PAYER)
    assert _status(runs, "M1_1_payables_tie") == "FAIL"


def test_advisory_failures_never_count_as_hard(cat):
    eye = CleanEye([], extra_turnover={"4423": {"debit": "1.00", "credit": "0.00"}})
    diff, runs = build_period_diff(cat, CUI, PERIOD, [], eye, axes={"tva": "neplatitor"})
    assert _status(runs, "T_regime_442x") == "FAIL"
    assert any("(advisory)" in b for b in diff.blockers)
    assert not any(b.startswith("T_regime_442x:") for b in diff.blockers)


def test_prefile_controls_refuse_a_package_unless_pre_said_absent(cat):
    assert prefile_failures(cat, pre_verdict="absent") == []
    failed = prefile_failures(cat, pre_verdict="already_posted")
    assert failed[0].startswith("P_prefile_duplicate") and "P_prefile_hard_failures" in failed[-1]
    assert prefile_failures(cat, pre_verdict=None)


def test_same_inputs_same_snapshot_and_runs_are_kept_once(cat):
    store = InMemoryPeriodStore()
    for _ in range(2):
        diff, runs = build_period_diff(
            cat, CUI, PERIOD, [_exp(*PURCHASE)], CleanEye([]), axes=PAYER
        )
        store.save(diff, runs)
    assert len(store.diffs) == 1 and len(store.runs) == len(runs)


def test_period_route_over_the_runtime(cat):
    from tests.test_runtime import NEW_INVOICE, Ops, _runtime

    o = Ops(_runtime(cat, periods=InMemoryPeriodStore()))
    o.tenant()
    o.upload_rj()
    job_id = o.ingest(NEW_INVOICE).json()["job"]["job_id"]
    out = o.http.get(
        f"/periods/{CUI}/{PERIOD}/diff", params={"tva": "tva_platitor"}, headers=o.op
    ).json()
    assert out["can_file"] is False
    assert job_id in out["diff"]["outbound_holes"]  # asked, not posted yet
    assert {c["control_id"] for c in out["controls"]} >= {
        "C0_synthetic_parity",
        "C2_unexplained_empty",
    }
    assert o.rt.periods.diffs


def test_postgres_period_store(cat):
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    import psycopg

    from poarta_contabila.jobs import PostgresJobStore
    from poarta_contabila.period_diff import PostgresPeriodStore

    PostgresJobStore(dsn, reset=True)
    diff, runs = build_period_diff(cat, CUI, PERIOD, [], CleanEye([]), axes=PAYER)
    store = PostgresPeriodStore(dsn)
    store.save(diff, runs)
    store.save(diff, runs)
    with psycopg.connect(dsn) as conn:
        (n,) = conn.execute("SELECT count(*) FROM domain.control_runs").fetchone()
        (m,) = conn.execute("SELECT count(*) FROM domain.close_snapshots").fetchone()
    assert (n, m) == (len(runs), 1)
