"""Tenants and the files that witness their books (exports, SPV register).

A tenant row carries what the SAGA mouth needs (name, firm folder). An uploaded export
is parsed before it is kept: a file that does not read, or a SAGA export whose header
names another firm, is refused. PRE reads the latest journal export (with the latest
balance of the same product) and the latest SPV register.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field

from poarta_contabila.packages import BlobStore
from poarta_contabila.recon.pre import Witnesses
from poarta_contabila.sinks.exports import (
    ExportError,
    ExportEye,
    read_firm_cui,
    read_nextup_balanta,
    read_nextup_rj,
    read_saga_balanta,
    read_saga_rj,
)
from poarta_contabila.sinks.saga_eye import FakeSagaEye
from poarta_contabila.sinks.spv_register import read_spv_register, register_invoices
from poarta_contabila.types import Closed, Cui, JobRecord, Period, TenantRef

Product = Literal["saga", "nextup"]
ExportKind = Literal["rj", "balanta", "spv_register"]


class Tenant(Closed):
    cui: Cui
    name: str = Field(min_length=1)
    saga_firm_folder: str = Field(min_length=1)
    punct: str = "default"
    book_of_record: Product = "saga"

    def ref(self) -> TenantRef:
        return TenantRef(cui=self.cui, punct=self.punct, saga_firm_folder=self.saga_firm_folder)


class ExportRow(Closed):
    export_id: str
    tenant_cui: Cui
    product: Product | None
    kind: ExportKind
    bucket_key: str
    periods: list[Period] = Field(default_factory=list)
    uploaded_at: str


_READERS = {
    ("saga", "rj"): read_saga_rj,
    ("saga", "balanta"): read_saga_balanta,
    ("nextup", "rj"): read_nextup_rj,
    ("nextup", "balanta"): read_nextup_balanta,
}


def _with_file(data: bytes, filename: str, fn):
    suffix = Path(filename).suffix.lower()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(data)
        return fn(path)


def check_export(
    cui: str,
    product: Product | None,
    kind: ExportKind,
    data: bytes,
    filename: str,
    periods: Iterable[str] | None = None,
) -> list[str]:
    """Parse an upload; return the months it covers. Raises :class:`ExportError`."""
    if kind == "spv_register":
        _with_file(data, filename, read_spv_register)
        return sorted(set(periods or []))
    if product is None or (product, kind) not in _READERS:
        raise ExportError(f"unknown export {product}/{kind}")
    parsed = _with_file(data, filename, _READERS[(product, kind)])
    if product == "saga":
        firm = _with_file(data, filename, read_firm_cui)
        if firm != cui:
            raise ExportError(f"the export header names firm {firm}, not {cui}")
    if kind == "rj":
        found = {ln.date[:7] for ln in parsed}
        return sorted(set(periods) if periods else found)
    return sorted(set(periods or []))


@dataclass
class InMemoryRegistry:
    tenants: dict[str, Tenant] = field(default_factory=dict)
    exports: list[ExportRow] = field(default_factory=list)

    def put_tenant(self, tenant: Tenant) -> None:
        self.tenants[tenant.cui] = tenant

    def tenant(self, cui: str) -> Tenant | None:
        return self.tenants.get(cui)

    def add_export(self, row: ExportRow) -> None:
        if not any(e.export_id == row.export_id for e in self.exports):
            self.exports.append(row)

    def latest_export(self, cui: str, kind: str, product: str | None = None) -> ExportRow | None:
        rows = [
            e
            for e in self.exports
            if e.tenant_cui == cui and e.kind == kind and product in (None, e.product)
        ]
        return max(rows, key=lambda e: e.uploaded_at) if rows else None


class PostgresRegistry:
    """``domain.tenants`` and ``domain.sink_exports``."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        self._dsn, self._psycopg = dsn, psycopg

    def put_tenant(self, tenant: Tenant) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.tenants (cui, body) VALUES (%s, %s)"
                " ON CONFLICT (cui) DO UPDATE SET body = EXCLUDED.body, updated_at = now()",
                (tenant.cui, tenant.model_dump_json()),
            )

    def tenant(self, cui: str) -> Tenant | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute("SELECT body FROM domain.tenants WHERE cui = %s", (cui,)).fetchone()
        return Tenant.model_validate(row[0], strict=False) if row else None

    def add_export(self, row: ExportRow) -> None:
        with self._psycopg.connect(self._dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO domain.sink_exports (export_id, tenant_cui, kind, product, body)"
                " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (export_id) DO NOTHING",
                (row.export_id, row.tenant_cui, row.kind, row.product, row.model_dump_json()),
            )

    def latest_export(self, cui: str, kind: str, product: str | None = None) -> ExportRow | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                "SELECT body FROM domain.sink_exports WHERE tenant_cui = %s AND kind = %s"
                " AND (%s::text IS NULL OR product = %s)"
                " ORDER BY body->>'uploaded_at' DESC LIMIT 1",
                (cui, kind, product, product),
            ).fetchone()
        return ExportRow.model_validate(row[0], strict=False) if row else None


def export_row(
    cui: str,
    product: Product | None,
    kind: ExportKind,
    data: bytes,
    filename: str,
    periods: list[str],
    uploaded_at: str,
) -> ExportRow:
    digest = hashlib.sha256(data).hexdigest()
    suffix = Path(filename).suffix.lower()
    return ExportRow(
        export_id=f"{kind}:{digest}",
        tenant_cui=cui,
        product=product,
        kind=kind,
        bucket_key=f"tenants/{cui}/_sink/{kind}/{digest}{suffix}",
        periods=periods,
        uploaded_at=uploaded_at,
    )


def witnesses_provider(registry, blobs: BlobStore):
    """``Witnesses`` for a job's tenant, read fresh from the latest uploads."""

    def witnesses(job: JobRecord) -> Witnesses:
        cui = job.tenant.cui
        rj = registry.latest_export(cui, "rj")
        if rj is None:
            eye = FakeSagaEye()
        else:
            reader = _READERS[(rj.product, "rj")]
            lines = _with_file(blobs.get(rj.bucket_key), rj.bucket_key, reader)
            bal = registry.latest_export(cui, "balanta", rj.product)
            balance = (
                _with_file(
                    blobs.get(bal.bucket_key), bal.bucket_key, _READERS[(bal.product, "balanta")]
                )
                if bal
                else None
            )
            eye = ExportEye(
                product=rj.product, lines=lines, balance=balance, cui=cui, periods=rj.periods
            )
        reg = registry.latest_export(cui, "spv_register")
        register = []
        if reg is not None:
            rows = _with_file(blobs.get(reg.bucket_key), reg.bucket_key, read_spv_register)
            register = register_invoices(rows)
        return Witnesses(eye=eye, register=register)

    return witnesses
