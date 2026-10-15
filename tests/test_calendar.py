"""core.calendar: every owed filing gets one due date, read from the register's term at its pin,
or one refusal with its reason (fail closed, L24); no term is a literal here (L40).

The non-working year below is invented for the tests (data_class synthetic): no year is pinned
in the catalog, and none may be written from memory.
"""

from __future__ import annotations

import calendar as stdcal
import copy
from datetime import date, timedelta

import pytest

from poarta_contabila import core
from poarta_contabila.calendar import (
    CalendarError,
    NonWorkingYear,
    load_nonworking,
    obligations,
    terms_by_form,
)
from poarta_contabila.catalog import load_catalog
from poarta_contabila.filings import due_filings
from poarta_contabila.synthetic.firms import FIRMS

FREQ = {"tva_period": "lunar", "d100_period": "lunar", "d112_period": "lunar"}
MONTHS = [f"2026-{m:02d}" for m in range(1, 13)]


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def synthetic_year(year: int, days: tuple[date, ...] = ()) -> NonWorkingYear:
    """An invented year for the tests: a fixed weekly rest and the days a test names."""
    return NonWorkingYear(
        year=year,
        weekly_rest=frozenset({5, 6}),
        days=frozenset(days),
        source="synthetic test year (invented)",
        certainty="de_confirmat",
    )


def years(*ys: int, days: tuple[date, ...] = ()) -> dict[int, NonWorkingYear]:
    return {y: synthetic_year(y, tuple(d for d in days if d.year == y)) for y in ys}


def expected(term: dict, end: date, nw: dict[int, NonWorkingYear]) -> date:
    """The register's day, computed from the term row (not from a literal), then moved."""
    idx = end.year * 12 + end.month - 1 + term["months_after"]
    y, m = divmod(idx, 12)
    m += 1
    d = date(y, m, stdcal.monthrange(y, m)[1] if term["day"] == "last" else term["day"])
    while not nw[d.year].working(d):
        d += timedelta(days=1)
    return d


def test_every_owed_filing_has_one_due_date_or_one_refusal(cat) -> None:
    nw = years(2026, 2027)
    for firm in FIRMS.values():
        axes = {**firm.axes, **FREQ}
        owed = {r["filing_id"] for r in due_filings(cat, axes)}
        for period in MONTHS:
            res = obligations(cat, axes, period, nw)
            got = [o.filing_id for o in res.items] + [r["filing_id"] for r in res.refused]
            assert sorted(got) == sorted(owed), (firm.key, period)  # monthly: each owed once


def test_the_due_date_is_the_register_term_moved_over_non_working_days(cat) -> None:
    nw = years(2026, 2027)
    axes = {"tva": "tva_platitor", "employees": "has", **FREQ}
    terms = terms_by_form(cat)
    for period in MONTHS:
        y, m = int(period[:4]), int(period[5:])
        end = date(y, m, stdcal.monthrange(y, m)[1])
        for o in obligations(cat, axes, period, nw).items:
            assert o.due == expected(terms[o.form], end, nw).isoformat(), (o.form, period)
            assert o.source.endswith(o.form) and "@5ca87f5" in o.source


def test_a_non_working_day_moves_the_date_to_the_next_working_day(cat) -> None:
    term = terms_by_form(cat)["D300"]
    plain = obligations(cat, {"tva": "tva_platitor", **FREQ}, "2026-04", years(2026)).items
    d300 = next(o for o in plain if o.form == "D300")
    blocked = date.fromisoformat(d300.due)
    moved = obligations(
        cat, {"tva": "tva_platitor", **FREQ}, "2026-04", years(2026, days=(blocked,))
    ).items
    d300b = next(o for o in moved if o.form == "D300")
    assert d300b.unshifted == d300.unshifted == date(2026, 5, term["day"]).isoformat()
    assert date.fromisoformat(d300b.due) > blocked


def test_changing_the_pinned_term_changes_the_answer(cat) -> None:
    other = copy.deepcopy(cat)
    row = next(t for t in other.docs["ArticoleTerms"]["terms"] if t["form"] == "D300")
    row["day"] = row["day"] - 1
    axes = {"tva": "tva_platitor", **FREQ}
    a = next(o for o in obligations(cat, axes, "2026-06", years(2026)).items if o.form == "D300")
    b = next(o for o in obligations(other, axes, "2026-06", years(2026)).items if o.form == "D300")
    assert a.unshifted != b.unshifted


def test_quarterly_filings_fall_due_only_after_the_quarter(cat) -> None:
    axes = {"tva": "tva_platitor", **FREQ, "tva_period": "trimestrial"}
    nw = years(2026)
    for period in MONTHS[:-1]:
        forms = {o.form: o for o in obligations(cat, axes, period, nw).items}
        if int(period[5:]) % 3:
            assert "D300" not in forms
        else:
            assert forms["D300"].filing_period == f"2026-Q{int(period[5:]) // 3}"


def test_operations_only_filings_are_marked_conditional(cat) -> None:
    axes = {"tva": "tva_platitor", "cross_border": "inbound_eu_services", **FREQ}
    items = obligations(cat, axes, "2026-05", years(2026)).items
    assert next(o for o in items if o.form == "D390").conditional == "operations_in_period"
    assert next(o for o in items if o.form == "D300").conditional is None


# ----- refusals: each seen to fail (R16) -----


def _refused(res, form: str) -> str:
    return next(r["reason"] for r in res.refused if r["form"] == form)


def test_refuses_a_year_without_pinned_non_working_days(cat) -> None:
    assert load_nonworking(cat) == {}  # nothing is pinned until a sourced year is added
    res = obligations(cat, {"tva": "tva_platitor", **FREQ}, "2026-04")
    assert not res.items
    assert "no non-working days pinned for 2026" in _refused(res, "D300")


def test_refuses_when_the_due_date_falls_in_an_unpinned_year(cat) -> None:
    res = obligations(cat, {"tva": "tva_platitor", **FREQ}, "2026-12", years(2026))
    assert "no non-working days pinned for 2027" in _refused(res, "D300")


def test_refuses_an_unset_frequency_axis(cat) -> None:
    res = obligations(cat, {"tva": "tva_platitor"}, "2026-04", years(2026))
    assert "tva_period is not set" in _refused(res, "D300")


def test_refuses_a_day_the_month_does_not_have(cat) -> None:
    term = terms_by_form(cat)["D394"]
    res = obligations(cat, {"tva": "tva_platitor", **FREQ}, "2026-01", years(2026))
    assert f"2026-02 has no day {term['day']}" in _refused(res, "D394")


def test_refuses_an_owed_filing_with_no_term(cat) -> None:
    other = copy.deepcopy(cat)
    other.docs["ArticoleTerms"]["terms"] = [
        t for t in other.docs["ArticoleTerms"]["terms"] if t["form"] != "D406"
    ]
    res = obligations(other, {"tva": "tva_platitor", **FREQ}, "2026-04", years(2026))
    assert _refused(res, "D406") == "no term for D406"


def test_refuses_a_non_working_year_without_a_source(cat) -> None:
    other = copy.deepcopy(cat)
    other.docs["ArticoleNonWorking"]["years"] = [
        {"year_id": "nw_x", "year": 2026, "weekly_rest": [], "days": [], "provenance": {}}
    ]
    with pytest.raises(CalendarError, match="needs its source"):
        load_nonworking(other)


def test_refuses_a_malformed_period(cat) -> None:
    with pytest.raises(CalendarError):
        obligations(cat, {}, "2026-4", years(2026))


def test_the_calendar_is_in_the_core() -> None:
    assert core.obligations is obligations
    assert "poarta_contabila.calendar" in core.CORE_MODULES["core.calendar"]
