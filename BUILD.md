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
| WP-20 | in-progress | WP-10 | Jev Layer 1 `v3_judge` + Layer 2 `v2_declaration_gate`; R2 read, live sender not built |
| WP-21 | done | WP-13 | Statement PDFs read by Google Document AI into the extract contract |
| WP-22 | done | WP-19 | Bank line → the invoice it settles: a proposal on `v3_approve`, a person decides |
| WP-23 | done | WP-05 | `reconcile_sink` graph, PRE stage: `need_rj_export`, `recon_ambiguous`, review contest |
| WP-24 | done | WP-20 | Model roles: one pinned model per role, synthetic-only guard, dry-run trace |
| WP-25 | done | WP-24 | Role cards: what each role is told, checked, hashed into the cache key |
| WP-26 | done | WP-25 | Shadow roles: every model role observed at its place in the flow (dry) |
| WP-27 | done | WP-23 | `reconcile_sink` POST stage: how SAGA posted an acked document (`recon_how_mismatch`) |
| WP-28 | done | WP-06R | Expense reports over HTTP: `folder_triage` splits the container, a person names the parts |
| WP-29 | done | WP-28 | Synthetic smoke run: one invented firm through every graph over HTTP, model calls by place |
| WP-30 | done | WP-22 | Settlement proposals for partial payments, part-paid invoices and one payment for several |
| WP-31 | done | WP-27 | POST stage compares the amounts on the partner and VAT accounts with the document |
| WP-32 | done | WP-26 | `sys2_draft_rule` in shadow at `monthly_close.v2_gate`: every model role has a call site |
| WP-33 | done | WP-06R | Answer log: every answer a person submits, its outcome and its author, append-only |
| WP-34 | done | WP-06R | Request bodies capped (413, `MAX_UPLOAD_MB`); `/ready` reports weak or shared tokens |
| WP-35 | done | WP-24 | `eu_route` is a checked structure: provider, EU region, exact model, credential variables |
| WP-36 | done | WP-21, WP-24 | Gemini reads synthetic statement PDFs directly through Google AI Studio (live sender) |
| WP-37 | done | WP-36 | Reading evaluation: six known synthetic statements, scored per model |
| WP-38 | done | WP-34 | Token names `GRAPHUSERTOKEN_*`; the build agent's token, synthetic tenants only |
| WP-39 | done | WP-36 | Gemini reader asks again when Google is busy (500/503/504), three tries at most |
| WP-40 | done | WP-39 | Free-tier rate limits in the catalog; one backup model while the main one is at its limit |

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
- Open: `recon_ambiguous` / `need_rj_export` are answered on the `reconcile_sink` graph (WP-23).
  Storno has no PRE row in the catalog, so every storno asks. Register partners match by name only
  (it carries no CUI).

### WP-06 Agent
- HTTP as ARCHITECTURE.md §10. AGENT user cannot devalidate.
- Tests: fake agent; `wait_validare` without snapshot ≠ acked.
- Built: `agent.py` (`AgentService`: pull per firm folder within `max_docs_per_run`, backup
  label `{cui}:{folder}:{utc}` acknowledged per tenant, import report → `wait_validare` or
  `needs_human`, snapshot → resumes `wait_validare` with the SAGA key of the matching validated
  document; closed months held), `agent_api.py` (bearer `GRAPHUSERTOKEN_AGENT_SHARED`, 503 when unset),
  ingest node `wait_validare` (`acked` only with a key a stored snapshot shows validated;
  `validated: false` → `reopened`), `domain.agent_backups` / `domain.agent_snapshots`.
- Open: the agent routes answer 503 only while the runtime's variables are unset (`/ready` says
  which; the runtime itself is WP-06R). The Windows agent program itself is not in this repo. A snapshot that stops showing an acked document is reported (`acked_not_shown`),
  never acted on; `request_devalidare` stays a person's step.

### WP-06R Runtime
- `runtime.py` assembles stores, bucket, checkpointer, ingest graph and agent service;
  `runtime_from_env` needs `DATABASE_URL` + `S3_*` (else `/ready` names what is missing and the
  agent/operator routes answer 503). LangGraph threads live in Postgres (`PostgresSaver`).
- `registry.py`: tenants (`domain.tenants`) and uploaded witnesses (`domain.sink_exports`: SAGA /
  NextUp journal and balance, SPV register); a SAGA export naming another firm is refused. PRE
  reads the latest journal export (+ balance) and register per tenant.
- `operator_api.py` (bearer `GRAPHUSERTOKEN_OPERATOR`, must differ from the agent token):
  `PUT /tenants/{cui}`, `POST /tenants/{cui}/exports/{kind}`, `POST /ingest` (SPV zip or UBL XML
  only, XML first), `GET /jobs/{id}`, `POST /jobs/{id}/resume`.
- Open: Jev sends nothing until its live sender exists (WP-20, WP-24), so every document asks
  `v3_approve`; `MODEL_CALLS=dry` records what it would be sent. Over HTTP: SPV / UBL invoices,
  bank statements (WP-13), expense reports as containers (WP-28); not receipts or other PDFs.

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
- 2026-10-02 (R1: SAGA books TVA la încasare on `4428.TP` / `4428.TI`): the journal export's
  invoice VAT is read through the synthetic account, so VAT on `4428.TP` / `4428.TI` (or any
  `4426.x` / `4427.x`) counts. Open: the expected set still books invoice VAT on 4426 / 4427;
  under `exig = tva_la_incasare` SAGA books it on 4428 and moves it at payment, so parity shows
  those as differences for a person, and `M1_8_4428_open` fails closed (it needs the journals'
  neexigible VAT, whose export columns are `[de confirmat]`). Both wait on the copy-firm notes.

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
- Open: Layer 2 sends nothing until Jev's live sender exists (WP-20, WP-24). The POST recon runs
  on `reconcile_sink` (WP-27) and the close is material while it is open; there is no separate
  Cartea Mare pull node (the period diff reads the latest uploaded books). V4 writes CO.DiT
  (WP-11).

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
- Open: both modules `draft` until the owner's copy-firm import (`docs/COPY_FIRM_TEST.md`); the
  partner and invoice are proposed on `v3_approve` (WP-22) but a person binds them.

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
- Open: the HTTP wire is documented since 2026-10-02 (R2, read from the vendor's own SDK
  `typesafe-sdk` 0.7.2: `POST /v1/systemone`, bearer key, Noul / Choice questions, the mapping
  onto `V3Judge` / `V2Gate` with fail-closed thresholds) but **not built**: the build session was
  not permitted to write the outbound call, so `http_transport` still refuses every call and a
  person is asked. The owner chose to build it outside that session. `JEV_*` are not set on
  Railway (the owner adds them). Layer 2 sees the period's due filings (`filings_due`: id +
  books_gate, from the CO.DiT axes) since 2026-10-02.

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
- Synthetic tenants: Gemini direct reads instead when wired (WP-36).
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
- Open: partial payments and one payment for several invoices: WP-30. The books' candidates
  carry no partner name (the journals' CUI only); the proposal is recomputed when the node
  re-enters on resume (reads the books again).

### WP-23 reconcile_sink, PRE stage
- Asked by the owner 2026-10-02: the fourth graph (ARCHITECTURE §2), so a person can answer the
  PRE checks ingest cannot decide.
- Built: `reconcile.py` — `build_reconcile_graph` on `recon:{cui}:{period}` (other threads
  refused): `load_window` → `ask` → `apply` → `load_window` …, one question per pass of the loop.
  `load_window` takes the period's jobs whose ingest thread ended at an `ambiguous` PRE
  (`Runtime.recon_waiting`) and runs `det_match` again on the books as they are now; a
  decisive verdict goes back to its job by itself unless the review contests it. The question
  is stored on the thread before it is asked: `need_rj_export` (all missing months at once;
  the answer is the `export_id` of the tenant's latest journal upload covering one of them)
  before `recon_review_contest` before `recon_ambiguous` (oldest document first; the sink
  documents shown by index; `already_posted` names at least one, `override_absent` none).
  `apply` stores the person's verdict beside the det one (`{snapshot}:person`) and hands it
  back by job id (`Runtime._settle_pre`): `already_posted` → `already_in_sink`; `absent` → the
  ingest thread goes on from `reconcile_pre` to `judge` / `v3_approve`. `absent` is never
  concluded for an uncovered month. `llm_review` is the `ReconDeps.review` hook, `abstain`
  until a reviewer is wired; a contest only asks (it cannot flip to posted). `PreResult.missing`
  names the uncovered months. Operator: `POST /recon/{cui}/{period}`, `GET`, `POST …/resume`.
- 2026-10-02: `monthly_close` locks a month with documents still waiting on a PRE answer as
  material (blocker `reconcile_sink: n document(s) wait on a PRE answer`, `CloseDeps.recon_open`):
  answered on the recon thread, never closed around.
- Open: the review goes through the `jev_recon_review` role (WP-24), which sends nothing until
  the live sender exists. POST stage: WP-27.

### WP-24 Model roles (00_LAW §3.5, changed by the owner 2026-10-02)
- Decided by the owner 2026-10-02: Jev = System One (routing, classification of JSON /
  normalized data); DeepSeek / GLM = System Two (explain, draft); Gemini = document reading; all
  through OpenRouter with an exact model per role; synthetic tenants only until the EU host
  (Scaleway). Grok and RunPod are gone from the law.
- Built: `catalog/50_control/ARTICOLE_MODEL_ROLES_v1.yaml` (13 roles over the four graphs: node,
  system, family, pack or annex decision, HITL kinds, output, `wired` / `not_wired`, `model`,
  provider pin `{only, allow_fallbacks: false, data_collection: deny}`, `eu_route`), loaded and
  checked by `catalog.py` (`model_roles.load_roles`: exact ids only — no alias / `openrouter/auto`
  / `:free`, no fallback list, family fits the system, a wired role names its pack; graph, HITL
  kinds and JevAnnex decisions resolve). `model_roles.py`: `route_check` (calls off, no model, a
  client tenant off the EU route → `RouteRefused`), `ModelCall` records, `domain.model_calls`.
  `Tenant.data_class` (`synthetic` | `client`, default client). `jev.role_transport`:
  `MODEL_CALLS=dry` records exactly what a role would be sent and sends nothing, then fails
  closed (a person is asked); refusals are recorded with the reason. Pack `recon_review` and
  `make_recon_review` wire `reconcile_sink`'s review hook through the `jev_recon_review` role.
  Operator `GET /model-roles` (roles, pinned model, key set or not — never the value),
  `GET /model-calls?role=`.
- Open: every `model:` is null until the owner sends the ids (`docs/OWNER_CHECKLIST.md`); the
  live sender is not built (this session was not permitted to write the outbound call); the
  `shadow` roles (WP-26) record at their place but none has a sender either.
  EU route: `docs/EU_VERTEX_SETUP.md` (Gemini on Vertex AI EU, a draft blocked on the owner's
  EU-route decision: `00_LAW.md` names Scaleway only).

### WP-25 Role cards
- Asked by the owner 2026-10-02: a card per role instead of a persona — who reads, what to do,
  what never to do, in which shape.
- Built: `card` on every row of `ARTICOLE_MODEL_ROLES_v1.yaml`, merged over its system's base
  card. System One (Jev): `questions` (noul / choice / score with criteria, or `criteria_from` a
  catalog list), `fields` (closed field ← question, or a choice's `.confidence`), `thresholds`
  (`noul_yes` 0.90, `choice` 0.80, `human` 0.10, `[de confirmat]`). Document reading (Gemini):
  `instructions` (copy what is printed, never compute or guess, strings only) + `output` (the
  extract contract). System Two (DeepSeek / GLM): audience, task, limits (no decision, only
  input facts, list what is missing), Romanian, the lexicon's terms, `output_fields` exactly
  `explanation, facts_cited, missing`; `model_roles.brief` renders it as text. `check_card`
  refuses: a choice without criteria, a field reading an unasked question, a wired card that
  does not fill exactly its pack's closed model, a non-text key (YAML `yes` / `no` read as
  booleans — the first draft's `thresholds: {yes: …}` was one), a persona ("you are a …"), a
  System Two decision field. `ModelRole.card_hash` is recorded on every call (with the System One
  question set) and is part of Jev's cache key with the role's model (`jev.role_pin`).
  `GET /model-roles` shows `card_hash` and the System Two `brief`.
- Open: the wording is a first draft, to be compared on synthetic dry / live runs; the System Two
  and document-reading cards are recorded at their shadow call sites (WP-26), never sent yet.

### WP-26 Shadow roles at their place in the flow
- Asked by the owner 2026-10-02: test each role's placement in the flow on Railway before any
  model decides anything.
- Built: role status `shadow` (observed, decides nothing) on 8 roles; `model_roles.ModelGateway`
  (`observe`, `observe_question`) records, under `MODEL_CALLS=dry`, what each would be sent —
  never blocks the flow (failures are logged), a re-entered node records the same input once
  (`seen`). Places: `jev_source_doc` and `jev_our_role` at the SPV / UBL upload (the invoice's
  root, type code, both parties); `jev_v3_classify` at `bind`, `jev_flux` at `bind` only when
  more than one articol matched; `ocr_extract` at the statement upload (the PDF by sha256 and
  size, never its bytes, + the typed header); System Two explainers on the questions their
  HITL kinds name: `v3_approve` (ingest), `recon_ambiguous` / `need_rj_export` /
  `recon_review_contest` (reconcile_sink), `v2_close` (monthly_close).
- Open: `ocr_decont_split` became the 9th shadow role with WP-28 (the expense-report upload),
  `sys2_draft_rule` the 10th with WP-32.

### WP-27 reconcile_sink, POST stage
- Built: `recon/post.py` `how_check` — for an `acked` Job, its posting's lines in the registru
  jurnal (invoice journal, same date, number at an accepted level other than `digits_core`)
  and the synthetic accounts they use, against the articol's `reconcile.expect_accounts` (else
  the POST profile's `fallback_accounts`), matched by prefix: `require_all_accounts: true` =
  every one, `false` = at least one (`[de confirmat]`). `how_ok`; `how_mismatch` (no posting in a
  covered month, accounts off, none expected, no single POST profile); `need_rj_export` (month
  not covered, or no journal lines — the report pack's journals carry no accounts;
  `registry.rj_eye` reads the latest journal upload). The snapshot is the profile + the
  posting's own lines, so a verdict and a person's answer hold until that posting changes.
  On `recon:{cui}:{period}` (`reconcile.PostDeps`): each pass checks the period's acked jobs;
  `how_ok` is stored silently (stage `post`); missing months join `need_rj_export`; a mismatch
  asks `recon_how_mismatch` after the PRE questions: `ack_mismatch` (the posting stands:
  settled) or `open_storno` (correct it in SAGA: stays open, re-checked every pass, not asked
  again for the same posting). `Runtime.post_open` → `monthly_close` is material while a
  posting is unchecked, unanswered or waiting on its storno. `GET /recon/…` shows `post_open`.
  `ReconStore.get`; Postgres `put_once` returns the stored verdict as its own type.
- Open: the storno itself is the person's in SAGA (the storno mouths wait on the copy firm);
  amounts per account: WP-31.

### WP-28 Expense reports over HTTP
- Built: `POST /decont/{cui}` (`filename`, `period`, `file_b64`, `tenant_on_doc`; `.pdf`,
  `.xls`, `.xlsx`, `.msg`, `.eml`) → `folder_triage` on `batch:decont-{cui}-{hash}`. The report
  is a container (A2): it never becomes a Job. Its identity gate is the operator's
  `tenant_on_doc` (nothing reads the file yet); once the gates pass a person names the parts
  (`decont_split`, `POST /triage/{batch_id}/resume` with `parts`), each a child Pack through
  the same gates; a part that breaks the rules is asked again. `GET /triage/{batch_id}` shows
  the question and the children (`emit`, `failed`, `job_id`). An emitted invoice part is a Job
  with no thread until its SPV zip / UBL arrives on `POST /ingest` (same tenant + hash → the
  same Job; its thread starts then). Re-uploading the report returns the same batch.
  `ocr_decont_split` is a shadow role: `MODEL_CALLS=dry` records what Gemini would be given.
- Open: parts are named by a person; the Gemini proposal waits on the live sender and model ids;
  receipts and workings parts are evidence only (no mouth).

### WP-29 Synthetic smoke run
- Asked by the owner 2026-10-02: test each role's place in the flow on Railway.
- Built: `python -m poarta_contabila.smoke` (`--local`: an in-memory runtime, `MODEL_CALLS=dry`;
  `--base-url …` with `GRAPHUSERTOKEN_OPERATOR` in the environment: the deployed service). One invented
  firm (`1000009`, `data_class: synthetic`, one bank account) through every graph with
  scripted answers: the registru jurnal; an SPV invoice → `v3_approve` approve; a statement
  (header + tables) → the receipt bound to its partner and invoice; an expense report →
  `decont_split` → one workings part; `reconcile_sink` (`need_rj_export` answered with the
  uploaded journal, any other question left); `monthly_close` → `v2_close` → `hold`. Then
  `GET /model-calls` for the firm, grouped by graph and node, with each refusal's reason. An
  answer is given only when that question is waiting, so a rerun changes nothing. It refuses a
  server whose `MODEL_CALLS` is neither `off` nor `dry`; it never uses the agent token.
- Open: the service needs a public domain first (`docs/OWNER_CHECKLIST.md`); packaged documents
  stay on `/agent/pull` while no agent is connected.

### WP-30 Partial and combined payments
- Built: `recon/settle.py` — an invoice is open for its gross less what other bound bank lines
  already paid on it (`paid`, by partner + number; the runtime sums the bound lines), so a
  second payment sees the rest and a fully paid invoice drops out. `cover: full` = the open
  amount equals the line; `cover: partial` = it is larger and the description names the
  invoice or its partner (an amount alone never proposes a partial payment), with
  `open_after`. Ranking: the text first, then full over partial. `groups`: with no full
  candidate, two to four open invoices of one partner (the newest 12 searched) adding up to
  the line, ranked by the text; a group is never an `edit` (a bank mouth names one invoice per
  line), and when a group fits as well as the leading invoice no `edit` is given either.
- Open: what was paid is read from this system's bound lines only — a payment SAGA holds that
  never came through here (or an earlier partial payment in the books) is not subtracted, so
  the person still checks the open amount; a group is posted by a person in SAGA.

### WP-31 POST amounts per account
- Built: POST profiles carry `account_amounts` (`ARTICOLE_RECONCILE_v1.yaml`, enum
  `account_amount: [gross, vat]`): `401` / `4111` → the document's gross, `4426` / `4427` /
  `4428` → its VAT. Once the accounts fit, `recon/post.py` `account_amounts` sums what the
  posting moves on each expected account that was used and is listed (each journal line once,
  either side) and compares it with the document within the articol's `tolerance` (else the
  profile's). A difference is `how_mismatch` naming each account, posted vs document, and asks
  `recon_how_mismatch` as before; `PostResult.amounts` carries every comparison. The snapshot
  includes the map and the tolerance, so a catalog change re-checks (a stored `how_ok` from
  before WP-31 is checked again on the next pass).
- Open: class 6 / 7 (net, may be split across accounts) and reverse-charge postings (4426 and
  4427 on one line, WP-D3) are not compared; the map is `[de confirmat]` on the copy firm.

### WP-32 The rule drafter's place
- Built: `sys2_draft_rule` is `shadow` at `monthly_close.v2_gate`, where the catalog puts it:
  when the close finds book documents with no source here (`unexplained`), the drafter's input
  is recorded under `MODEL_CALLS=dry` as the `explained_rule` kind — those documents (the first
  20) and the firm's active rules (id + description), so a draft would not repeat one. Its card
  now says so: wording only, one draft per kind of document; scope, matcher and accounts stay
  the person's, who writes the rule through `POST /rules`. Every role in the catalog now has a
  call site.
- Open: nothing is sent (no sender, no model ids); a draft would be shown with the `v2_close`
  question, never written as a rule by itself.

### WP-33 Answer log
- Built: `answers.py` and `domain.answers`, an insert-only table. Every answer submitted on
  `/jobs/…/resume`, `/recon/…/resume`, `/close/…/resume` and `/triage/…/resume` is logged:
  - graph, thread, tenant, the question's kind and sha256 (without its `error`), the answer
    as sent, UTC time;
  - the author from the optional `X-Operator-Name` header (1–64 printable characters, else
    422 before anything runs), since one shared token names nobody;
  - the outcome: `accepted` (with the next question's kind), `asked_again` (the same question
    came back with its `error`) or `no_question`.

  With nothing waiting, the graph is no longer run at all. Before, resuming a recon or close
  thread that never started failed with a 500. `GET /answers?cui=&thread=&limit=` reads the
  log, newest first.
- Open: one token per person instead of a self-declared name; the log keeps answers whole, so
  a client tenant's answers hold client data and fall under the same retention as its jobs.

### WP-34 Before the operator API is public
- Built: `app.BodyLimit` caps every request body at `MAX_UPLOAD_MB` (default 32 MB; base64
  adds a third, so about 24 MB files). A declared Content-Length over the cap gets 413 at once.
  Otherwise the body is read in full before any route runs and refused as soon as it passes the
  cap, so no route sees part of a body. `/ready` adds `operator_token` and `agent_token`:
  `ok`, `unset`, `shorter than 32 characters` or `same as another token`. These are reported,
  never the values, and do not gate readiness.
- Open: no rate limit; per-person tokens (see WP-33).

### WP-35 The EU route's shape
- Built: `model_roles.EuRoute` fixes the shape of `eu_route` without deciding it:
  - `provider` is `vertex` or `scaleway`;
  - `location` must be on that provider's explicit EU list (`EU_LOCATIONS`). Google's London
    (`europe-west2`) and Zurich (`europe-west6`) regions and `global` are refused;
  - `model` is an exact id (the same alias rules as `model`);
  - `key_env` and `project_env` name the variables that hold the credential and the project
    (Vertex needs both). The catalog holds names, never values.

  Routing:
  - a client tenant goes by `eu_route` alone and needs no OpenRouter `model`;
  - a synthetic tenant goes by OpenRouter alone;
  - recorded calls carry `route: eu/<provider>/<location>` and the EU model, or `eu/none` when
    refused.

  `GET /model-roles` adds `eu_route_set` and `eu_keys_set`, which say whether the variables
  are set, never their values. The smoke run reports how many roles have one.
- Also fixed: the smoke run built its SPV zip with the current time inside, so a rerun across a
  2-second boundary minted a second Job for the same invoice. The zip now has a fixed
  timestamp.
- Open: every `eu_route` stays null until the owner's EU-route decision; no EU transport is
  built (WP-20 / WP-24).

### WP-36 Gemini direct for synthetic statements
- Asked by the owner 2026-10-02: document reading on synthetic data goes straight to Google AI
  Studio (key in `GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC`), not through OpenRouter; every other role
  stays on OpenRouter. `00_LAW.md` §3 invariant 5 changed in place.
- Built: `extract/gemini.py` `GeminiStatementReader`, the first live sender.
  - **Guards, before any request:** the tenant must be `data_class: synthetic` (checked
    again here, whatever the caller checked); `MODEL_CALLS=live`; a model on the role; the
    key set. A refusal is recorded and nothing is sent.
  - **The request:** Gemini API `v1beta/models/{model}:generateContent`, header
    `x-goog-api-key`, the role card's brief as `systemInstruction`, the PDF as `inlineData`
    (at most 18 MB), JSON out, temperature 0. The format matches Google's documented example
    as quoted in search results; Google's docs site is blocked from this session.
  - **The answer:** only the card's shape is taken (`header` of strings, `tables` of
    `{headers, rows}` strings). Anything else refuses the statement. The holder CUI must be
    the tenant's, the IBAN the typed one, then `parse_statement` makes every line tie.
  - **Recording:** every call goes to `domain.model_calls` as `sent` / `failed` / `refused`,
    with the PDF's sha256 and size and the answer's shape, never the bytes or the key.
  - **Reuse:** the extract is stored once per `(sha256, gemini)`, and a re-upload reuses it.
- Routing: `Runtime.reader_for(cui)` gives Gemini to a synthetic tenant when it is wired, else
  Document AI. A client tenant never gets Gemini.
- Mode `live`: synthetic document reading sends; every other role records as in `dry`,
  because Jev and System Two have no sender yet.
- Catalog: route `google_ai_studio` (document reading only; bare `gemini-…` ids, no
  `google/`, no aliases, no provider pins); `ocr_extract` is `wired`, and `ocr_decont_split`
  stays `shadow` on the same route.
- The smoke run accepts `live`, and `--ocr` uploads a real generated one-page synthetic
  statement PDF without tables.
- Then (owner, 2026-10-02):
  - both document-reading roles are pinned to `gemini-3.8-flash`;
  - `00_LAW.md` §3.5 now lets a model read statement tables even from a text-layer PDF,
    because the tie-out checks every line;
  - the request carries `STATEMENT_SCHEMA` as `responseSchema`, so the answer is constrained
    to the card's shape and `parse_answer` still checks it.

  A refused client call is recorded with no model (route `eu/none`).
- Open: a wrong field name in the request would show as `failed` with Google's HTTP status on
  the first live run.

### WP-37 Reading evaluation
- Asked by the owner 2026-10-02: measure, don't guess, before any Pro escalation.
- Built: `ocr_eval.py` has six invented statements, each a real PDF with its known answer
  (`synthetic_docs.text_pdf`, deterministic, multi-page):
  - `simple`;
  - `ro_labels` (Data operatiunii / Detalii / Plati / Incasari, thousands separators);
  - `continuation` (wrapped descriptions, a total row);
  - `column_order` (credit before debit);
  - `two_pages` (60 lines, the header row repeated);
  - `dense` (30 near-equal amounts on few days).

  Score per case: read (in the card's shape), identity, IBAN, header fields (out of 6),
  ties (`parse_statement` accepts it), and lines with the right date, side and amount, in
  order.
- `POST /ocr-eval/{cui}?case=&model=`: the server's Gemini reader reads one case or all, for a
  synthetic tenant only, with `MODEL_CALLS=live`. Nothing is minted; each read is a
  model-call record. `model` reads with another bare AI Studio id for comparison only; the
  catalog keeps one pinned model.
- The command `python -m poarta_contabila.ocr_eval --base-url … [--model …] [--case …]`
  sends one request per case and prints the table; `--write-pdfs DIR` saves the PDFs to look
  at.
- A test checks the answer key: a perfect reading scores full marks on every case. It caught
  a case whose closing balance went negative; the builder now refuses that.
- Open: text-layer PDFs only (no scans, photos or rotations yet); receipts (WP-14) get their
  own cases when that WP is unparked.

### WP-38 Token names and the build agent's token
- Asked by the owner 2026-10-02: the tokens are `GRAPHUSERTOKEN_OPERATOR` and
  `GRAPHUSERTOKEN_AGENT_SHARED`, read first, with the old names `OPERATOR_TOKEN` /
  `AGENT_SHARED_TOKEN` only when the new one is unset or blank. The PR #7 deploy read only the
  old names, so with the variables renamed the operator and agent routes answered 503 until
  this ships.
- `GRAPHUSERTOKEN_CLAUDE_SYSBUILDER`, the build agent's token (Claude acting for the owner):
  - **Same routes, synthetic tenants only.** A request must resolve to a tenant marked
    `data_class: synthetic` (the path's `cui`, the `cui` query, the job's or the batch's
    tenant), else 403. A new tenant registered with it must be synthetic, and an existing
    client tenant is never touched.
  - **Logs:** `/model-calls` and `/answers` show it synthetic tenants' rows only; its answers
    are logged as `claude-sysbuilder`.
  - **Default deny:** a route that names no tenant and is not listed is closed to it.
  - Never opens the agent routes. Ignored when equal to another token.
  - `/ready` reports it like the other two, never its value.
- The smoke run and the evaluation read `GRAPHUSERTOKEN_OPERATOR`, else
  `GRAPHUSERTOKEN_CLAUDE_SYSBUILDER`, else the old name.
- Open: for the build agent to run them against Railway, the service needs a public domain
  and the build session needs the token in its own environment (never in the chat).

### WP-39 Gemini reader retries a busy Google
- Found 2026-10-02 by the build agent's live smoke run and evaluation: Google AI Studio
  answered `HTTP 503 UNAVAILABLE` on the statement PDF read and on 4 of the 6 evaluation
  cases; the other two read correctly, so the request was sound and the model was busy.
- `_generate` now tries at most 3 times for 500, 503, 504 or a transport error (429: WP-40), waiting
  2 s then 6 s. Any other answer (403, a bad body, a block) fails at once, as before.
- One recorded call per read however many tries; the final reason names the attempts. The
  model, the synthetic-only guards and the key handling are unchanged.

### WP-40 Free-tier rate limits and one backup model
- Asked by the owner 2026-10-02 (00_LAW §8 A3): keep Google AI Studio until the owner moves
  to the EU route; bake in the free tier's limits; read with a backup model when the main
  one is at its limit.
- Catalog: both document-reading roles pin `gemini-3.8-flash` with `backup_model:
  gemini-3.7-flash` and `rate_limits` 5 RPM / 250 000 TPM for each (the owner's AI Studio
  page). `load_roles` refuses a backup off the Google AI Studio route, a backup equal to the
  model or not an exact `gemini-…` id, and a Google AI Studio model without a rate limit.
  Fallback lists stay forbidden.
- `extract/gemini.py`: a process-wide `RateLimiter` counts requests and tokens per model over
  the last minute (a PDF is estimated at 258 tokens a page plus 1 000, then settled to
  Google's `usageMetadata.totalTokenCount`). The reader takes the main model while it has a
  slot, else the backup; a 429 blocks that model for a minute and moves to the other; both
  full → wait for the first slot, at most 90 s, else the statement is refused. 503 retries
  (WP-39) stay on the same model and take a slot each.
- The model call records the model that read; a backup read says so (`output.backup`).
- The evaluation never uses the backup: it scores the one model asked for (and a `--model`
  override gets the main model's limits).
- Open: the limits count only this process; Google's own count is per project, so another
  client of the same key still shows as 429.

### WP-D3 Non-payer reverse charge books (`decision`)
- Ask: expected sink accounts for `foreign_rc_neplatitor` — harvest Y1 used 446x; some SAGA books use 4423.
- Until answered: articol exists, `expect_accounts: []`, `nota_nc_dbf` always-HITL, or SAGA-native + `explained_rule`.
- Do not silently fill 4423 or 446.

## Definition of done for v1

WP-00–WP-12 green. WP-13 optional. Parked WPs untouched. No `Journal.post` in the tree. No SYSDBA in env samples. Catalogs that shipped without fixtures remain `draft`.
