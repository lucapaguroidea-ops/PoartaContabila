"""Provenance by lock set on stored results (R36): every proposal (Job), verdict (PRE / POST)
and tie-out (period diff, control runs, the close decision) a store writes records the lock set
the runtime read its pins under, and the impact query finds exactly the records of a pin.
Rows written before a lock set existed are listed as unlocked, never guessed."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from poarta_contabila.agent import InMemoryAgentStore
from poarta_contabila.catalog import load_catalog
from poarta_contabila.close import InMemoryCloseStore, PostgresCloseStore
from poarta_contabila.jobs import InMemoryJobStore, PostgresJobStore
from poarta_contabila.lockset import LockSet, LockSetError, lock_set
from poarta_contabila.packages import InMemoryBlobStore, InMemoryPackageStore
from poarta_contabila.period_diff import InMemoryPeriodStore, PostgresPeriodStore
from poarta_contabila.provenance import RECORDS, impacted_records, unlocked_records
from poarta_contabila.recon.pre import InMemoryReconStore, PostgresReconStore
from poarta_contabila.registry import InMemoryRegistry
from poarta_contabila.runtime import build_runtime
from poarta_contabila.triage import EmitDecision, Pack

OLD = LockSet(core="0.3.0", library="a" * 40, corpus=None)
NEW = LockSet(core="0.3.0", library="b" * 40, corpus=None)
CUI = "1000009"  # invented, passes the check digit (L36)


def _diff(period: str, snapshot: str) -> SimpleNamespace:
    return SimpleNamespace(
        cui=CUI, period=period, snapshot_id=snapshot, model_dump_json=lambda: "{}"
    )


def _run(control: str) -> SimpleNamespace:
    return SimpleNamespace(control_id=control, model_dump_json=lambda: "{}")


def _close(period: str) -> SimpleNamespace:
    return SimpleNamespace(
        cui=CUI, period=period, expected_set_hash=None, model_dump_json=lambda: "{}"
    )


class _Verdict(SimpleNamespace):
    """The shape a recon store needs of a PRE / POST result (its own type reads it back)."""

    def model_dump_json(self) -> str:
        return json.dumps({"snapshot_id": self.snapshot_id})

    @classmethod
    def model_validate(cls, body: dict, strict: bool = False) -> _Verdict:
        return cls(**body)


def _verdict(snapshot: str) -> _Verdict:
    return _Verdict(snapshot_id=snapshot)


def _pack(n: int, period: str = "2026-09") -> Pack:
    return Pack(
        tenant_cui=CUI,
        saga_firm_folder="0001",
        period=period,
        source_hash=f"{n:064x}",
        source_doc_id="ro_efactura_ubl",
        kinds=["ubl_spv"],
        our_role="inbound",
        counterparty_cui="20000005",
    )


DECISION = EmitDecision(emit=True, job_kind="job_ro_efactura", aisle="x")


def test_lock_set_round_trips_through_its_stored_shape() -> None:
    assert LockSet.from_dict(NEW.as_dict()) == NEW
    assert LockSet.from_dict(None) is None
    with pytest.raises(LockSetError):
        LockSet.from_dict({"core": "0.3.0", "library": "b" * 40})  # a missing pin is refused


def test_every_store_records_the_lock_set_it_was_given() -> None:
    stores = {
        "jobs": InMemoryJobStore(),
        "recon": InMemoryReconStore(),
        "periods": InMemoryPeriodStore(),
        "closes": InMemoryCloseStore(),
    }
    for s in stores.values():
        s.lock = NEW
    job = stores["jobs"].emit(_pack(1), DECISION).job
    stores["recon"].put_once("job-1", "pre", _verdict("s1"))
    stores["closes"].put(_close("2026-04"))
    stores["periods"].save(_diff("2026-04", "s1"), [_run("C1")])
    found = impacted_records(stores, library=NEW.library)
    assert {(r["record"], r["key"]) for r in found} == {
        ("jobs", (job.job_id,)),
        ("recon", ("job-1", "pre", "s1")),
        ("closes", (CUI, "2026-04")),
        ("periods", (CUI, "2026-04", "s1")),
        ("periods", (CUI, "2026-04", "C1", "s1")),
    }
    assert all(r["lock"] == NEW for r in found)


def test_the_impact_query_separates_pins_and_lists_the_unlocked() -> None:
    recon = InMemoryReconStore()
    recon.put_once("job-0", "pre", _verdict("s0"))  # before any lock set
    recon.lock = OLD
    recon.put_once("job-1", "pre", _verdict("s1"))
    recon.lock = NEW
    recon.put_once("job-2", "post", _verdict("s2"))
    stores = {"recon": recon}
    assert [r["key"] for r in impacted_records(stores, library=OLD.library)] == [
        ("job-1", "pre", "s1")
    ]
    assert [r["key"] for r in impacted_records(stores, library=NEW.library)] == [
        ("job-2", "post", "s2")
    ]
    assert [r["key"] for r in unlocked_records(stores)] == [("job-0", "pre", "s0")]
    with pytest.raises(LockSetError):
        impacted_records(stores)  # a query names a pin


def test_a_replayed_write_keeps_the_first_lock_set() -> None:
    recon = InMemoryReconStore()
    recon.lock = OLD
    recon.put_once("job-1", "pre", _verdict("s1"))
    recon.lock = NEW
    recon.put_once("job-1", "pre", _verdict("s1"))  # idempotent (L22): the first write stands
    assert impacted_records({"recon": recon}, library=OLD.library)
    assert not impacted_records({"recon": recon}, library=NEW.library)


def test_the_close_decision_takes_the_lock_set_it_was_last_decided_under() -> None:
    closes = InMemoryCloseStore()
    closes.lock = OLD
    closes.put(_close("2026-04"))
    closes.lock = NEW
    closes.put(_close("2026-04"))  # a close run is re-decided in place
    assert impacted_records({"closes": closes}, library=NEW.library)
    assert not impacted_records({"closes": closes}, library=OLD.library)


def test_the_runtime_gives_its_stores_the_catalog_lock_set() -> None:
    cat = load_catalog()
    rt = build_runtime(
        catalog=cat,
        jobs=InMemoryJobStore(),
        packages=InMemoryPackageStore(),
        blobs=InMemoryBlobStore(),
        registry=InMemoryRegistry(),
        recon=InMemoryReconStore(),
        agent_store=InMemoryAgentStore(),
        checkpointer=MemorySaver(),
        periods=InMemoryPeriodStore(),
    )
    for record, attr in RECORDS.items():
        assert getattr(rt, attr).lock == lock_set(cat), record
    assert impacted_records(rt.records(), core=lock_set(cat).core) == []  # nothing stored yet


# ----- Postgres (CI; skipped without a scratch database) -----


@pytest.fixture
def dsn() -> str:
    value = os.environ.get("POARTA_TEST_DSN")
    if not value:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    PostgresJobStore(value)  # applies the schema
    return value


def test_postgres_stores_record_and_query_the_lock_set(dsn: str) -> None:
    import psycopg

    tag = os.urandom(4).hex()
    period = f"2099-{int(tag, 16) % 12 + 1:02d}"
    stores = {
        "jobs": PostgresJobStore(dsn),
        "recon": PostgresReconStore(dsn),
        "periods": PostgresPeriodStore(dsn),
        "closes": PostgresCloseStore(dsn),
    }
    for s in stores.values():
        s.lock = NEW
    job = stores["jobs"].emit(_pack(int(tag, 16), period), DECISION).job
    stores["recon"].put_once(job.job_id, "pre", _verdict(f"s-{tag}"))
    stores["periods"].save(_diff(period, f"s-{tag}"), [_run("C1")])
    stores["closes"].put(_close(period))
    mine = [
        r
        for r in impacted_records(stores, library=NEW.library)
        if f"s-{tag}" in r["key"] or period in r["key"] or job.job_id in r["key"]
    ]
    assert {r["record"] for r in mine} == {"jobs", "recon", "periods", "closes"}
    assert all(r["lock"] == NEW for r in mine)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DELETE FROM domain.recon_verdicts WHERE job_id = %s", (job.job_id,))
        conn.execute("DELETE FROM domain.control_runs WHERE snapshot_id = %s", (f"s-{tag}",))
        conn.execute("DELETE FROM domain.close_snapshots WHERE snapshot_id = %s", (f"s-{tag}",))
        conn.execute("DELETE FROM domain.close_runs WHERE period = %s", (period,))
        conn.execute("DELETE FROM domain.job_events WHERE job_id = %s", (job.job_id,))
        conn.execute("DELETE FROM domain.jobs WHERE job_id = %s", (job.job_id,))
