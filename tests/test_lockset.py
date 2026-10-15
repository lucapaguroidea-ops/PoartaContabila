"""core.provenance: every calendar entry records the lock set it was computed under (the core
version, the notes library's register commit, the legal corpus release), and an impact query
by lock set returns exactly the entries that read a given pin (R36)."""

from __future__ import annotations

import copy

import pytest

from poarta_contabila import core
from poarta_contabila.calendar import NonWorkingYear, obligations
from poarta_contabila.catalog import load_catalog
from poarta_contabila.lockset import LockSet, LockSetError, impacted, lock_set

AXES = {
    "tva": "tva_platitor",
    "employees": "has",
    "tva_period": "lunar",
    "d100_period": "lunar",
    "d112_period": "lunar",
}


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def synthetic(year: int) -> dict[int, NonWorkingYear]:
    """An invented year for the tests (no year is pinned in the catalog)."""
    return {
        year: NonWorkingYear(
            year=year,
            weekly_rest=frozenset({5, 6}),
            days=frozenset(),
            source="synthetic test year (invented)",
            certainty="de_confirmat",
        )
    }


def with_register_commit(cat, commit: str):
    other = copy.deepcopy(cat)
    other.docs["ArticoleTerms"]["register"]["commit"] = commit
    return other


def test_the_lock_set_names_the_core_the_register_and_the_corpus(cat) -> None:
    lock = lock_set(cat)
    assert lock.core == core.CORE_VERSION
    assert lock.library == cat.docs["ArticoleTerms"]["register"]["commit"]
    assert lock.corpus is None  # no legal corpus release is pinned in this repository yet
    assert lock.key == f"core-v{core.CORE_VERSION}|library@{lock.library[:7]}|corpus@unpinned"


def test_every_calendar_entry_records_its_lock_set(cat) -> None:
    items = obligations(cat, AXES, "2026-04", synthetic(2026)).items
    assert items
    assert {o.lock for o in items} == {lock_set(cat)}


def test_a_different_register_pin_is_a_different_lock_set(cat) -> None:
    other = with_register_commit(cat, "0" * 40)
    assert lock_set(other) != lock_set(cat)
    assert obligations(other, AXES, "2026-04", synthetic(2026)).items[0].lock == lock_set(other)


def test_impact_query_returns_exactly_the_entries_of_a_pin(cat) -> None:
    old = with_register_commit(cat, "0" * 40)
    before = obligations(old, AXES, "2026-04", synthetic(2026)).items
    after = obligations(cat, AXES, "2026-04", synthetic(2026)).items
    entries = before + after
    hit = impacted(entries, library="0" * 40)
    assert hit == before
    assert impacted(entries, core=core.CORE_VERSION) == entries
    assert impacted(entries, library="0" * 40, core="9.9.9") == []


def test_impact_query_needs_a_pin_to_look_for() -> None:
    with pytest.raises(LockSetError):
        impacted([], core=None, library=None, corpus=None)


def test_refuses_a_register_without_a_full_commit(cat) -> None:
    with pytest.raises(LockSetError, match="commit"):
        lock_set(with_register_commit(cat, "5ca87f5"))


def test_the_lock_set_is_in_the_core() -> None:
    assert core.LockSet is LockSet and core.lock_set is lock_set and core.impacted is impacted
    assert "poarta_contabila.lockset" in core.CORE_MODULES["core.provenance"]
