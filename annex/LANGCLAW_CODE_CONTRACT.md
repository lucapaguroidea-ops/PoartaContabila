# LangClaw Code Contract

**Status:** LOCKED — implement against this file.  
**Date:** 2026-09-29  
**Supersedes:** `GROK_BOT_BRIEF_RO_ACCOUNTING_LOOP.md` wherever it still assumes NextUp API, Ciel as sink, SAGA Web as primary, or LangClaw-as-ledger.  
**Gemini restatement** (`LangClaw Architectural Review.docx`) is commentary. On conflict, this contract wins.

Identifiers, type names, and env vars are English. Domain words stay Romanian.

---

## 0. One-sentence law

LangClaw is an operational hopper and a pre-filing gate.  
SAGA C is the only statutory mouth.  
Firebird FDB (read-only replica) is the only statutory eye.  
Nothing in LangClaw posts a *notă contabilă*.

---

## 1. Invariants (fail the build if violated)

1. No chart of accounts, journal, or 5-column trial balance is stored as a *ledger* in Postgres or Mongo. Mongo may store an **expected set** (document-derived totals) and **snapshots** of SAGA (witness copies).
2. No process in Railway holds `SYSDBA` or writes `INSERT`/`UPDATE`/`DELETE` on `CONT_BAZA.FDB`.
3. Posting = official SAGA path only: XML/DBF file → Import date → Validare. Agent UI may *drive that screen*. Agent UI may not invent ecrane. Direct FDB write = `FORBIDDEN_FDB`.
4. Conditional graph edges read only stored fields / Jev answers already on state. No LLM on an edge.
5. Jev is System One (choice / score / noul). Grok is System Two (explain, HITL). Grok never posts. RunPod runs only if Jev `needs_ocr` is true.
6. `interrupt()` resume re-enters the node from line 1. Side effects sit *after* the interrupt, guarded by Mongo idempotency.
7. One firm-period has one statutory sink: SAGA C. A second package (Ciel, Web) is not a second month.
8. Compensation is SAGA-shaped: Anulează importul | Devalidare | Stornare. Backup/restore is a *firm* net, not per-row rollback.
9. Month closed in SAGA ⇒ agent writes `0`.
10. `thread_id` prefixes: `job:` | `close:` | `chat:`. Never mix.

---

## 2. Topology

```
[sources] → Railway LangClaw (Python, LangGraph)
                ├─ Jev (typed packs)
                ├─ Grok (explain / HITL text)
                ├─ RunPod (OCR, gated)
                ├─ Mongo Atlas   domain
                ├─ Postgres      LangGraph checkpointer only
                └─ Railway Bucket (S3 API)  blobs
                         │
                         │ XML/DBF packages
                         ▼
              Windows VPS: SAGA C + Firebird service
                ├─ user SAGA  AGENT   (import / optional validare)
                ├─ user FDB   langclaw_ro  SELECT on replica
                └─ agent OS   pulls bucket, drives Import, posts snapshots
```

Railway never opens port 3050/3060/1433 on the public internet.

SAGA Web: out of scope until this contract is revised. Migration to Web *drops FDB*; do not design reads on Web API.

Ciel Focus: out of critical path. Optional local sandbox only.

---

## 3. Runtime identities

| Kind | Format | Example |
|---|---|---|
| Tenant | CUI 8 digits, no RO prefix in keys | `12345678` |
| Period | `YYYY-MM` | `2026-09` |
| Job | `job:{uuid}` | thread + Mongo `_id` space |
| Close thread | `close:{cui}:{yyyy-mm}` | one live close per firm-month |
| Chat thread | `chat:{user_id}` | never resumes a job |
| Object key | `tenants/{cui}/{punct}/{period}/{kind}/{jobId}/...` | bucket |
| Idempotency | `{cui}:{source_hash}` or `{cui}:{module_id}:{nr}:{data}` | Mongo unique |

`thread_id` length < 255 (PostgresSaver column).

---

## 4. Types (minimum; Pydantic in `langclaw_acct/types/`)

Money and fiscal dates are **strings** in graph state (`"1234.67"`, `"2026-09-15"`). Decimals live only inside compute nodes.

```python
class TenantRef(BaseModel):
    cui: str
    punct: str = "default"   # punct de lucru
    saga_firm_folder: str    # e.g. "0001"

class SourceRef(BaseModel):
    kind: Literal["pdf", "ubl", "photo", "email", "manual"]
    bucket_key: str
    content_type: str
    source_hash: str         # sha256 of bytes

class PartnerRef(BaseModel):
    cui: str | None
    name: str
    role: Literal["supplier", "customer", "both", "unknown"]
    saga_analytic: str | None   # "401.00012" after maps

class Line(BaseModel):
    desc: str
    qty: str | None
    unit: str | None
    net: str
    vat_rate: str | None
    vat: str | None
    gross: str
    account_hint: str | None

class CanonicalDocument(BaseModel):
    job_id: str
    tenant: TenantRef
    period: str
    doc_class: Literal[
        "intrare", "iesire", "storn_intrare", "storn_iesire",
        "incasare", "plata", "extras", "stat_plata",
        "nota_interna", "nedefinit"
    ]
    number: str
    date: str
    partner: PartnerRef
    currency: str = "RON"
    totals: dict             # net, vat, gross as strings
    lines: list[Line]
    is_storno: bool = False
    storno_of: str | None    # job_id or saga key
    source: SourceRef
    maps: dict = {}          # gestiune, jurnal, conturi, tva_incasare
    jev: dict = {}           # pack_name -> answer
    schema_version: str = "1"

class JobRecord(BaseModel):
    job_id: str
    tenant: TenantRef
    period: str
    status: Literal[
        "ingested", "extracted", "classified", "matched",
        "needs_human", "approved",
        "packaged", "staged", "acked", "rejected",
        "reopened", "failed"
    ]
    canonical_key: str | None
    export_key: str | None
    module_id: str | None
    saga: dict = {}          # {import_name, validated, saga_doc_key}
    error: str | None

class ExpectedItem(BaseModel):
    job_id: str
    doc_class: str
    number: str
    date: str
    partner_cui: str | None
    gross: str
    net: str
    vat: str
    analytic: str | None

class SinkDoc(BaseModel):
    saga_key: str
    doc_class: str
    number: str
    date: str
    partner_cui: str | None
    gross: str
    net: str
    vat: str
    validated: bool
    analytic: str | None

class BucketRow(BaseModel):
    kind: Literal["expected", "explained_sink_only", "unexplained"]
    expected: ExpectedItem | None
    sink: SinkDoc | None
    rule_id: str | None
    delta_gross: str

class PeriodDiff(BaseModel):
    cui: str
    period: str
    outbound_holes: list[str]      # job_ids staged or missing in sink
    inbound: list[BucketRow]
    synthetic_delta: dict          # account -> {expected, sink, delta}
    analytic_delta: dict           # "401.00012" -> {expected, sink, delta}
    material: bool
    blockers: list[str]
    snapshot_id: str

class WriteModule(BaseModel):
    module_id: str
    saga_path: Literal["import_xml", "import_dbf", "ui_screen", "FORBIDDEN_FDB"]
    input: str                     # which CanonicalDocument slice
    preconditions: list[str]
    hitl: Literal["always", "first_n", "never_if_risk_low"]
    first_n: int = 5
    backup: Literal["before_batch", "before_each", "none"]
    validare: Literal["human", "agent_if_approved", "never"]
    max_docs_per_run: int
    schema_version: str
    approved_by: str
    approved_at: str
```

`PeriodDiff` and `CanonicalDocument` in **checkpoint state** are allowed only as small DTOs or as Mongo ids (`canonical_key`, `diff_id`). Do not checkpoint raw PDF bytes.

---

## 5. Persistence

| Store | Holds | Does not hold |
|---|---|---|
| Mongo `jobs` | JobRecord | FDB rows |
| Mongo `canonical` | CanonicalDocument | | 
| Mongo `maps` | partner→analytic, nomenclator, gestiune | |
| Mongo `expected_sets` | lock per `{cui,period}` | |
| Mongo `explained_rules` | `{rule_id, match, account, note}` versioned | |
| Mongo `write_modules` | WriteModule catalog | |
| Mongo `close_snapshots` | FDB pull results + PeriodDiff | |
| Mongo `codit` | V4 vector after file | |
| Postgres checkpointer | graph cursor, interrupts | domain |
| Bucket | source bytes, XML packs, gbak labels metadata json | secrets |

Checkpointer: `langclaw[postgres]`, `AsyncPostgresSaver`, `.setup()` on boot.  
`LANGCLAW__CHECKPOINTER__BACKEND=postgres`

Domain Mongo is source of truth for status. After SAGA side effect: write Mongo *then* return from the node.

---

## 6. WriteModule catalog (initial)

Only these `module_id` values may run until a new row is HITL-approved and versioned.

| module_id | saga_path | validare | backup | hitl |
|---|---|---|---|---|
| `iesire_factura_xml` | import_xml | human | before_batch | first_n |
| `intrare_factura_xml` | import_xml | human | before_batch | first_n |
| `storno_iesire_xml` | import_xml | human | before_each | always |
| `storno_intrare_xml` | import_xml | human | before_each | always |
| `incasare_xml` | import_xml | human | before_batch | first_n |
| `plata_xml` | import_xml | human | before_batch | first_n |
| `parteneri_xml` | import_xml | n/a | before_batch | first_n |
| `articole_xml` | import_xml | n/a | before_batch | first_n |
| `nota_nc_dbf` | import_dbf | human | before_each | always |

`ui_screen` and `FORBIDDEN_FDB` exist as enum values so the type is closed. Shipping a module with those paths requires a contract amendment.

XML file names and tags follow SAGA manual (Facturi: `FurnizorCIF` → Ieșiri, `ClientCIF` → Intrări). Exporter lives in `langclaw_acct/sinks/saga_xml.py`. Do not guess extra tags; extend only from a successful import on a copy firm.

---

## 7. Document graph `ingest_source_doc`

Compiled `StateGraph`. Nodes are functions. Edges read `state`.

```
ingest
  → extract            # RunPod iff jev.needs_ocr else parse UBL/PDF text
  → v3_classify        # Jev pack v3_classify
  → match              # maps + partner/hash
  → v3_judge           # Jev pack v3_judge
  → checks             # totals, CUI, period open, duplicate source_hash
  → route_hitl         # edge: needs_human?
        → interrupt_approve     # kind=v3_approve
        → package               # WriteModule + XML to bucket, status=packaged
  → interrupt_wait     # kind=wait_validare   (agent or human Validare)
  → intent_check       # FDB snapshot vs canonical
  → v5_write           # job acked | reopened | failed
```

`package` does not talk to Firebird.  
`intent_check` does not import.  
`interrupt_approve` contains **no** SAGA call before `interrupt()`.

Job statuses move only forward except `reopened` after devalidare/storno decision.

---

## 8. Period graph `monthly_close`

Thread `close:{cui}:{yyyy-mm}`.

```
lock_expected_set      # freeze jobs in period with status in {acked} + packaged/staged as holes
  → pull_sink          # agent webhook or RO query result already in Mongo
  → period_diff        # Layer 1 deterministic → PeriodDiff
  → v2_gate            # Jev pack v2_declaration_gate on PeriodDiff + CO.DiT + due list
  → route_close
        file        → mark_fileable + v4_codit
        hold        → interrupt kind=v2_close
        patch_maps  → interrupt then maps node (no SAGA write)
        reopen      → interrupt; does not devalidate by itself
```

Layer 1 must set `material=true` on: outbound hole, unexplained inbound, synthetic |Δ| ≥ 0.01 RON on watched accounts, analytic |Δ| ≥ 0.01 after maps exist, period not open/lock mismatch.

Layer 2 cannot clear `material`. It can only choose among `hold | patch_maps | reopen` when material, or `file | hold` when not.

Buckets:

- `expected` — LangClaw sent, sink matches totals  
- `explained_sink_only` — `rule_id` versioned (payroll, TVA settlement, accountant reclass)  
- `unexplained` — blocks `file`

---

## 9. Jev packs (names frozen)

| pack | Inputs | Output shape |
|---|---|---|
| `v3_classify` | extract DTO + CO.DiT slice | `{doc_class, needs_ocr, needs_human, confidence}` |
| `v3_judge` | canonical + maps | `{accounts_ok, risk, needs_human}` |
| `v2_declaration_gate` | PeriodDiff + due[] + CO.DiT | `{books_support_declaration, gap_materiality, action}` |

Pack JSON only. No PDF. Cache by `{pack, input_hash}` in Mongo so interrupt replay does not rebill.

---

## 10. Interrupt kinds

| kind | thread | Resume payload |
|---|---|---|
| `v3_approve` | `job:` | `{decision: approve\|reject\|edit, patch?: {}}` |
| `wait_validare` | `job:` | `{validated: bool, saga_doc_key?: str}` |
| `v2_close` | `close:` | `{action: file\|hold\|patch_maps\|reopen}` |
| `request_devalidare` | `job:` | `{done: bool}` |
| `define_module` | `chat:` or ops | `{module_id, approved: bool}` |

Unknown kind = bug.

---

## 11. Windows agent contract

Process on the SAGA VPS. Outbound HTTPS to LangClaw + local SAGA + local backup.

```
LOOP
  GET /agent/pull?cui=
  if batch:
      POST /agent/ack-backup {batch_id, snapshot_label, sha}
      run SAGA as user AGENT:
          Import date ← folder from batch
          do not Validare unless module.validare == agent_if_approved
      POST /agent/imported {batch_id, files[], errors[]}
  if snapshot_request:
      read replica with langclaw_ro
      POST /agent/snapshot {cui, period, docs[], solduri[], captured_at}
```

SAGA user `AGENT`: add/import; no modify/delete/devalidare; no închidere lună; no user admin; firms = tenant allowlist.

Firebird user `langclaw_ro`: SELECT on replica produced by `nbackup`/`gbak`, not on the hot file while SAGA writes if that causes locks. Live SELECT is allowed only if proven safe on that VPS; default = replica.

Backup label: `{cui}.{period}.{batch_id}.{utc}` stored next to the backup file; metadata JSON also in bucket `backups/`.

Restore: human-only runbook. Agent must not auto-restore.

---

## 12. Compensation map

| SAGA fact | SAGA action | Job status |
|---|---|---|
| Imported, not validated | Anulează importul | `rejected` |
| Validated, not in SPV | Devalidare (+ delete if needed) by human | `reopened` |
| In SPV / e-Factura | Stornare + Reglare stornare | new job `is_storno=True` |
| Lot corrupt, ops panic | Restore labeled snapshot (firm-wide) | all jobs after label → `reopened` or `failed` per runbook |

Agent never devalidates.

---

## 13. FDB read surface (v1)

Do not bake table names into LangClaw core until a `saga_fdb` adapter is calibrated on a copy of `CONT_BAZA` for a pinned SAGA C build.

Adapter interface:

```python
class SagaEye(Protocol):
    def documents(self, cui: str, period: str) -> list[SinkDoc]: ...
    def solduri(self, cui: str, period: str) -> dict[str, dict]: ...
    def analytic(self, cui: str, period: str, root: str) -> dict[str, dict]: ...
```

Implementation 1: SQL against replica (table map in `sinks/saga_fdb/{build}/`).  
Implementation 2: agent-computed JSON (same DTO).

Core graphs depend only on `SagaEye`.

Watched synthetic accounts for Layer 1 v1: `401`, `4111`, `4426`, `4427`, `4428`, `5121`, `5311`. Extend by config, not by prompt.

---

## 14. HTTP surface (Railway)

| Method | Path | Role |
|---|---|---|
| POST | `/ingest` | new source → start document graph |
| GET | `/jobs/{id}` | status |
| POST | `/jobs/{id}/resume` | `Command(resume=)` |
| GET | `/close/{cui}/{period}` | PeriodDiff + gate |
| POST | `/close/{cui}/{period}/resume` | close interrupt |
| GET | `/agent/pull` | agent |
| POST | `/agent/imported` | agent |
| POST | `/agent/snapshot` | agent |
| POST | `/agent/ack-backup` | agent |
| POST | `/maps` | accountant patch (authz) |
| POST | `/rules` | explained_sink_only rules |

Auth: service token for agent; user session for HITL. Agent token ≠ Grok token.

---

## 15. Package layout

```
langclaw_acct/
  types/
  graphs/
    document.py
    period.py
  jev/
    packs/v3_classify.json
    packs/v3_judge.json
    packs/v2_declaration_gate.json
    client.py
  sinks/
    saga_xml.py
    saga_eye.py
    saga_fdb/          # build-pinned SQL, optional
  agent_api.py
  maps.py
  period_diff.py       # Layer 1 only
  idempotency.py
```

LangClaw app wires tools to these graphs. No ReAct supervisor tool that can call `saga_xml.emit` on a whim.

---

## 16. Env (production)

```
LANGCLAW__CHECKPOINTER__BACKEND=postgres
LANGCLAW__CHECKPOINTER__POSTGRES__DSN=
MONGODB_URI=
S3_ENDPOINT=          # Railway Bucket
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_BUCKET=
JEV_BASE_URL=
JEV_API_KEY=
GROK_API_KEY=
RUNPOD_API_KEY=
AGENT_SHARED_TOKEN=
```

Not present: `SAGA_SYSDBA`, `FIREBIRD_PASSWORD` write user, `CIEL_SA`, `NEXTUP_*`.

---

## 17. Tests that must exist before a module is “live”

1. Duplicate `source_hash` → second job does not package.  
2. `interrupt` resume → XML written once (fake agent).  
3. `wait_validare` resume without snapshot → not `acked`.  
4. PeriodDiff unexplained → `file` impossible even if Jev says yes.  
5. Storno job carries `is_storno` and `storno_of`.  
6. Checkpointer MemorySaver in CI; Postgres in staging.  
7. XML fixture imports into a **copy** SAGA firm (manual or agent) at least once per `module_id`.

---

## 18. Implementation order

1. Types + Mongo indexes + fake `SagaEye`.  
2. `saga_xml` + fixture zip + human import on copy firm.  
3. Document graph through `packaged` + interrupts.  
4. Agent pull/import/snapshot on VPS.  
5. `intent_check` + Layer 1 PeriodDiff.  
6. Period graph + V2 pack.  
7. Catalog expansion only after 4+5 are green.

No WriteModule with `ui_screen` or `FORBIDDEN_FDB` in this order.

---

## 19. Amendment rule

Changing: sink product, FDB write policy, graph topology, interrupt kinds, or watched accounts  
requires a new dated section in this file and a bump of `schema_version` on affected types.

A Telegram message is not an amendment.


<!-- ANNEX. Not source of truth. Kept so nothing is lost. SoT is /INDEX.md + /catalog. -->
