"""The deterministic core: the code both runtimes share, re-exported behind one versioned name.

The module review's direction (repository ``MASTER_1WORKCLIENTx3SYSTEMCONTA``, approved by the
owner on 2026-10-14) keeps one deterministic core for PoartaContabila and DinamicaAgenti:
this package hosts it, the other pins it by tag instead of re-writing it. Until the core is
extracted into its own package (after the SAGA C loops), this module is its boundary:

- **Re-exports only.** Every name here is the very object of its home module; nothing is
  moved, copied or changed, and the runtime keeps importing from the home modules.
- **No runtime stack.** Importing the core pulls no graph, HTTP service, database driver or
  model client; stores (in memory or Postgres) stay with each runtime.
- **Versioned.** ``CORE_VERSION`` changes when an exported name or its behaviour changes; a
  release is tagged ``CORE_TAG`` (``core-v<version>``), the tag the other runtime pins.

``CORE_MODULES`` names, per shared-core module of the review's register (``core.*``), the home
modules it is drawn from. A name enters the core only from a declared home module.
"""

from __future__ import annotations

from poarta_contabila import synthetic
from poarta_contabila.catalog import (
    Catalog,
    CatalogError,
    UnknownArticol,
    UnknownHitlKind,
    load_catalog,
)
from poarta_contabila.codit import (
    AxisValue,
    Codit,
    CoditError,
    CoditInput,
    SoftFlag,
    V4Edit,
    next_period,
    seed_pins,
    v4_patch,
    v4_rules,
    v4_seed,
)
from poarta_contabila.extract.statement import (
    Statement,
    StatementError,
    StatementLine,
    StatementMeta,
    line_source_hash,
    parse_statement,
    statement_line_document,
)
from poarta_contabila.extract.ubl import (
    SpvZip,
    UblError,
    UblInvoice,
    UblLine,
    UblParty,
    UblSubtotal,
    line_vats,
    parse_ubl,
    read_spv_zip,
    to_canonical,
)
from poarta_contabila.filings import FilingView, books_gate, due_filings, views
from poarta_contabila.flux import MatchContext, match_articole
from poarta_contabila.packages import PackageRow, write_once
from poarta_contabila.period_diff import (
    ExpectedJob,
    bank_counterparts,
    build_period_diff,
    can_file,
    expected_turnover,
    open_4428,
    prefile_failures,
    standard_rate,
    vat_exigible,
)
from poarta_contabila.recon.numbers import match_level, normalize
from poarta_contabila.recon.post import (
    AccountAmount,
    PostResult,
    account_amounts,
    how_check,
    posting_lines,
)
from poarta_contabila.recon.pre import PreResult, Witnesses, check_profile, det_match, pre_profile
from poarta_contabila.recon.settle import (
    Candidate,
    CandidateGroup,
    InvoiceJob,
    SettlementProposal,
    name_in_text,
    number_in_text,
    propose_settlement,
    settle_key,
)
from poarta_contabila.rules import (
    ControlDispositionResume,
    DocumentMatch,
    ExplainedRule,
    ExplainedRuleResume,
    LineMatch,
    RuleBody,
    check_control_disposition,
    check_explained_rule,
    explained_turnover,
)
from poarta_contabila.sinks.exports import (
    BalanceRow,
    ExportError,
    SinkLine,
    read_firm_cui,
    read_nextup_balanta,
    read_nextup_rj,
    read_saga_balanta,
    read_saga_rj,
)
from poarta_contabila.sinks.saga_xml import (
    RenderedFile,
    SagaXmlError,
    export_key,
    is_bank_mouth,
    mouth_doc_class,
    packaged_number,
    render_bank_line,
    render_invoice,
)
from poarta_contabila.types import (
    AccountDelta,
    BucketRow,
    CanonicalDocument,
    Closed,
    ControlRun,
    Cui,
    DocClass,
    ExpectedItem,
    FilingItem,
    FiscalDate,
    JobRecord,
    JobStatus,
    Line,
    Money,
    PartnerRef,
    Period,
    PeriodDiff,
    PrimaryKind,
    Rate,
    SinkDoc,
    Slug,
    SourceRef,
    TenantRef,
    Totals,
    WriteModule,
    cui_is_valid,
    cui_key,
)

CORE_VERSION = "0.1.0"
CORE_TAG = f"core-v{CORE_VERSION}"

# The review register's shared-core modules (its §2) → their home modules here.
# core.calendar is WP-86; core.pins, core.provenance, core.tenancy and core.runs are law or
# runtime today and enter when they have deterministic code to share.
CORE_MODULES: dict[str, tuple[str, ...]] = {
    "core.types": ("poarta_contabila.types",),
    "core.catalog": ("poarta_contabila.catalog", "poarta_contabila.flux"),
    "core.readers": (
        "poarta_contabila.extract.ubl",
        "poarta_contabila.extract.statement",
        "poarta_contabila.sinks.exports",
    ),
    "core.render_saga": ("poarta_contabila.sinks.saga_xml", "poarta_contabila.packages"),
    "core.recon": (
        "poarta_contabila.recon.numbers",
        "poarta_contabila.recon.pre",
        "poarta_contabila.recon.post",
        "poarta_contabila.recon.settle",
    ),
    "core.controls": ("poarta_contabila.period_diff",),
    "core.rules": ("poarta_contabila.rules",),
    "core.codit": ("poarta_contabila.codit",),
    "core.filings": ("poarta_contabila.filings",),
    "core.synthetic": ("poarta_contabila.synthetic",),
}
CORE_MODULES_FLAT: tuple[str, ...] = tuple(m for ms in CORE_MODULES.values() for m in ms)

# The core's public names. CORE_VERSION, CORE_TAG and CORE_MODULES describe the core and are
# read by name; they are not part of it.
__all__ = [
    # core.types
    "AccountDelta",
    "BucketRow",
    "CanonicalDocument",
    "Closed",
    "ControlRun",
    "Cui",
    "DocClass",
    "ExpectedItem",
    "FilingItem",
    "FiscalDate",
    "JobRecord",
    "JobStatus",
    "Line",
    "Money",
    "PartnerRef",
    "Period",
    "PeriodDiff",
    "PrimaryKind",
    "Rate",
    "SinkDoc",
    "Slug",
    "SourceRef",
    "TenantRef",
    "Totals",
    "WriteModule",
    "cui_is_valid",
    "cui_key",
    # core.catalog
    "Catalog",
    "CatalogError",
    "MatchContext",
    "UnknownArticol",
    "UnknownHitlKind",
    "load_catalog",
    "match_articole",
    # core.readers
    "BalanceRow",
    "ExportError",
    "SinkLine",
    "SpvZip",
    "Statement",
    "StatementError",
    "StatementLine",
    "StatementMeta",
    "UblError",
    "UblInvoice",
    "UblLine",
    "UblParty",
    "UblSubtotal",
    "line_source_hash",
    "line_vats",
    "parse_statement",
    "parse_ubl",
    "read_firm_cui",
    "read_nextup_balanta",
    "read_nextup_rj",
    "read_saga_balanta",
    "read_saga_rj",
    "read_spv_zip",
    "statement_line_document",
    "to_canonical",
    # core.render_saga
    "PackageRow",
    "RenderedFile",
    "SagaXmlError",
    "export_key",
    "is_bank_mouth",
    "mouth_doc_class",
    "packaged_number",
    "render_bank_line",
    "render_invoice",
    "write_once",
    # core.recon
    "AccountAmount",
    "Candidate",
    "CandidateGroup",
    "InvoiceJob",
    "PostResult",
    "PreResult",
    "SettlementProposal",
    "Witnesses",
    "account_amounts",
    "check_profile",
    "det_match",
    "how_check",
    "match_level",
    "name_in_text",
    "normalize",
    "number_in_text",
    "posting_lines",
    "pre_profile",
    "propose_settlement",
    "settle_key",
    # core.controls
    "ExpectedJob",
    "bank_counterparts",
    "build_period_diff",
    "can_file",
    "expected_turnover",
    "open_4428",
    "prefile_failures",
    "standard_rate",
    "vat_exigible",
    # core.rules
    "ControlDispositionResume",
    "DocumentMatch",
    "ExplainedRule",
    "ExplainedRuleResume",
    "LineMatch",
    "RuleBody",
    "check_control_disposition",
    "check_explained_rule",
    "explained_turnover",
    # core.codit
    "AxisValue",
    "Codit",
    "CoditError",
    "CoditInput",
    "SoftFlag",
    "V4Edit",
    "next_period",
    "seed_pins",
    "v4_patch",
    "v4_rules",
    "v4_seed",
    # core.filings
    "FilingView",
    "books_gate",
    "due_filings",
    "views",
    # core.synthetic
    "synthetic",
]
