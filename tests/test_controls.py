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


# ----- WP-46: a statement line's counterpart (owner, 2026-10-02) -----

from poarta_contabila.period_diff import bank_counterparts  # noqa: E402
from poarta_contabila.sinks.exports import SinkLine  # noqa: E402


def _ln(row, day, journal, doc, debit, credit, amount):
    return SinkLine(
        product="saga",
        row=row,
        seq=str(row),
        date=day,
        journal=journal,
        doc_number=doc,
        explanation="",
        debit=debit,
        credit=credit,
        amount=amount,
    )


INVOICES = [  # 1427 bought for 1 210,00; FX-101 sold for 182,11
    _ln(1, "2026-09-03", "Intrari", "1427", "628", "401.00010", "1000.00"),
    _ln(2, "2026-09-03", "Intrari", "1427", "4426", "401.00010", "210.00"),
    _ln(3, "2026-09-10", "Iesiri", "FX-101", "4111.00001", "704", "150.50"),
    _ln(4, "2026-09-10", "Iesiri", "FX-101", "4111.00001", "4427", "31.61"),
]
PAYMENT = _ln(5, "2026-09-15", "Banca", "OP-77", "401.00010", "5121.01", "1210.00")
RECEIPT = _ln(6, "2026-09-20", "Banca", "IN-1", "5121.01", "4111.00001", "182.11")


def _books(*lines):
    return ExportEye(product="saga", lines=[*INVOICES, *lines], cui=CUI)


def _line(doc_class, day, gross, *, role, n, status="already_in_sink"):
    e = _exp(f"EXT-{n}", day, gross, "0.00", doc_class=doc_class, status=status, n=n)
    partner = e.doc.partner.model_copy(update={"role": role})
    return ExpectedJob(job=e.job, doc=e.doc.model_copy(update={"partner": partner}))


def _month(*bank):
    return [_exp(*PURCHASE, n=1), _exp(*SALE, doc_class="iesire", n=2), *bank]


@pytest.mark.parametrize("role", ["supplier", "unknown"])
def test_a_payment_and_a_receipt_tie_by_binding_or_by_their_posting(cat, role):
    receipt_role = "customer" if role == "supplier" else "unknown"
    expected = _month(
        _line("plata", "2026-09-15", "1210.00", role=role, n=3),
        _line("incasare", "2026-09-20", "182.11", role=receipt_role, n=4),
    )
    diff, runs = build_period_diff(cat, CUI, PERIOD, expected, _books(PAYMENT, RECEIPT), axes=PAYER)
    assert diff.synthetic_delta["401:debit"].model_dump() == {
        "expected": "1210.00",
        "sink": "1210.00",
        "delta": "0.00",
    }
    assert diff.synthetic_delta["4111:credit"].delta == "0.00"
    assert diff.synthetic_delta["5121:debit"].delta == "0.00"
    assert _status(runs, "C0_synthetic_parity") == "PASS"
    assert can_file(diff) and diff.blockers == []


def test_a_bound_line_is_checked_against_where_the_books_put_it(cat):
    """Bound to a supplier, posted against a customer: both accounts show the difference."""
    wrong = _ln(5, "2026-09-15", "Banca", "OP-77", "4111.00001", "5121.01", "1210.00")
    expected = _month(_line("plata", "2026-09-15", "1210.00", role="supplier", n=3))
    diff, runs = build_period_diff(cat, CUI, PERIOD, expected, _books(wrong), axes=PAYER)
    assert diff.synthetic_delta["401:debit"].delta == "-1210.00"
    assert diff.synthetic_delta["4111:debit"].delta == "1210.00"
    assert _status(runs, "C0_synthetic_parity") == "FAIL" and not can_file(diff)


@pytest.mark.parametrize(
    "posting",
    [
        # never bound, posted against a customer: not the payment account, not taken
        [_ln(5, "2026-09-15", "Banca", "OP-77", "4111.00001", "5121.01", "1210.00")],
        # split over two lines: only one line of the whole amount is taken
        [
            _ln(5, "2026-09-15", "Banca", "OP-77", "401.00010", "5121.01", "1000.00"),
            _ln(6, "2026-09-15", "Banca", "OP-77", "401.00010", "5121.01", "210.00"),
        ],
    ],
)
def test_an_unbound_line_takes_only_one_posting_of_its_account_and_amount(cat, posting):
    expected = _month(_line("plata", "2026-09-15", "1210.00", role="unknown", n=3))
    diff, runs = build_period_diff(cat, CUI, PERIOD, expected, _books(*posting), axes=PAYER)
    assert {b.kind for b in diff.inbound} == {"expected"}  # the bank document is matched
    assert _status(runs, "C0_synthetic_parity") == "FAIL" and not can_file(diff)


def test_a_line_not_in_the_books_implies_nothing_from_them(cat):
    line = _line("plata", "2026-09-15", "1210.00", role="unknown", n=3)
    assert bank_counterparts([line], {}, [PAYMENT]) == []
    bound = _line("plata", "2026-09-15", "1210.00", role="supplier", n=3, status="packaged")
    assert bank_counterparts([bound], {}, []) == [("401", "debit", Decimal("1210.00"))]


def test_the_fixture_payment_with_its_statement_line_ties_401(cat):
    """The September books (fixtures/sink/saga_rj.xls): its payment, once a statement line
    here matches it, no longer leaves 401 debit as a difference."""
    eye = ExportEye(product="saga", lines=read_saga_rj(SINK / "saga_rj.xls"), cui=CUI)
    expected = [
        _exp(*PURCHASE, n=1),
        _exp("AB0058", "2026-09-10", "167.06", "16.56", n=2),
        _exp(*SALE, doc_class="iesire", n=3),
        _line("plata", "2026-09-15", "1210.00", role="unknown", n=4),
    ]
    diff, runs = build_period_diff(cat, CUI, PERIOD, expected, eye, axes=PAYER)
    assert diff.synthetic_delta["401:debit"].delta == "0.00"
    assert diff.synthetic_delta["5121:credit"].delta == "0.00"
    assert _status(runs, "C0_synthetic_parity") == "PASS"


# ----- WP-73 G6: C0's implied VAT follows the period's CO.DiT -----


def _items(*specs):
    return [_exp(*s, n=i, doc_class=dc).item() for i, (dc, *s) in enumerate(specs, start=1)]


def test_implied_vat_follows_the_tva_regime():
    items = _items(
        ("intrare", "A1", "2026-09-03", "121.00", "21.00"),
        ("iesire", "S1", "2026-09-04", "242.00", "42.00"),
    )
    payer = expected_turnover(items, {"tva": "tva_platitor", "exig": "tva_exig_livrare"})
    assert payer["4426"]["debit"] == Decimal("21.00") and payer["4427"]["credit"] == Decimal(
        "42.00"
    )
    incasare = expected_turnover(items, {"tva": "tva_platitor", "exig": "tva_la_incasare"})
    assert "4426" not in incasare and "4427" not in incasare
    assert incasare["4428"] == {"debit": Decimal("21.00"), "credit": Decimal("42.00")}
    nonpayer = expected_turnover(items, {"tva": "tva_neplatitor"})
    assert "4426" not in nonpayer and nonpayer["401"]["credit"] == Decimal("121.00")
    unknown = expected_turnover(items, {})  # no CO.DiT: the payer's reading, as before
    assert unknown == expected_turnover(items)
    assert unknown["4426"]["debit"] == Decimal("21.00")


def test_reverse_charge_for_a_payer_is_implied_on_its_invoice_from_abroad():
    items = _items(("intrare", "DE-1", "2026-09-05", "100.00", "0.00"))
    rc = expected_turnover(items, {"tva": "tva_platitor"}, "21", {"job-1"})
    assert rc["4426"]["debit"] == Decimal("21.00") and rc["4427"]["credit"] == Decimal("21.00")
    plain = expected_turnover(items, {"tva": "tva_platitor"}, "21")  # not bound abroad
    assert plain["4426"]["debit"] == Decimal("0") and "4427" not in plain


def test_tva_la_incasare_moves_the_paid_share(cat):
    from poarta_contabila.period_diff import vat_exigible
    from poarta_contabila.types import PartnerRef

    inv = _exp("A1", "2026-08-20", "121.00", "21.00")
    inv = ExpectedJob(
        job=inv.job,
        doc=inv.doc.model_copy(
            update={"partner": PartnerRef(cui="20000005", name="FURNIZOR", role="supplier")}
        ),
    )
    pay = _exp("EXT-1", "2026-09-10", "60.50", "0.00", doc_class="plata", n=2)
    pay = ExpectedJob(
        job=pay.job,
        doc=pay.doc.model_copy(
            update={
                "partner": PartnerRef(cui="20000005", name="FURNIZOR", role="supplier"),
                "maps": {"factura_numar": "A 1"},
                "totals": pay.doc.totals.model_copy(update={"net": "60.50", "vat": "0.00"}),
            }
        ),
    )
    axes = {"tva": "tva_platitor", "exig": "tva_la_incasare"}
    got = vat_exigible([pay], [inv], axes)  # the invoice is of the month before
    assert got == [("4426", "debit", Decimal("10.50")), ("4428", "credit", Decimal("10.50"))]
    assert vat_exigible([pay], [inv], {"tva": "tva_platitor"}) == []


def test_a_job_minted_without_a_thread_is_an_outbound_hole(cat):
    """WP-73 G2: the close counts every Job of the month, even one never started."""
    exp = [_exp(*PURCHASE)]
    diff, runs = build_period_diff(
        cat, CUI, PERIOD, exp, CleanEye([_sd(*PURCHASE)]), axes=PAYER, stalled=["job-x"]
    )
    assert diff.outbound_holes == ["job-x"]
    assert {r.control_id: r.status for r in runs}["C1_outbound_complete"] == "FAIL"
