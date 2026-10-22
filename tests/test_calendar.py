"""core.calendar: every owed filing gets one due date, read from the register's term at its pin,
or one refusal with its reason (fail closed, L24); no term is a literal here (L40).

The non-working year below is invented for the tests (data_class synthetic): no year is pinned
in the catalog, and none may be written from memory. So is the register pin's freshness window
(``WINDOW``): the catalog leaves it unset for the owner, and an unset window refuses everything.
"""

from __future__ import annotations

import calendar as stdcal
import copy
import inspect
from datetime import date, datetime, timedelta

import pytest

from poarta_contabila import core
from poarta_contabila.calendar import (
    CalendarError,
    NonWorkingYear,
    load_nonworking,
    obligations,
    register_freshness,
    terms_by_form,
)
from poarta_contabila.catalog import load_catalog
from poarta_contabila.filings import due_filings
from poarta_contabila.synthetic.firms import FIRMS

FREQ = {"tva_period": "lunar", "d100_period": "lunar", "d112_period": "lunar"}
MONTHS = [f"2026-{m:02d}" for m in range(1, 13)]


WINDOW = 90  # an invented freshness window for the tests; the owner sets the real one


def fresh(cat, window: int | None = WINDOW):
    """*cat* with the register pin's freshness window set (to an invented test value)."""
    other = copy.deepcopy(cat)
    other.docs["ArticoleTerms"]["register"]["max_age_days"] = window
    return other


def verified(cat) -> date:
    return date.fromisoformat(cat.docs["ArticoleTerms"]["register"]["verified_at"])


@pytest.fixture(scope="module")
def real():
    return load_catalog()


@pytest.fixture(scope="module")
def cat(real):
    return fresh(real)


def inside(cat) -> date:
    return verified(cat) + timedelta(days=WINDOW // 2)  # a day inside the test window


def ask(cat, axes, period, nw=None):
    """``obligations`` on a day inside the test window."""
    return obligations(cat, axes, period, nw, as_of=inside(cat))


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
        for freq in ("lunar", "trimestrial"):
            axes = {**firm.axes, **{a: freq for a in FREQ}}
            owed = {r["filing_id"] for r in due_filings(cat, axes)}
            for period in MONTHS:
                res = ask(cat, axes, period, nw)
                got = [o.filing_id for o in res.items]
                got += [r["filing_id"] for r in res.refused + res.later]
                assert sorted(got) == sorted(owed), (firm.key, freq, period)  # each owed once


def test_the_due_date_is_the_register_term_moved_over_non_working_days(cat) -> None:
    nw = years(2026, 2027)
    axes = {"tva": "tva_platitor", "employees": "has", **FREQ}
    terms = terms_by_form(cat)
    for period in MONTHS:
        y, m = int(period[:4]), int(period[5:])
        end = date(y, m, stdcal.monthrange(y, m)[1])
        for o in ask(cat, axes, period, nw).items:
            assert o.due == expected(terms[o.form], end, nw).isoformat(), (o.form, period)
            assert o.source.endswith(o.form) and "@5ca87f5" in o.source


def test_a_non_working_day_moves_the_date_to_the_next_working_day(cat) -> None:
    term = terms_by_form(cat)["D300"]
    plain = ask(cat, {"tva": "tva_platitor", **FREQ}, "2026-04", years(2026)).items
    d300 = next(o for o in plain if o.form == "D300")
    blocked = date.fromisoformat(d300.due)
    moved = ask(cat, {"tva": "tva_platitor", **FREQ}, "2026-04", years(2026, days=(blocked,))).items
    d300b = next(o for o in moved if o.form == "D300")
    assert d300b.unshifted == d300.unshifted == date(2026, 5, term["day"]).isoformat()
    assert date.fromisoformat(d300b.due) > blocked


def test_changing_the_pinned_term_changes_the_answer(cat) -> None:
    other = copy.deepcopy(cat)
    row = next(t for t in other.docs["ArticoleTerms"]["terms"] if t["form"] == "D300")
    row["day"] = row["day"] - 1
    axes = {"tva": "tva_platitor", **FREQ}
    a = next(o for o in ask(cat, axes, "2026-06", years(2026)).items if o.form == "D300")
    b = next(o for o in ask(other, axes, "2026-06", years(2026)).items if o.form == "D300")
    assert a.unshifted != b.unshifted


def test_quarterly_filings_fall_due_only_after_the_quarter(cat) -> None:
    axes = {"tva": "tva_platitor", **FREQ, "tva_period": "trimestrial"}
    nw = years(2026)
    for period in MONTHS[:-1]:
        res = ask(cat, axes, period, nw)
        forms = {o.form: o for o in res.items}
        if int(period[5:]) % 3:
            assert "D300" not in forms
            later = next(r for r in res.later if r["form"] == "D300")
            assert later["reason"] == f"its quarter does not end in {period}"
        else:
            assert forms["D300"].filing_period == f"2026-Q{int(period[5:]) // 3}"


def test_operations_only_filings_are_marked_conditional(cat) -> None:
    axes = {"tva": "tva_platitor", "cross_border": "inbound_eu_services", **FREQ}
    items = ask(cat, axes, "2026-05", years(2026)).items
    assert next(o for o in items if o.form == "D390").conditional == "operations_in_period"
    assert next(o for o in items if o.form == "D300").conditional is None


# ----- refusals: each seen to fail (R16) -----


def _refused(res, form: str) -> str:
    return next(r["reason"] for r in res.refused if r["form"] == form)


def test_refuses_a_year_without_pinned_non_working_days(cat) -> None:
    assert load_nonworking(cat) == {}  # nothing is pinned until a sourced year is added
    res = ask(cat, {"tva": "tva_platitor", **FREQ}, "2026-04")
    assert not res.items
    assert "no non-working days pinned for 2026" in _refused(res, "D300")


def test_refuses_when_the_due_date_falls_in_an_unpinned_year(cat) -> None:
    res = ask(cat, {"tva": "tva_platitor", **FREQ}, "2026-12", years(2026))
    assert "no non-working days pinned for 2027" in _refused(res, "D300")


def test_refuses_an_unset_frequency_axis(cat) -> None:
    res = ask(cat, {"tva": "tva_platitor"}, "2026-04", years(2026))
    assert "tva_period is not set" in _refused(res, "D300")


def test_refuses_a_day_the_month_does_not_have(cat) -> None:
    term = terms_by_form(cat)["D394"]
    res = ask(cat, {"tva": "tva_platitor", **FREQ}, "2026-01", years(2026))
    assert f"2026-02 has no day {term['day']}" in _refused(res, "D394")


def test_refuses_an_owed_filing_with_no_term(cat) -> None:
    other = copy.deepcopy(cat)
    other.docs["ArticoleTerms"]["terms"] = [
        t for t in other.docs["ArticoleTerms"]["terms"] if t["form"] != "D406"
    ]
    res = ask(other, {"tva": "tva_platitor", **FREQ}, "2026-04", years(2026))
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
        ask(cat, {}, "2026-4", years(2026))


def test_the_calendar_is_in_the_core() -> None:
    assert core.obligations is obligations
    assert "poarta_contabila.calendar" in core.CORE_MODULES["core.calendar"]


# ----- freshness of the register pin (R23): a stale pin dates nothing -----

AXES = {"tva": "tva_platitor", "employees": "has", **FREQ}


def test_the_register_window_is_the_owners_value_left_unset(real) -> None:
    register = real.docs["ArticoleTerms"]["register"]
    assert "max_age_days" in register and register["max_age_days"] is None  # never invented
    assert verified(real).isoformat() == register["verified_at"]


def test_an_unset_freshness_window_refuses_every_item(real) -> None:
    res = obligations(real, AXES, "2026-04", years(2026), as_of=verified(real))
    owed = {r["filing_id"] for r in due_filings(real, AXES)}
    assert not res.items and not res.later
    assert {r["filing_id"] for r in res.refused} == owed
    assert all("freshness window is not set" in r["reason"] for r in res.refused)


def test_a_stale_register_pin_refuses_every_item(cat) -> None:
    owed = {r["filing_id"] for r in due_filings(cat, AXES)}
    last = verified(cat) + timedelta(days=WINDOW)
    on_edge = obligations(cat, AXES, "2026-04", years(2026), as_of=last)
    assert {o.filing_id for o in on_edge.items} == owed  # the window's last day still dates
    stale = obligations(cat, AXES, "2026-04", years(2026), as_of=last + timedelta(days=1))
    assert not stale.items
    assert {r["filing_id"] for r in stale.refused} == owed
    reason = stale.refused[0]["reason"]
    assert reason.startswith("the register pin is stale") and f"{WINDOW}-day window" in reason


def test_a_stale_pin_refuses_even_the_filings_a_quarter_would_defer(cat) -> None:
    axes = {**AXES, "tva_period": "trimestrial"}
    stale = verified(cat) + timedelta(days=WINDOW + 1)
    res = obligations(cat, axes, "2026-04", years(2026), as_of=stale)
    assert not res.items and not res.later
    assert {r["filing_id"] for r in res.refused} == {r["filing_id"] for r in due_filings(cat, axes)}


def test_a_malformed_window_or_verified_at_refuses(cat) -> None:
    day = verified(cat)
    for bad in (-1, "90", True, 1.5):
        assert "whole number of days" in register_freshness(fresh(cat, bad), day)
    other = fresh(cat)
    other.docs["ArticoleTerms"]["register"]["verified_at"] = None
    assert "no verified_at" in register_freshness(other, day)
    assert register_freshness(cat, day) is None


def test_freshness_is_judged_on_the_as_of_the_caller_passes(cat) -> None:
    # the core has no clock: as_of is required and is a date, never read from the system
    with pytest.raises(TypeError):
        obligations(cat, AXES, "2026-04", years(2026))  # type: ignore[call-arg]
    with pytest.raises(CalendarError, match="as_of must be a date"):
        register_freshness(cat, datetime(2026, 8, 1))  # type: ignore[arg-type]
    import poarta_contabila.calendar as calendar_module

    src = inspect.getsource(calendar_module)
    assert "today(" not in src and "now(" not in src


def test_every_due_date_path_in_the_package_passes_as_of() -> None:
    import ast
    from pathlib import Path

    import poarta_contabila

    root = Path(poarta_contabila.__file__).parent
    calls = []
    for f in root.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            name = getattr(node, "func", None)
            name = getattr(name, "id", None) or getattr(name, "attr", None)
            if isinstance(node, ast.Call) and name == "obligations":
                calls.append((f.name, {k.arg for k in node.keywords}))
    assert calls  # the runtime computes due dates
    assert all("as_of" in kws for _, kws in calls), calls


def test_freshness_is_in_the_core() -> None:
    assert core.register_freshness is register_freshness
