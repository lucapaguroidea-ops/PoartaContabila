# BUILD — work packages

One WP per change. Status: `todo` | `in-progress` | `done` | `n-a` | `parked`.  
Depends must be done. `decision` WPs need a human before code.

Law values in tests are synthetic. Invented CUIs must pass the checksum if you validate checksums.

## Sequence

| id | status | depends | title |
|---|---|---|---|
| WP-00 | done | — | Scaffold `poarta_contabila` types + Postgres domain schema + fake SagaEye |
| WP-01 | done | WP-00 | Load Lane B YAML; fail closed on unknown articol / HITL kind |
| WP-02 | done | WP-01 | folder_triage + SourceDoc emit gates + Job unique `(cui, source_hash)` |
| WP-03 | in-progress | WP-02 | `iesire_factura_xml` + `intrare_factura_xml` fixtures; human import on copy firm |
| WP-04 | done | WP-03 | ingest graph through `packaged` + `v3_approve` interrupt (no SAGA before interrupt) |
| WP-05 | done | WP-04 | PRE recon: RJ or SPV register already has the doc → `already_in_sink`, no package |
| WP-06 | done | WP-03 | Windows agent pull / backup label / Import / `wait_validare` human |
| WP-07 | todo | WP-06 | intent_check against SagaEye v1 (report pack / RJ-CM) |
| WP-08 | todo | WP-07 | ArticoleControls Layer 1 + PeriodDiff; `hard_failures` blocks package and file |
| WP-09 | todo | WP-08 | `POST /rules` + HITL `explained_rule` + `control_disposition` |
| WP-10 | todo | WP-09 | monthly_close + V2 pack; material cannot be cleared by Jev |
| WP-11 | todo | WP-01 | CO.DiT seed from Pins + T* F* + additive axes; no silent `tva_platitor` |
| WP-12 | todo | WP-10 | Filing items + `filing_receipt`; V2 `file` ≠ ANAF submit |
| WP-13 | todo | WP-05 | `extras_statement_pdf` extract path (document_ai); no MT940-first |
| WP-14 | parked | — | ArticolBon / `bon_via_nota` |
| WP-15 | parked | — | FDB SQL SagaEye |
| WP-16 | parked | — | Agent Validare |
| WP-17 | parked | — | Engagement backlog / `chat:` face |
| WP-18 | parked | — | Take-on / year-end / D406 producer / FX engine |
| WP-D3 | decision | WP-11 | Non-payer RC books: 4423 vs 446x on copy-firm note |

## WP details

### WP-00 Scaffold
- Build: `poarta_contabila/types/` from ARCHITECTURE.md §3. Checkpointer MemorySaver in tests.
- Fake `SagaEye` returns empty lists.
- Tests: models reject extra keys; money fields are str.

### WP-01 Catalog loader
- Load every YAML under `catalog/` including `60_harvest` additive files (merge by catalog name).
- Unknown `articol_id` / HITL kind → error, not skip.
- Tests: load fixture pack; `define_articol` with invented id fails.

### WP-02 Triage + emit
- Implement class / identity / primary gates from SourceDoc + json-logic in `fixtures/architecture.jsonlogic.json`.
- Unique Job index `(tenant_cui, source_hash)`.
- Tests: PDF-only RO e-Factura does not emit; duplicate hash does not create a second job.

### WP-03 Invoice XML mouths
- Exporter in `sinks/saga_xml.py`. Tags only from a successful copy-firm import.
- Record `fixture:` path and `approved_at` on the module row after human green. Still `status: draft` until that happens; then `active`.
- Tests: XML well-formed; FurnizorCIF/ClientCIF routing documented in a unit test with synthetic CUIs.

### WP-04 Ingest to packaged
- Nodes as ARCHITECTURE.md §2. Jev mocked in tests.
- `v3_approve` at top of node; package after resume; idempotent `export_key`.
- Tests: resume writes XML once; reject does not package.

### WP-05 PRE recon + SPV
- Profiles from `ARTICOLE_RECONCILE_v1.yaml`.
- `spv_register` SourceDoc additive feeds expected keys.
- Tests: matching number+date in sink_lines → `already_in_sink`.
- Built: `recon/pre.py` (`make_pre_check` → `IngestDeps.pre_check`; profile by flux on stage `pre`;
  verdict stored once per `(job_id, pre, sink_snapshot_id)`), `recon/numbers.py` (`number_match`
  ladder exact → alnum → digits_core, `[de confirmat]` on the profile), `sinks/spv_register.py`
  (C-F12 register, checked), `SagaEye.covers` (absent only for months whose books were read).
- Open: `recon_ambiguous` / `need_rj_export` answers live on the `reconcile_sink` graph (not built);
  until then such jobs stop at `needs_human` with the reason. Storno has no PRE row in the catalog,
  so every storno asks. Register partners match by name only (it carries no CUI).

### WP-06 Agent
- HTTP as ARCHITECTURE.md §10. AGENT user cannot devalidate.
- Tests: fake agent; `wait_validare` without snapshot ≠ acked.
- Built: `agent.py` (`AgentService`: pull per firm folder within `max_docs_per_run`, backup
  label `{cui}:{folder}:{utc}` acknowledged per tenant, import report → `wait_validare` or
  `needs_human`, snapshot → resumes `wait_validare` with the SAGA key of the matching validated
  document; closed months held), `agent_api.py` (bearer `AGENT_SHARED_TOKEN`, 503 when unset),
  ingest node `wait_validare` (`acked` only with a key a stored snapshot shows validated;
  `validated: false` → `reopened`), `domain.agent_backups` / `domain.agent_snapshots`.
- Open: the production runtime (Postgres checkpointer, S3 blob store, ingest runner) is not wired,
  so the deployed agent routes answer 503 until it is. The Windows agent program itself is not in
  this repo. A snapshot that stops showing an acked document is reported (`acked_not_shown`),
  never acted on; `request_devalidare` stays a person's step.

### WP-07 SagaEye v1
- Parse SAGA report pack / RJ-CM **headers only** first (harvest C-11). Column map lives in `sinks/saga_eye.py`, not in graph code.
- Tests: fixture export (synthetic) → SinkDoc list.

### WP-08 Controls
- Implement `catalog/60_harvest/ARTICOLE_CONTROLS_v1.yaml`.
- `hard_failures > 0` ⇒ package refused and V2 `file` refused.
- Tests: unexplained inbound → file impossible; already_posted → no package.

### WP-09 Explained rules
- `POST /rules` versioned. HITL `explained_rule` and `control_disposition`.
- Tests: rule tags sink lines to `explained_sink_only`; cannot hide unexplained without `rule_id`.

### WP-10 Close + V2
- Thread `close:{cui}:{period}`. Layer 2 JSON only.
- Tests: Jev action `file` with material=true is ignored.

### WP-11 CO.DiT
- Seed copies Pins. T1–T3 hard. New axes default null. Certainty required on write.
- Tests: neplătitor + exig încasare → ValidationError; empty profile is not platitor.

### WP-12 Filings
- Rows from `ARTICOLE_FILING_v1.yaml`. Receipt closes item.
- Tests: calendar date passing does not close; receipt does.

### WP-13 Extras PDF
- Only after WP-05. Follow `EXTRACT.md` and `catalog/60_harvest/ARTICOLE_EXTRAS_GRAIN_v1.yaml`.
- Statement Pack + line Jobs. Do not match date+gross on one statement Job.
- Tests: extras without tenant identity do not emit; a two-line fixture mints two movement Jobs.

### WP-D3 Non-payer reverse charge books (`decision`)
- Ask: expected sink accounts for `foreign_rc_neplatitor` — harvest Y1 used 446x; some SAGA books use 4423.
- Until answered: articol exists, `expect_accounts: []`, `nota_nc_dbf` always-HITL, or SAGA-native + `explained_rule`.
- Do not silently fill 4423 or 446.

## Definition of done for v1

WP-00–WP-12 green. WP-13 optional. Parked WPs untouched. No `Journal.post` in the tree. No SYSDBA in env samples. Catalogs that shipped without fixtures remain `draft`.
