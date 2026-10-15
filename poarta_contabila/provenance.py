"""Provenance by lock set on stored results (R36 of the module review's register).

Every proposal (a Job), verdict (PRE / POST) and tie-out (the period difference, its control
runs, the close decision) a store writes records the ``LockSet`` the runtime read its pins
under (``lockset.py``): the core version, the notes library register's commit, the legal
corpus release. When a pin is corrected or revoked, ``impacted_records`` lists exactly the
stored results that read it; ``unlocked_records`` lists the rows written before lock sets were
recorded, which nothing can place.

The runtime gives each store its lock set at boot (``Runtime.__post_init__``); a store writes
it with every new row and keeps the first one on a replay (L22), except the close decision,
which is decided again in place and takes the lock set it was last decided under.

Runtime side, not core: it reads the domain store.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any

from poarta_contabila.lockset import LockSet, impacted

# record name → the Runtime attribute holding its store
RECORDS: dict[str, str] = {
    "jobs": "jobs",  # proposals
    "recon": "recon",  # PRE / POST verdicts
    "periods": "periods",  # the period difference and its control runs (tie-outs)
    "closes": "closes",  # the close decision
}


def lock_json(lock: LockSet | None) -> str | None:
    """The value a store writes into a ``lock jsonb`` column."""
    return json.dumps(lock.as_dict()) if lock is not None else None


def lock_from(value: Any) -> LockSet | None:
    """A ``lock`` column read back (psycopg returns jsonb as a dict)."""
    if isinstance(value, str):
        value = json.loads(value)
    return LockSet.from_dict(value)


def _rows(stores: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    for record, store in stores.items():
        if store is None:
            continue
        for key, lock in store.locked():
            yield {"record": record, "key": tuple(key), "lock": lock}


def impacted_records(
    stores: Mapping[str, Any],
    *,
    core: str | None = None,
    library: str | None = None,
    corpus: str | None = None,
) -> list[dict[str, Any]]:
    """Every stored result whose lock set matches each pin named: ``{record, key, lock}``."""
    locked = [r for r in _rows(stores) if r["lock"] is not None]
    return impacted(locked, core=core, library=library, corpus=corpus)


def unlocked_records(stores: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Stored results written before lock sets were recorded: their pins are unknown."""
    return [r for r in _rows(stores) if r["lock"] is None]
