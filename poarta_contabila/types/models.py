"""Domain types (ARCHITECTURE.md §3). Enums mirror the Lane B catalogs;
``tests/test_catalog.py`` checks that they stay in sync."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from poarta_contabila.types.base import Closed, Cui, FiscalDate, Money, Period, Rate, Slug

PrimaryKind = Literal[
    "ubl_spv",
    "pdf",
    "xml",
    "jpeg",
    "png",
    "xls",
    "xlsx",
    "csv",
    "mt940",
    "sta",
    "eml",
    "msg",
    "unknown",
]

DocClass = Literal[
    "intrare",
    "iesire",
    "storn_intrare",
    "storn_iesire",
    "incasare",
    "plata",
    "extras",
    "stat_plata",
    "nota_interna",
    "nedefinit",
]

JobStatus = Literal[
    "ingested",
    "extracted",
    "bound",
    "reconcile_pre",
    "approved",
    "packaged",
    "wait_validare",
    "acked",
    "already_in_sink",
    "rejected",
    "failed",
    "needs_human",
    "reopened",
]


class TenantRef(Closed):
    cui: Cui
    punct: str = "default"
    saga_firm_folder: str


class SourceRef(Closed):
    kind: PrimaryKind
    bucket_key: str
    content_type: str
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class PartnerRef(Closed):
    cui: Cui | None
    name: str
    role: Literal["supplier", "customer", "both", "unknown"]
    saga_analytic: str | None = None


class Totals(Closed):
    net: Money
    vat: Money
    gross: Money


class Line(Closed):
    desc: str
    qty: str | None = None
    unit: str | None = None
    net: Money
    vat_rate: Rate | None = None
    vat: Money | None = None
    gross: Money
    account_hint: str | None = None


class CanonicalDocument(Closed):
    job_id: str
    tenant: TenantRef
    period: Period
    doc_class: DocClass
    number: str
    date: FiscalDate
    partner: PartnerRef
    currency: str = "RON"
    totals: Totals
    lines: list[Line]
    is_storno: bool = False
    storno_of: str | None = None
    source: SourceRef
    maps: dict[str, str] = Field(default_factory=dict)
    jev: dict[str, dict] = Field(default_factory=dict)
    schema_version: str = "1"


class JobRecord(Closed):
    job_id: str
    tenant: TenantRef
    period: Period
    status: JobStatus
    job_kind: Slug | None = None
    articol_id: Slug | None = None
    schema_version: str = "1"
    client_type_hash: str | None = None
    jev_annex_hash: str | None = None
    canonical_key: str | None = None
    export_key: str | None = None
    module_id: Slug | None = None
    saga: dict[str, str | bool | None] = Field(default_factory=dict)
    error: str | None = None


class ExpectedItem(Closed):
    job_id: str
    doc_class: DocClass
    number: str
    date: FiscalDate
    partner_cui: Cui | None
    gross: Money
    net: Money
    vat: Money
    analytic: str | None = None


class SinkDoc(Closed):
    saga_key: str
    doc_class: DocClass
    number: str
    date: FiscalDate
    partner_cui: Cui | None
    gross: Money
    net: Money
    vat: Money
    validated: bool
    analytic: str | None = None


class BucketRow(Closed):
    kind: Literal["expected", "explained_sink_only", "unexplained"]
    expected: ExpectedItem | None = None
    sink: SinkDoc | None = None
    rule_id: Slug | None = None
    delta_gross: Money


class AccountDelta(Closed):
    expected: Money
    sink: Money
    delta: Money


class PeriodDiff(Closed):
    cui: Cui
    period: Period
    outbound_holes: list[str] = Field(default_factory=list)
    inbound: list[BucketRow] = Field(default_factory=list)
    synthetic_delta: dict[str, AccountDelta] = Field(default_factory=dict)
    analytic_delta: dict[str, AccountDelta] = Field(default_factory=dict)
    material: bool = False
    blockers: list[str] = Field(default_factory=list)
    snapshot_id: str
    hard_failures: int = 0


class WriteModule(Closed):
    """A SAGA mouth row (catalog/30_cale/ARTICOLE_WRITE_MODULE_v1.yaml)."""

    module_id: Slug
    schema_version: str
    status: Literal["draft", "active", "deprecated", "yanked"]
    saga_path: Literal["import_xml", "import_dbf", "ui_agent"]
    validare: Literal["n_a", "human", "agent"]
    backup: Literal["none", "before_batch", "before_each"]
    hitl: Literal["never", "first_n", "always"]
    first_n: int | None = None
    max_docs_per_run: int
    fixture: str | None = None
    used_by_flux: list[Slug] = Field(default_factory=list)
    note: str | None = None
    approved_at: FiscalDate | None = None


class ControlRun(Closed):
    control_id: Slug
    status: Literal["PASS", "FAIL", "INFO"]
    target: Money | None = None
    actual: Money | None = None
    diff: Money | None = None


class FilingItem(Closed):
    filing_id: Slug
    period: Period
    state: Literal["open", "filed"] = "open"
    receipt_key: str | None = None
