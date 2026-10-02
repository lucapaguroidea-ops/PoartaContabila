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
| WP-06R | done | WP-06 | Runtime: Postgres checkpointer, S3 bucket, tenants + witness uploads, operator API |
| WP-07 | done | WP-06 | intent_check against SagaEye v1 (report pack / RJ-CM) |
| WP-08 | done | WP-07 | ArticoleControls Layer 1 + PeriodDiff; `hard_failures` blocks package and file |
| WP-09 | done | WP-08 | `POST /rules` + HITL `explained_rule` + `control_disposition` |
| WP-10 | done | WP-09 | monthly_close + V2 pack; material cannot be cleared by Jev |
| WP-11 | done | WP-01 | CO.DiT seed from Pins + T* F* + additive axes; no silent `tva_platitor` |
| WP-12 | done | WP-10 | Filing items + `filing_receipt`; V2 `file` ≠ ANAF submit |
| WP-13 | done | WP-05 | `extras_statement_pdf` extract path (document_ai); no MT940-first |
| WP-14 | parked | — | ArticolBon / `bon_via_nota` |
| WP-15 | parked | — | FDB SQL SagaEye |
| WP-16 | parked | — | Agent Validare |
| WP-17 | parked | — | Engagement backlog / `chat:` face |
| WP-18 | parked | — | Take-on / year-end / D406 producer / FX engine |
| WP-D3 | decision | WP-11 | Non-payer RC books: 4423 vs 446x on copy-firm note |
| WP-19 | done | WP-13 | Bank mouths `incasare_xml` / `plata_xml` from the SAGA manual (R1) |
| WP-20 | in-progress | WP-10 | Jev Layer 1 `v3_judge` + Layer 2 `v2_declaration_gate`; wire waits on R2 |
| WP-21 | done | WP-13 | Statement PDFs read by Google Document AI into the extract contract |
| WP-22 | done | WP-19 | Bank line → the invoice it settles: a proposal on `v3_approve`, a person decides |

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
- Corrected 2026-10-02 from R1 (the manual's "Import date"): every tag written is quoted there, in
  its order. `FacturaCotaTVA` (not in the manual) is gone; `ProcTVA` on every line (a line without
  a rate is refused); `FacturaID` = the job id after `<Detalii>`, so a receipt or payment can name
  the invoice (WP-19). Both fixtures regenerated from the renderer.
- Open: the owner's copy-firm import of both fixtures (sync "Nr.+data"), and SAGA's own sample XML
  (Ieșiri → Tipărire → "Formular PDF" → `TEMP\Facturi`, invented data) to settle date and decimal
  formats and the `RO` prefix. `FacturaIndexSPV` waits for a source of the SPV upload index (the
  SPV zip reader and the register do not keep one).

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

### WP-06R Runtime
- `runtime.py` assembles stores, bucket, checkpointer, ingest graph and agent service;
  `runtime_from_env` needs `DATABASE_URL` + `S3_*` (else `/ready` names what is missing and the
  agent/operator routes answer 503). LangGraph threads live in Postgres (`PostgresSaver`).
- `registry.py`: tenants (`domain.tenants`) and uploaded witnesses (`domain.sink_exports`: SAGA /
  NextUp journal and balance, SPV register); a SAGA export naming another firm is refused. PRE
  reads the latest journal export (+ balance) and register per tenant.
- `operator_api.py` (bearer `OPERATOR_TOKEN`, must differ from the agent token):
  `PUT /tenants/{cui}`, `POST /tenants/{cui}/exports/{kind}`, `POST /ingest` (SPV zip or UBL XML
  only, XML first), `GET /jobs/{id}`, `POST /jobs/{id}/resume`.
- Open: Jev is wired only once its wire is read (WP-20); until then every document asks
  `v3_approve`. No triage of other sources over HTTP yet (PDF, receipts, statements, expense
  reports).

### WP-07 SagaEye v1
- Parse SAGA report pack / RJ-CM **headers only** first (harvest C-11). Column map lives in `sinks/saga_eye.py`, not in graph code.
- Tests: fixture export (synthetic) → SinkDoc list.
- Built: `read_saga_tva_journal` (purchase/sales journal → SinkDoc with partner CUI, net, VAT; rows
  must add up; column map `TVA_JOURNAL_COLUMNS` in `sinks/saga_eye.py`, `[de confirmat]` against a
  real report-pack export) and `ReportPackEye`; uploads `jurnal_cumparari` / `jurnal_vanzari`, which
  PRE prefers over the journal register. Ingest node `intent_check` after `wait_validare`: what SAGA
  shows (side, gross; net, VAT, partner CUI when the snapshot carries them) must equal the package,
  else `needs_human` with the differences (`acked` otherwise).
- Open: the report pack's other sheets (ledger, supplier situation, aging, fixed assets) are not read
  yet; the agent's snapshot must carry net/VAT/partner for the full intent check (gross is always
  checked).

### WP-08 Controls
- Implement `catalog/60_harvest/ARTICOLE_CONTROLS_v1.yaml`.
- `hard_failures > 0` ⇒ package refused and V2 `file` refused.
- Tests: unexplained inbound → file impossible; already_posted → no package.
- Built: `period_diff.py` — `build_period_diff` (buckets expected / unexplained, outbound holes,
  synthetic parity on the watched accounts from the turnover the expected documents imply:
  purchase 401 Cr gross + 4426 Dr VAT, sale 4111 Dr gross + 4427 Cr VAT), one `ControlRun` per
  catalog row, `can_file`; `prefile_failures` gates `package`; `SagaEye.turnover`; stored in
  `close_snapshots` / `control_runs`; operator `GET /periods/{cui}/{period}/diff`.
- Fail closed: a blocking control without the input it needs FAILs (TVA regime unknown until
  WP-11; 4428 open documents for TVA-la-încasare; a bank/cash movement with no source until WP-13).
  Expected postings other than invoices (reverse charge, 404/408, bank, cash) are not modelled yet,
  so they show as differences for a person, never as plugs.

### WP-09 Explained rules
- `POST /rules` versioned. HITL `explained_rule` and `control_disposition`.
- Tests: rule tags sink lines to `explained_sink_only`; cannot hide unexplained without `rule_id`.
- Built: `rules.py` — `RuleBody` (scope `document`: side / partner CUI / number prefix / gross
  ceiling; scope `line`: debit / credit account patterns, journal, words), `ExplainedRule`
  versions per `(cui, rule_id)` (same body = same version; `domain.explained_rules`), applied in
  `build_period_diff` (documents → `explained_sink_only` + `rule_id`; lines → explained turnover on
  the parity side, never a line of a document already counted). `POST /rules`, `GET /rules/{cui}`.
  Answer checks for `explained_rule` and `control_disposition` (used by the close graph, WP-10).

### WP-10 Close + V2
- Thread `close:{cui}:{period}`. Layer 2 JSON only.
- Tests: Jev action `file` with material=true is ignored.
- Built: `close.py` — `monthly_close` on `close:{cui}:{period}`: `lock_expected_set` (hash locked once
  per `(cui, period)` in `domain.close_runs`; a changed set is a lock mismatch, material until
  `reopen`), `period_diff` (Layer 1 with the tenant's eye and rules), `v2_gate` (Layer 2 must
  validate as `V2Gate` JSON or is ignored; its `file` on a material month is dropped; the person's
  `v2_close` cannot `file` while material, and an `explained_rule` named must exist), `v4_codit`
  after `file` (answer recorded). Close kind from the axes (unknown → material).
  Operator: `POST /close/{cui}/{period}`, `GET /close/{cui}/{period}`, `POST …/resume`.
- Open: Layer 2 is wired in WP-20 but sends nothing until its wire is read; the POST recon and Cartea Mare pull nodes are not
  separate yet (the period diff reads the latest uploaded books); V4 writes CO.DiT (WP-11).

### WP-11 CO.DiT
- Seed copies Pins. T1–T3 hard. New axes default null. Certainty required on write.
- Tests: neplătitor + exig încasare → ValidationError; empty profile is not platitor.
- Built: `codit.py` — `write_codit` (closed axis values; certainty on every axis written; exig
  default fills an omitted exig, and a defaulted one follows a new tva; hard T1–T3 then F5 F6 F1 F2
  F4 F3 raise `CoditError` and nothing is saved; soft F7.* / A* + `A_FLIP` / `A_CONTESTED` flags,
  `blocks_file` ones block the close), pins copied at seed, `derive()` (unset axes absent),
  `domain.codit`. The period diff, close and ingest take their axes from the period's CO.DiT
  (operator query axes only where no CO.DiT exists). `PUT/GET /codit/{cui}/{period}`; a filed
  period's CO.DiT is not rewritten.
- V4 (2026-10-02): after `file`, `skip` writes nothing; `accept` may patch the filed period's
  CO.DiT on `v4.may_patch` only (`edit`: `auto`, `saf_t`, `exig`; hard pairs run, nothing is saved
  on a refusal and the question is asked again) and seed the next period (`seed_next`): the
  profile carries forward whole, marked `seeded by V4 from <period>`, and only
  `v4.seed_next_period_on` (`impozit`, `tva`) may change at the boundary (a default `exig`
  follows a changed `tva`). An existing next CO.DiT is never overwritten; a replay of the
  same seed is a no-op. The CloseRun records `patched_hash` / `seeded_period`.
- Open: R1 (identity join) is enforced at triage, not here.

### WP-12 Filings
- Rows from `ARTICOLE_FILING_v1.yaml`. Receipt closes item.
- Tests: calendar date passing does not close; receipt does.
- Built: `filings.py` — due items from the ArticoleFiling rows that fit the period's CO.DiT (no
  CO.DiT → nothing assumed due), each with its `books_gate` (named controls' latest status) and due
  date `[de confirmat]` (legal.lock not pinned); `domain.filing_items` (+ `submitted_by`), filed only
  with a receipt (CHECK). Operator: `POST /filings/{cui}/{period}` opens, `GET` lists,
  `POST /filings/{cui}/{period}/{filing_id}/receipt` stores the receipt in the bucket and closes
  that item. A period with any receipt gets no new package (ingest gate).
- Open: due dates wait for `legal.lock`; nothing here submits to ANAF or builds a declaration.

### WP-13 Extras PDF
- Only after WP-05. Follow `EXTRACT.md` and `catalog/60_harvest/ARTICOLE_EXTRAS_GRAIN_v1.yaml`.
- Statement Pack + line Jobs. Do not match date+gross on one statement Job.
- Tests: extras without tenant identity do not emit; a two-line fixture mints two movement Jobs.
- Built: `extract/statement.py` — the extract contract's tables (`tables.json` from the backend) →
  movement lines, checked (one side per line, whole cents, opening − debits + credits = closing,
  holder CUI = tenant, RON only); `job_extras_line` (additive ArticoleJobs: one Job per line,
  `source_hash = sha256(statement_id:seq)`); each line Job carries an `incasare` / `plata` document
  with the bank side only (no counterparty guessed from text). SAGA / NextUp bank-journal entries
  are witness documents, so PRE finds lines already booked (date + amount + side) and the period
  diff matches them; expected lines count on 5121. A bank entry whose journal lines all fall under a
  line rule is `explained_sink_only`. Operator `POST /extras/{cui}` (PDF + tables + header).
- Open: Document AI reads the PDF since WP-21 (else the tables come with the upload); an unbooked
  line takes a bank mouth only once bound (WP-19), else it stops at `needs_human`; 5311 (cash)
  statements and foreign-currency accounts are not read.

### WP-19 Bank mouths
- Tags only from `RESEARCH_LOG.md` R1: receipts `I_<data>.xml` `<Incasari><Linie>`, payments
  `P_<data>.xml` `<Plati><Linie>`.
- Render the statement-line documents (`incasare` / `plata`, `extract/statement.py`) next to the
  invoice renderer in `sinks/saga_xml.py`; write once per `export_key`; the ingest `package`
  node uses these mouths instead of stopping at `needs_human`. Fixtures
  `fixtures/saga/incasare.xml` / `plata.xml` (synthetic). Modules stay `draft` until a green
  copy-firm import, which the owner does.
- Blocked 2026-10-01 (the manual's host was denied); unblocked 2026-10-02: R1 read from the
  owner's print of SAGA C's installed help.
- Built: `sinks/saga_xml.py` `render_bank_line` — one `<Linie>` per Job (`Data`, `Numar`, `Suma`,
  `Cont`, `Explicatie`, `FacturaID`?, `FacturaNumar`?, `CodFiscal`; optional tags only with a
  value; `ContClient` / `ContFurnizor` / `Moneda` not written). Poartă (decided by the owner
  2026-10-02): a line is packaged only with a partner CUI bound by a person, the invoice it
  settles (`maps.factura_id` = the invoice Job's `FacturaID`, or `maps.factura_numar`), and a
  class-5 treasury account for its IBAN (`Tenant.bank_accounts`, `PUT /tenants/{cui}`); fees,
  taxes, salaries, transfers and unknown payers stay `needs_human` (posted in SAGA). The
  `package` node picks the one declared mouth whose class is the document's; a `v3_approve`
  edit adds `maps` keys instead of dropping the statement's. `/agent/pull` holds a second file
  of the same name for the next run (two receipts of one day are both `I_<data>.xml`).
  Fixtures `incasare.xml` (settles `iesire.xml`, by `FacturaID`) and `plata.xml` (settles
  `intrare.xml`, by number), so one copy-firm session proves invoices and their settlement.
- `Numar` is the bank's reference (`maps.referinta`, from the statement's reference column) when
  no other line of the statement shares it, else the line's own number (`EXT-…`): with sync
  "Nr.+data" SAGA would skip a second document of the same number and date.
- Open: both modules `draft` until the owner's copy-firm import (`docs/COPY_FIRM_TEST.md`);
  nothing proposes the partner or the invoice (a person binds both).

### WP-20 Jev Layer 1 + Layer 2
- `v3_judge` → `IngestDeps.judge`; `v2_declaration_gate` → `CloseDeps.jev_v2`. JSON only,
  closed models, cache `{pack, input_hash}`, fail closed, Layer 2 never clears `material`.
  Env `JEV_BASE_URL` + `JEV_API_KEY`. Tests mock the transport.
- Built: `jev.py` — `V3Judge` (`accounts_ok`, `risk` low/medium/high, `needs_human`) and
  `V2Gate` (moved from `close.py`), strict validation of JSON text or objects (extra keys,
  coercion, off-list values refused); `Jev.ask` with the cache keyed on
  `sha256({pack, version, input})` (only validated answers stored; `domain.jev_answers`);
  errors, timeouts and invalid answers raise `JevError`. `make_judge` returns Jev's verdict or
  one that asks a person; `make_v2` gives a suggestion or none. The judge input is the document
  with its maps and the articol's accounts (no job id, bucket key or earlier answers); Layer 2
  gets the PeriodDiff and the period's CO.DiT axes. Ingest node `judge` and close node
  `layer2` checkpoint the answer before the question: `approve` / `v2_gate` re-run on resume,
  and a replayed call that answered differently would skip the question and drop the person's
  answer (test: a reject became `packaged`). On a material month Layer 2's `file`, a
  `gap_materiality` below material and `books_support_declaration: true` are dropped.
  `runtime_from_env` wires Jev when both env vars are set.
- Open: the HTTP wire (endpoint, auth, request/response, mapping of Jev's primitives onto the
  closed models) is not built: `docs.typesafe.ai` was denied by the build session's network
  policy (R2), so `http_transport` refuses every call and a person is asked. `JEV_*` are not
  set on Railway (the owner adds them). Layer 2 does not yet see the period's due filings.

### WP-21 Statement PDF reading backend
- Decided by the owner on 2026-10-01: Google Document AI. Write the extract contract
  (`normalized/tables.json` + `extract_meta.json`) and feed `parse_statement`.
- Built from the API's official Discovery document (RESEARCH_LOG.md R3):
  `extract/document_ai.py` — `DocumentAiReader` (`POST v1/{name}:process` on the processor's
  documented regional endpoint, `rawDocument` + `skipHumanReview`, bearer token for the
  `cloud-platform` scope from a service-account key or Application Default Credentials, built
  on first use and never echoed); `document.error`, a shard, an HTTP failure or an unknown
  location refuse. `tables_from_document`: cell text from `textAnchor` (content, else segments
  into `text`), spans laid out as an HTML table, multi-row headers labelled per column, a
  headerless table of the same width on the next page continues the previous one.
  `extract/contract.py` — `ExtractMeta`, the three `normalized/` files under
  `tenants/{cui}/{punct}/{period}/extras/source/{sha256}/`, written once per
  `(source_hash, backend)` (`domain.extracts`, + `prefix`), reused after (another tenant's
  extract is refused). `POST /extras/{cui}` without `tables` reads the PDF; the statement must
  show the tenant's CUI after `RO` or a fiscal-code label (`identity_ok`) and the header's
  IBAN; `parse_statement` then ties the lines to the typed header, so a misread cell refuses
  the statement. Tests mock the HTTP client.
- Open: no processor exists yet and `DOCUMENT_AI_PROCESSOR` /
  `DOCUMENT_AI_CREDENTIALS_JSON` are not set on Railway (the owner creates and adds them; an
  EU location keeps statements in the EU). Which processor type returns `pages[].tables` for
  these banks, and the CUI-label rule, are to be checked on real statements. The header (IBAN,
  holder, balances, date) is still typed by a person; reading it from the PDF is not built.

### WP-22 Settlement proposals for bank lines
- Asked by the owner 2026-10-02: a statement line names no partner, so WP-19 waits for a person
  to bind partner and invoice; propose them instead of leaving the person to search.
- Built: `recon/settle.py` `propose_settlement` — deterministic, no model. Candidates from the
  tenant's invoice Jobs (not rejected / failed) and the books' journals (covered months only), in
  the line's month and the two before (`runtime.SETTLE_MONTHS`): the settled side (receipt →
  sale, payment → purchase; no storno), the same gross to the cent, dated on or before the
  line, not already named by another bound bank line (`FacturaID`, or partner + number). Ranked
  by the bank description: invoice number as whole tokens (≥ 3 characters), then the partner's
  name without legal forms, then the amount alone; a Job outranks the books for one invoice
  (it carries `FacturaID`). `edit` (a ready `v3_approve` edit) only when one candidate leads
  alone, else a list of ≤ 5 and why. The `v3_approve` question of an unbound bank line carries
  it as `proposal`; a proposal that fails is left out, the question is asked all the same.
- Open: partial payments and one payment for several invoices get no candidate; the books'
  candidates carry no partner name (the journals' CUI only); the proposal is recomputed when
  the node re-enters on resume (reads the books again).

### WP-D3 Non-payer reverse charge books (`decision`)
- Ask: expected sink accounts for `foreign_rc_neplatitor` — harvest Y1 used 446x; some SAGA books use 4423.
- Until answered: articol exists, `expect_accounts: []`, `nota_nc_dbf` always-HITL, or SAGA-native + `explained_rule`.
- Do not silently fill 4423 or 446.

## Definition of done for v1

WP-00–WP-12 green. WP-13 optional. Parked WPs untouched. No `Journal.post` in the tree. No SYSDBA in env samples. Catalogs that shipped without fixtures remain `draft`.
