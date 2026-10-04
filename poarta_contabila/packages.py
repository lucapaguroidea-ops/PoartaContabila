"""PreFile output: XML/DBF packages written once per ``export_key`` (ARCHITECTURE.md §16).

The blob (bytes) goes to a BlobStore under the bucket key; the row in the package
store is the proof it was written. A replay checks the row first and writes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class BlobStore(Protocol):
    def put(self, key: str, data: bytes) -> None: ...

    def get(self, key: str) -> bytes: ...


@dataclass
class InMemoryBlobStore:
    data: dict[str, bytes] = field(default_factory=dict)
    puts: int = 0

    def put(self, key: str, data: bytes) -> None:
        self.puts += 1
        self.data[key] = data

    def get(self, key: str) -> bytes:
        return self.data[key]


@dataclass(frozen=True)
class PackageRow:
    export_key: str
    job_id: str
    module_id: str
    bucket_key: str


class PackageStore(Protocol):
    def get(self, export_key: str) -> PackageRow | None: ...

    def for_job(self, job_id: str) -> list[PackageRow]: ...

    def add(self, row: PackageRow) -> bool: ...


@dataclass
class InMemoryPackageStore:
    rows: dict[str, PackageRow] = field(default_factory=dict)

    def get(self, export_key: str) -> PackageRow | None:
        return self.rows.get(export_key)

    def for_job(self, job_id: str) -> list[PackageRow]:
        return [r for r in self.rows.values() if r.job_id == job_id]

    def add(self, row: PackageRow) -> bool:
        if row.export_key in self.rows:
            return False
        self.rows[row.export_key] = row
        return True


class PostgresPackageStore:
    """Rows in ``domain.packages``; the primary key on export_key is the write-once lock."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def get(self, export_key: str) -> PackageRow | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT export_key, job_id, module_id, bucket_key FROM domain.packages"
                " WHERE export_key = %s",
                (export_key,),
            ).fetchone()
        return PackageRow(*row) if row else None

    def for_job(self, job_id: str) -> list[PackageRow]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                "SELECT export_key, job_id, module_id, bucket_key FROM domain.packages"
                " WHERE job_id = %s ORDER BY export_key",
                (job_id,),
            ).fetchall()
        return [PackageRow(*r) for r in rows]

    def add(self, row: PackageRow) -> bool:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            done = conn.execute(
                "INSERT INTO domain.packages (export_key, job_id, module_id, bucket_key)"
                " VALUES (%s, %s, %s, %s) ON CONFLICT (export_key) DO NOTHING RETURNING 1",
                (row.export_key, row.job_id, row.module_id, row.bucket_key),
            ).fetchone()
        return done is not None


def write_once(
    packages: PackageStore, blobs: BlobStore, row: PackageRow, data: bytes
) -> PackageRow:
    """Write *data* for *row* unless its export_key already exists; return the stored row."""
    existing = packages.get(row.export_key)
    if existing is not None:
        return existing
    blobs.put(row.bucket_key, data)
    packages.add(row)
    return packages.get(row.export_key) or row
