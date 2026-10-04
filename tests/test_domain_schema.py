"""the domain schema applies, enforces idempotency keys, and holds no books."""

from __future__ import annotations

import os

import pytest

from poarta_contabila.db import schema_sql

psycopg = pytest.importorskip("psycopg")
DSN = os.environ.get("POARTA_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set POARTA_TEST_DSN to a scratch Postgres")


@pytest.fixture
def conn():
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute("DROP SCHEMA IF EXISTS domain CASCADE")
        c.execute(schema_sql())
        c.execute(schema_sql())  # idempotent
        yield c
        c.execute("DROP SCHEMA IF EXISTS domain CASCADE")


def _job(c, job_id: str, source_hash: str = "a" * 64) -> None:
    c.execute(
        "INSERT INTO domain.jobs (job_id, tenant_cui, source_hash, period, status, body)"
        " VALUES (%s, '1000009', %s, '2026-09', 'ingested', '{}')",
        (job_id, source_hash),
    )


def test_same_source_twice_is_refused(conn):
    _job(conn, "job-1")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _job(conn, "job-2")


def test_package_written_once(conn):
    _job(conn, "job-1")
    sql = (
        "INSERT INTO domain.packages (export_key, job_id, module_id, bucket_key)"
        " VALUES ('intrare_factura_xml:job-1:1', 'job-1', 'intrare_factura_xml', 'k')"
    )
    conn.execute(sql)
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(sql)


def test_filing_closes_only_with_receipt(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO domain.filing_items (cui, period, filing_id, state)"
            " VALUES ('1000009', '2026-09', 'd300_platitor', 'filed')"
        )


def test_no_books_in_domain(conn):
    names = [
        r[0]
        for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'domain'"
        )
    ]
    assert names
    banned = ("journal", "ledger", "balanta", "trial", "plan_conturi", "chart")
    assert not [n for n in names if any(b in n for b in banned)]
