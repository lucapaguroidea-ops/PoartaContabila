"""WP-09: explained rules — versioned, person-written, and the only way to explain."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from poarta_contabila.catalog import load_catalog
from poarta_contabila.period_diff import build_period_diff, can_file
from poarta_contabila.rules import (
    ControlDispositionResume,
    ExplainedRuleResume,
    InMemoryRuleStore,
    RuleBody,
    check_control_disposition,
    check_explained_rule,
)
from poarta_contabila.sinks.exports import ExportEye, read_saga_rj
from tests.test_controls import CUI, PAYER, PERIOD, PURCHASE, SALE, CleanEye, _exp, _sd, _status

SINK = Path(__file__).resolve().parents[1] / "fixtures" / "sink"
FEES = {
    "description": "Comisioane bancare lunare",
    "scope": "document",
    "document": {"doc_class": "intrare", "number_prefix": "COM", "gross_max": "100.00"},
}
PAYMENTS = {
    "description": "Plăți furnizori din extras (până la WP-13)",
    "scope": "line",
    "line": {"debit": "401*", "credit": "5121*", "journal": "Banca"},
}


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _store(*bodies):
    store = InMemoryRuleStore()
    for rule_id, body in bodies:
        store.add(CUI, rule_id, RuleBody.model_validate(body))
    return store


# ----- the rule itself -----


def test_a_rule_names_exactly_one_matcher():
    with pytest.raises(ValidationError, match="exactly the matcher"):
        RuleBody.model_validate({**FEES, "scope": "line"})
    with pytest.raises(ValidationError, match="narrow at least one"):
        RuleBody.model_validate({"description": "everything", "scope": "document", "document": {}})


def test_rules_are_versioned_and_never_rewritten():
    store = InMemoryRuleStore()
    v1 = store.add(CUI, "comisioane", RuleBody.model_validate(FEES))
    same = store.add(CUI, "comisioane", RuleBody.model_validate(FEES))
    v2 = store.add(
        CUI, "comisioane", RuleBody.model_validate({**FEES, "description": "Comisioane"})
    )
    assert (v1.version, same.version, v2.version) == (1, 1, 2)
    assert len(store.rows) == 2 and store.active(CUI)[0].version == 2


# ----- in the period diff -----


def test_document_rule_moves_a_row_to_explained_with_its_rule_id(cat):
    fee = ("COM-0925", "2026-09-30", "15.00", "0.00")
    eye = CleanEye([_sd(*PURCHASE), _sd(*fee)])
    without, runs = build_period_diff(cat, CUI, PERIOD, [_exp(*PURCHASE)], eye, axes=PAYER)
    assert _status(runs, "C2_unexplained_empty") == "FAIL"  # no rule, no hiding
    store = _store(("comisioane", FEES))
    diff, runs = build_period_diff(
        cat, CUI, PERIOD, [_exp(*PURCHASE)], eye, axes=PAYER, rules=store.active(CUI)
    )
    row = next(b for b in diff.inbound if b.sink.number == "COM-0925")
    assert (row.kind, row.rule_id) == ("explained_sink_only", "comisioane")
    assert _status(runs, "C2_unexplained_empty") == "PASS"
    assert _status(runs, "C0_synthetic_parity") == "PASS"  # explained postings counted
    assert can_file(diff) and diff.snapshot_id != without.snapshot_id


def test_rule_outside_its_months_or_bounds_does_not_explain(cat):
    big = ("COM-0926", "2026-09-30", "150.00", "0.00")  # over gross_max
    late = RuleBody.model_validate({**FEES, "valid_from": "2026-10"})
    store = InMemoryRuleStore()
    store.add(CUI, "comisioane", late)
    eye = CleanEye([_sd(*big)])
    _, runs = build_period_diff(cat, CUI, PERIOD, [], eye, axes=PAYER, rules=store.active(CUI))
    assert _status(runs, "C2_unexplained_empty") == "FAIL"
    _, runs = build_period_diff(
        cat, CUI, PERIOD, [], eye, axes=PAYER, rules=_store(("comisioane", FEES)).active(CUI)
    )
    assert _status(runs, "C2_unexplained_empty") == "FAIL"


def _rj_month(cat, rules):
    eye = ExportEye(product="saga", lines=read_saga_rj(SINK / "saga_rj.xls"), cui=CUI)
    expected = [
        _exp(*PURCHASE, n=1),
        _exp("AB0058", "2026-09-10", "167.06", "16.56", n=2),
        _exp(*SALE, doc_class="iesire", n=3),
    ]
    return build_period_diff(cat, CUI, PERIOD, expected, eye, axes=PAYER, rules=rules)


def test_line_rule_explains_the_bank_payment(cat):
    diff, runs = _rj_month(cat, [])
    assert _status(runs, "C0_synthetic_parity") == "FAIL"
    diff, runs = _rj_month(cat, _store(("plati_furnizori", PAYMENTS)).active(CUI))
    assert diff.synthetic_delta["401:debit"].delta == "0.00"
    assert diff.synthetic_delta["5121:credit"].delta == "0.00"
    assert _status(runs, "C0_synthetic_parity") == "PASS"


def test_a_broad_line_rule_never_counts_a_document_twice(cat):
    broad = {
        "description": "Tot ce intră pe 401",
        "scope": "line",
        "line": {"debit": "*", "credit": "401*"},
    }
    diff, _ = _rj_month(cat, _store(("prea_larg", broad)).active(CUI))
    assert diff.synthetic_delta["401:credit"].delta == "0.00"  # invoice lines already expected


# ----- HITL answers -----


def test_explained_rule_answer_needs_an_existing_rule(cat):
    store = _store(("comisioane", FEES))
    assert check_explained_rule(store, CUI, ExplainedRuleResume(rule_id="comisioane")) is None
    assert "POST /rules" in check_explained_rule(store, CUI, ExplainedRuleResume(rule_id="ok"))
    assert check_explained_rule(store, "20000005", ExplainedRuleResume(rule_id="comisioane"))


@pytest.mark.parametrize(
    ("answer", "problem"),
    [
        (
            {"control_id": "C2_unexplained_empty", "disposition": "explained_rule"},
            "needs a rule_id",
        ),
        (
            {
                "control_id": "C2_unexplained_empty",
                "disposition": "explained_rule",
                "rule_id": "nope",
            },
            "no explained rule",
        ),
        ({"control_id": "C9_invented", "disposition": "hold"}, "unknown control"),
        (
            {"control_id": "C2_unexplained_empty", "disposition": "hold", "rule_id": "comisioane"},
            "only given with",
        ),
        (
            {
                "control_id": "C2_unexplained_empty",
                "disposition": "explained_rule",
                "rule_id": "comisioane",
            },
            None,
        ),
        ({"control_id": "C1_outbound_complete", "disposition": "reopen"}, None),
    ],
)
def test_control_disposition_cannot_clear_without_a_rule(cat, answer, problem):
    store = _store(("comisioane", FEES))
    got = check_control_disposition(
        store, CUI, cat.controls, ControlDispositionResume.model_validate(answer)
    )
    assert (got is None) if problem is None else (problem in got)


# ----- HTTP -----


def test_rules_route_versions_and_feeds_the_period_diff(cat):
    from poarta_contabila.period_diff import InMemoryPeriodStore
    from tests.test_runtime import Ops, _runtime

    o = Ops(_runtime(cat, rules=InMemoryRuleStore(), periods=InMemoryPeriodStore()))
    assert (
        o.http.post(
            "/rules", json={"cui": CUI, "rule_id": "plati_furnizori", **PAYMENTS}, headers=o.op
        ).status_code
        == 422
    )  # tenant not registered
    o.tenant()
    o.upload_rj()
    first = o.http.post(
        "/rules", json={"cui": CUI, "rule_id": "plati_furnizori", **PAYMENTS}, headers=o.op
    ).json()
    again = o.http.post(
        "/rules", json={"cui": CUI, "rule_id": "plati_furnizori", **PAYMENTS}, headers=o.op
    ).json()
    assert first["version"] == again["version"] == 1
    assert [r["rule_id"] for r in o.http.get(f"/rules/{CUI}", headers=o.op).json()] == [
        "plati_furnizori"
    ]
    out = o.http.get(
        f"/periods/{CUI}/{PERIOD}/diff", params={"tva": "tva_platitor"}, headers=o.op
    ).json()
    assert out["diff"]["synthetic_delta"]["5121:credit"]["delta"] == "0.00"


def test_postgres_rule_store(cat):
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    from poarta_contabila.jobs import PostgresJobStore
    from poarta_contabila.rules import PostgresRuleStore

    PostgresJobStore(dsn, reset=True)
    store = PostgresRuleStore(dsn)
    assert store.add(CUI, "comisioane", RuleBody.model_validate(FEES)).version == 1
    assert store.add(CUI, "comisioane", RuleBody.model_validate(FEES)).version == 1
    changed = RuleBody.model_validate({**FEES, "description": "Comisioane banca"})
    assert store.add(CUI, "comisioane", changed).version == 2
    store.add(CUI, "plati", RuleBody.model_validate(PAYMENTS))
    assert [(r.rule_id, r.version) for r in store.active(CUI)] == [("comisioane", 2), ("plati", 1)]
