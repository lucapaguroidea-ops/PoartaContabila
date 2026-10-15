"""core.calendar: when each owed filing is due (R22 of the module review's register).

Which filings a firm owes for a period is ``filings.due_filings`` (CO.DiT axes against
``ArticoleFiling``). This module adds **when**: each form's term is a catalog row
(``ArticoleTerms``) quoted from the notes library's declarations register at a pinned commit,
and a due date that falls on a non-working day moves to the next working day, over the days
pinned per year in ``ArticoleNonWorking``. Nothing is assumed: no term, frequency, rest day or
holiday is written here (L40).

Fail closed (L24): an owed filing whose due date cannot be computed is **refused** with its
reason (no term for its form, its frequency axis unset, a day the month does not have, a year
with no pinned non-working days), never dropped and never guessed. Every owed filing ends up
in exactly one of ``CalendarResult.items`` or ``CalendarResult.refused``.

Pure: no store, no clock, no I/O beyond the catalog already loaded.
"""

from __future__ import annotations

import calendar as _cal
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from poarta_contabila.catalog import Catalog
from poarta_contabila.filings import due_filings
from poarta_contabila.lockset import LockSet, lock_set

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
FREQUENCIES = ("lunar", "trimestrial")


class CalendarError(ValueError):
    """A term or a non-working-day row the calendar cannot read."""


@dataclass(frozen=True)
class NonWorkingYear:
    year: int
    weekly_rest: frozenset[int]  # date.weekday() numbers
    days: frozenset[date]
    source: str
    certainty: str

    def working(self, d: date) -> bool:
        return d.weekday() not in self.weekly_rest and d not in self.days


@dataclass(frozen=True)
class Obligation:
    """One owed filing with its due date. Holds no client data beyond what the caller keys it by."""

    filing_id: str
    form: str
    filing_period: str  # YYYY-MM or YYYY-Qn
    due: str  # ISO date, a string as money and fiscal dates are (L24)
    unshifted: str  # the register's day before any move over non-working days
    conditional: str | None
    certainty: str
    term_id: str
    source: str
    lock: LockSet  # the pins this entry was computed under (core.provenance)


@dataclass
class CalendarResult:
    period: str
    items: list[Obligation] = field(default_factory=list)
    refused: list[dict[str, str]] = field(default_factory=list)


def load_nonworking(cat: Catalog) -> dict[int, NonWorkingYear]:
    """The pinned non-working days per year (empty until a year is pinned with its source)."""
    out: dict[int, NonWorkingYear] = {}
    for row in (cat.docs.get("ArticoleNonWorking") or {}).get("years") or []:
        year = int(row["year"])
        prov = row.get("provenance") or {}
        if not prov.get("source") or prov.get("certainty") not in ("confirmed", "de_confirmat"):
            raise CalendarError(f"{row.get('year_id')}: a non-working year needs its source")
        rest = row.get("weekly_rest")
        if rest is None or any(r not in WEEKDAYS for r in rest):
            raise CalendarError(f"{row.get('year_id')}: weekly_rest must name weekdays")
        days = frozenset(date.fromisoformat(d) for d in row.get("days") or [])
        if any(d.year != year for d in days):
            raise CalendarError(f"{row.get('year_id')}: a day outside {year}")
        out[year] = NonWorkingYear(
            year=year,
            weekly_rest=frozenset(WEEKDAYS.index(r) for r in rest),
            days=days,
            source=str(prov["source"]),
            certainty=str(prov["certainty"]),
        )
    return out


def terms_by_form(cat: Catalog) -> dict[str, dict[str, Any]]:
    doc = cat.docs.get("ArticoleTerms") or {}
    out: dict[str, dict[str, Any]] = {}
    for row in doc.get("terms") or []:
        if row["form"] in out:
            raise CalendarError(f"two terms for {row['form']}")
        out[row["form"]] = row
    return out


def _source(cat: Catalog, term: dict[str, Any]) -> str:
    reg = (cat.docs.get("ArticoleTerms") or {}).get("register") or {}
    return f"{reg.get('library')}:{reg.get('path')}@{str(reg.get('commit', ''))[:7]} {term['form']}"


def _month_end_periods(period: str, frequency: str) -> tuple[str, date] | None:
    """The filing period that ends with month *period*, or None if none ends there."""
    y, m = int(period[:4]), int(period[5:7])
    end = date(y, m, _cal.monthrange(y, m)[1])
    if frequency == "lunar":
        return period, end
    if m % 3 == 0:
        return f"{y}-Q{m // 3}", end
    return None


def _target(end: date, months_after: int, day: Any) -> date:
    idx = end.year * 12 + (end.month - 1) + months_after
    y, m = divmod(idx, 12)
    m += 1
    last = _cal.monthrange(y, m)[1]
    if day == "last":
        return date(y, m, last)
    if not isinstance(day, int) or day < 1:
        raise CalendarError(f"day must be a positive number or 'last', not {day!r}")
    if day > last:
        raise CalendarError(f"{y}-{m:02d} has no day {day}")
    return date(y, m, day)


def _shift(d: date, years: dict[int, NonWorkingYear]) -> date:
    for _ in range(60):  # a month of non-working days would be a bad pin, not a calendar
        year = years.get(d.year)
        if year is None:
            raise CalendarError(f"no non-working days pinned for {d.year}")
        if year.working(d):
            return d
        d += timedelta(days=1)
    raise CalendarError(f"no working day within 60 days of {d.isoformat()}")


def obligations(
    cat: Catalog,
    axes: dict[str, str],
    period: str,
    nonworking: dict[int, NonWorkingYear] | None = None,
) -> CalendarResult:
    """Every filing *axes* owe whose filing period ends with month *period*, and when it is due.

    *axes* are the firm's CO.DiT values for that period. *nonworking* defaults to the catalog's
    pinned years.
    """
    if len(period) != 7 or period[4] != "-":
        raise CalendarError(f"period must be YYYY-MM, not {period!r}")
    years = load_nonworking(cat) if nonworking is None else nonworking
    terms = terms_by_form(cat)
    lock = lock_set(cat)
    result = CalendarResult(period=period)
    for row in due_filings(cat, axes):
        fid, form = row["filing_id"], row["form"]
        term = terms.get(form)
        if term is None:
            result.refused.append({"filing_id": fid, "form": form, "reason": f"no term for {form}"})
            continue
        if term["frequency"] == "from_axis":
            axis = term["frequency_axis"]
            frequency = axes.get(axis)
            if frequency not in FREQUENCIES:
                result.refused.append(
                    {"filing_id": fid, "form": form, "reason": f"CO.DiT axis {axis} is not set"}
                )
                continue
        else:
            frequency = term["frequency"]
        span = _month_end_periods(period, frequency)
        if span is None:
            continue  # a quarterly filing whose quarter does not end this month: nothing owed yet
        filing_period, end = span
        try:
            unshifted = _target(end, int(term["months_after"]), term["day"])
            due = _shift(unshifted, years) if term.get("shift") == "next_working_day" else unshifted
        except CalendarError as exc:
            result.refused.append({"filing_id": fid, "form": form, "reason": str(exc)})
            continue
        pinned = (years[d.year].certainty for d in (unshifted, due) if d.year in years)
        certainties = {term.get("certainty"), *pinned}
        result.items.append(
            Obligation(
                filing_id=fid,
                form=form,
                filing_period=filing_period,
                due=due.isoformat(),
                unshifted=unshifted.isoformat(),
                conditional=term.get("only_if"),
                certainty="confirmed" if certainties == {"confirmed"} else "de_confirmat",
                term_id=term["term_id"],
                source=_source(cat, term),
                lock=lock,
            )
        )
    return result
