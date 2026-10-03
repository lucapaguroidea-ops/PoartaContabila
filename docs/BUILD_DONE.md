# BUILD — details of done work packages

Moved out of `BUILD.md` on 2026-10-03 (WP-68) so that a session reads only open work.
The status table in `BUILD.md` stays the index of every WP. Text kept as written.

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
- Built 2026-10-03 (owner: models confirmed, keys set, "go for it"), through OpenRouter, not
  the direct TypeSafe route:
  - Catalog: every System One role `typesafe/jev-1.13`, provider `{only: [typesafe]}`; the
    DeepSeek roles `deepseek/deepseek-v4.1-flash` `{only: [deepseek]}`; `sys2_draft_rule`
    `z-ai/glm-5.3` `{only: [z-ai]}`; fallbacks off, data collection denied (RESEARCH_LOG R2).
  - `jev.role_transport`, `MODEL_CALLS=live`, a wired pack (`v3_judge`, `recon_review`,
    `v2_declaration_gate`), a synthetic tenant (`route_check`; a client tenant needs the EU
    route, which no role has) and the OpenRouter key set (`OPENROUTER_SYS1_API_KEY`, WP-55): `POST
    https://openrouter.ai/api/alpha/decisions` with `{model, state: the pack input,
    questions: the role card's questions, provider: the pin}`. Without the key it records as
    in `dry`.
  - The answers are mapped by the card's thresholds: a `noul` is yes from 0.90
    (`needs_human` from 0.10); a `choice` stands from confidence 0.80, else its cautious value
    (`risk: high` + `needs_human`; `gap_materiality: material`; `action: hold`;
    `verdict: abstain`). An answer off the card, a non-200 or an unreachable endpoint is
    recorded `failed` and fails closed (a person is asked; Layer 2 gives no suggestion).
  - Every call is recorded (`sent` with the answers, the mapped fields and the usage; never
    the key). Answers are cached in `domain.jev_answers` (keyed with the role's model and
    card hash), so a question is paid for once.
  - System Two roles stay `shadow`: pinned, recorded, not sent (no sender is built for them).
- Open: the Decisions endpoint is `alpha`; where TypeSafe processes data is not documented,
  so Jev stays synthetic-only until the owner decides an EU route for it.

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

### WP-41 Model tiers, daily limits and the second run
- Asked by the owner 2026-10-02 (00_LAW §8 A4) after the second live run: the free tier's
  Flash models allow 20 requests a day, and the 503s seemed to count against it, so the
  `dense` case got a daily 429.
- Catalog (both document-reading roles): `tiers.everyday` = `gemini-3.5-flash-lite`,
  `gemini-3.1-flash-lite` (15 RPM, RPD `[de confirmat]`); `tiers.strong` = `gemini-3.8-flash`,
  `gemini-3.7-flash` (5 RPM, 20 RPD); `model` is the first everyday one. `backup_model` is gone.
  `load_roles` refuses tiers off the Google AI Studio route, a model listed twice, an inexact
  id, a `model` other than the first everyday one, and a tier model without a rate limit.
- `extract/gemini.py`: the limiter also counts requests per Pacific day (every attempt);
  `order()` is everyday → strong, strong first for 2+ pages or `strong: true`, strong only for
  a second run; a 429 names its quota (`QuotaFailure.quotaId`) and a `…PerDay…` one skips the
  model until Pacific midnight; a busy model gets one retry after 10 s (was 3 tries), then the
  next model. The call records `tier`, `first_choice`, and "second run".
- `runtime.py`: a Gemini read that fails `statement_problem` (holder CUI, IBAN, tie-out) is
  read once more by the strong tier; still failing → refused, not stored, so a re-upload
  reads again. `POST /extras/{cui}` takes `strong: true`.
- The evaluation reads with one model (the first everyday one, or `--model`).
- Open: the Lite models' daily limits and the ids `gemini-3.5-flash-lite` /
  `gemini-3.1-flash-lite` are to be confirmed on the owner's AI Studio page.

### WP-42 Lite first, parked reads, reading budget
- Asked by the owner 2026-10-02 (00_LAW §8 A5), from AI Studio's full rate-limit table: Lite
  500 RPD each, Flash 20; the Lite model read all six evaluation statements correctly.
- Catalog: `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite` get `rpd: 500` (no longer
  `[de confirmat]`).
- `order()`: pages no longer send a statement to the strong tier first; only `strong: true`
  does, and a second run.
- No model can read now (`OutOfQuota`: every model at its limit, 429 or busy; it carries
  when the first may read again) → the statement is parked in `domain.reading_waits` with its
  PDF in the bucket, and `POST /extras/{cui}` answers **202** `{status: waiting, wait_id,
  not_before, reason}`. No Job until a read confirms. A wrong read is still a 422.
- Read again: a background task every `READING_RETRY_SECONDS` (default 60, 0 = off) and
  `POST /reading/{cui}/retry`; a parked statement becomes `read` (with the ingest result),
  waits longer (still no quota), or `refused` (the read did not confirm).
- `GET /reading/{cui}/waiting`; `GET /reading/{cui}/budget?documents=N`: per model rpm, rpd,
  used today, left today, spent by Google; tier totals; seconds to Pacific midnight; what
  waits; warnings when N statements (plus those waiting) exceed today's everyday reads, or
  the strong reads left could not give each a second run.
- The smoke run reports a parked statement as `waiting for model quota until …`.
- Open: the counts are this process's; a redeploy restarts them at 0 (Google's 429 still
  stops a spent model). The operator's on-the-fly choice when every tier is spent (reserve
  models, evaluated first) is the next WP.

### WP-43 The operator's choice when every tier is spent
- Asked by the owner 2026-10-02 (00_LAW §8 A6): reading must not stall until a procedure is
  written.
- Catalog: `tiers.reserve: [gemini-3.6-flash, gemini-3.5-flash]` (5 RPM, 20 RPD each) on
  both document-reading roles. Evaluated 2026-10-02 against production: every statement they
  answered was read right (3.6: `dense` 30/30; 3.5: `continuation` 9/9), the other five each
  were Google 503s, so 6/6 stays `[de confirmat]`. `gemini-3-flash` and `gemini-2.5-flash`
  answered 404: those ids are not the API's (the owner to read the exact ids in AI Studio).
- Reader: `reserve_until`; the reserve models join the end of the order (and of a second
  run) only while it holds; calls record `tier: reserve`; the budget lists them.
- A parked upload's 202 and the budget carry `ask` (question + closed options) while the
  reserve is not open. `POST /reading/{cui}/choice` (`wait` | `reserve`), recorded in
  `domain.reading_choices` with the operator (`X-Operator-Name`, or `claude-sysbuilder`);
  `reserve` opens until Pacific midnight, releases this tenant's waiting statements and
  reads them at once. `POST /reading/{cui}/waiting/{wait_id}/skip {reason}` sets one aside
  (status `skipped`, never read by a model).
- Open: re-evaluate the reserve models after the 07:00 UTC reset for a clean 6/6; find the
  real ids of Gemini 3 Flash and 2.5 Flash before listing them.
### WP-44 Why a read does not tie
- Asked by the owner 2026-10-02: on the live evaluation `two_pages` read 60/60 lines and 6/6
  header fields but did not tie, twice; the score did not say why.
- `CaseScore` gains `tie_error` (`parse_statement`'s reason, at most 300 characters) and
  `rows_read` (every row the model returned); `render` prints
  `does not tie (N rows read): <reason>` under the case.

### WP-45 Balance rows are not lines
- Found 2026-10-02 by WP-44 on the live evaluation: `two_pages` with `gemini-3.5-flash-lite`
  returned 61 rows for 60 lines; `table 2 row 21: a line moves on exactly one side`. The
  extra row is the closing balance (`Sold final: …`) with its label outside the description
  column, so the existing skip (description starting Total / Sold) missed it.
- `parse_statement` skips a row when any cell starts with Total / Sold (accents and case
  ignored, so Soldul too). Safe because of the tie: a real line skipped this way leaves
  opening − debits + credits ≠ closing, and the statement is refused.
- `ocr_extract`'s card task now says the tables hold movement lines only; the opening and
  closing balances go in the header, never as a table row (the card hash changes).

### WP-46 A statement line's counterpart in C0
- Found 2026-10-02 while tracing the synthetic firm's held September close: C0 implied only
  the bank side (5121) of a statement line, so a supplier payment (401 Dr) or a customer
  receipt (4111 Cr) in the books was always a difference, and no month with bank activity
  could be filed.
- Decided by the owner 2026-10-02: a line bound to a customer implies 4111, to a supplier
  401, on the side opposite 5121 (what `incasare_xml` / `plata_xml` post); a line never bound
  (already in the books when it arrived) implies the books' own counterpart only when its bank
  document there is one journal line, 401 Dr for a payment or 4111 Cr for a receipt, of
  exactly the line's amount. Anything else (another account, a split posting, a `%` entry, a
  role of `both` / `unknown` with no such posting) stays a difference. A payment with no
  statement line here is still a difference (the fixture test keeps it).
- `period_diff.bank_counterparts`; the books' documents are matched as before (bank: side +
  date + amount), and the counterpart is added to the implied turnover. Catalog: C0 note.

### WP-47 A clean month in the smoke run
- Asked by the owner 2026-10-02 ("fix the month-close blockers"). The synthetic firm's
  September close was held by four blockers, none of them a fault:
  - **lock mismatch**: the smoke answered `hold` every run while its September jobs kept
    changing; `hold` keeps the lock, only `reopen` releases it (WP-10, by design);
  - **C1**: its packaged jobs wait for the SAGA agent (`acked` comes only from an agent
    snapshot, and the build agent's token never opens the agent routes, WP-38);
  - **C2 and most of C0**: the smoke reused `saga_rj.xls`, the books of another test, which
    hold invoices 1427, FX-101 and AB0058 that the smoke never uploads, while its own
    documents are not in them;
  - **C0 401 Dr**: a statement line's counterpart was never implied (fixed by WP-46).
- Decided by the owner 2026-10-02: prove a clean close on a fresh month, keep September as
  the honest held example.
  - `fixtures/sink/make_fixtures.py` writes `saga_rj_smoke.xls`: a clean August (the SPV
    purchase AB 0070 of 12.08, 807,81 with 132,31 VAT; its payment OP-81 of 20.08, 401 Dr /
    5121 Cr; a customer receipt IN-25 of 25.08, 500,00, 5121 Dr / 4111 Cr), then September
    line for line as `saga_rj.xls` (which is unchanged, byte for byte). The books view uses
    the tenant's latest export, so one export covers both months.
  - The smoke uploads it, then (step 8) August's SPV invoice (`fixtures/ubl` renumbered
    `AB 0070`, issued 12.08) and statement (opening 5 307,81, closing 5 000,00 = September's
    opening): every job ends `already_in_sink`.
  - `monthly_close` runs for September, then August, answered `hold` (nothing is filed). On a
    lock mismatch it answers `reopen` first, then closes again
    (`reopened after a lock mismatch; …`).
- Expected: August `material=False` with no blocker; September material (its packages wait
  for an agent; its books hold invoices never uploaded).

### WP-48 Reserve order from the evaluation
- Evaluation of 2026-10-03 against production (after the quota reset): `gemini-3.5-flash`
  6/6 (115/115 lines, 36/36 header); `gemini-3-flash-preview` 6/6 (a preview model: Google
  may change or withdraw it); `gemini-3.6-flash` 2/6, read right whatever it answered, the
  other four Google 503s.
- Owner, 2026-10-03: `tiers.reserve` is `[gemini-3.5-flash, gemini-3-flash-preview,
  gemini-3.6-flash]` on both document-reading roles; `gemini-3-flash-preview` 5 RPM, 250K TPM,
  20 RPD (AI Studio's Gemini 3 Flash row). `gemini-2.5-flash` stays out: Google serves 2.5
  only to projects that used it before (404 here).

### WP-49 One OpenRouter key
- Smoke run of 2026-10-03 after WP-20: `/model-roles` showed `OPENROUTER_JEV_API_KEY` unset, so
  both `jev_v2_gate` calls were recorded, not sent. The owner set one OpenRouter key on Railway,
  `OPENROUTER_SYS2_API_KEY`, for both systems.
- `model_roles.KEY_ENV` and the catalog's `systems.system_one.key_env` are
  `OPENROUTER_SYS2_API_KEY`; `OPENROUTER_JEV_API_KEY` is gone from the `key_env` enum. A test
  holds the catalog's names to `KEY_ENV`. Jev and System Two share that key's credit limit.

### WP-50 System Two explains the question
- Owner, 2026-10-03: build the System Two sender. `sys2_explain_approve`, `sys2_explain_recon`
  and `sys2_explain_close` are `wired`; `sys2_draft_rule` stays `shadow` (recorded only).
- `MODEL_CALLS=live`, a synthetic tenant (`route_check`; a client tenant is refused) and
  `OPENROUTER_SYS2_API_KEY` set: `POST https://openrouter.ai/api/v1/chat/completions` with
  the role's pinned model and provider (fallbacks off, data collection denied), the card's
  brief as the system message and `{kind, question}` as JSON. Once per question: a node that
  runs again on resume does not send again. Without the key it records; in `dry` it records.
- `explain.check_explanation`: the answer is exactly `explanation` (at most five sentences),
  `facts_cited` (each `{field, value}` found in the question: a made-up fact is refused) and
  `missing`. Off the card, a non-200 or unreachable → recorded `failed`; the question is
  shown without an explanation and nothing waits on it.
- The job, reconcile and close views carry `explanation` (`role_id`, `explanation`,
  `facts_cited`, `missing`, `served_by`) next to `question`. No node reads it; it cannot
  approve, hold, file or post anything.

### WP-51 Explanations on GLM
- Smoke run of 2026-10-03 after WP-50: every `sys2_explain_close` call failed, OpenRouter HTTP 404
  "No endpoints found matching your data policy (Paid model training)". OpenRouter's provider
  list (2026-10-03): DeepSeek `training: true, retainsPrompts: true`; Z.AI and TypeSafe
  `training: false, retainsPrompts: false`.
- Owner, 2026-10-03: take GLM if Z.AI is not flagged. `sys2_explain_approve`,
  `sys2_explain_recon` and `sys2_explain_close` are `z-ai/glm-5.3`, provider `{only: [z-ai]}`;
  data collection stays denied for every role. No role uses DeepSeek now.

### WP-52 GLM answers
- Smoke run of 2026-10-03 after WP-51: every `sys2_explain_close` call reached GLM and failed
  "the answer is not JSON" (about 10 s each: GLM reasons first).
- The request turns reasoning off (`reasoning: {enabled: false}`) and allows 2000 tokens; the
  JSON object is read from between the first `{` and the last `}`; an empty answer says so; a
  bad one is quoted (160 characters, synthetic questions only) in the call's reason.

### WP-53 Approved alternates (00_LAW §8 A7)
- Owner, 2026-10-03: a provider changing its data policy must not halt the work; the switch to
  an approved alternate is automatic. OpenRouter's provider list that day: 52 of 92 providers
  neither train on nor keep prompts (DeepSeek does both; Z.AI, Together, Moonshot AI and
  TypeSafe do neither).
- Alternates (all four System Two roles): `z-ai/glm-5.3` on `together` (same model, a second
  host), then `moonshotai/kimi-k2.6` on `moonshotai` (another family, served by its maker).
  Jev has none: `typesafe/jev-1.13` is served only by TypeSafe and `typesafe/jev-router` is an
  auto-router.
- `provider_policy`: the list is read from OpenRouter's provider list
  (`/api/frontend/v1/all-providers`, the one that carries `dataPolicy`; the documented
  `/api/v1/providers` does not) at start and every `POLICY_REFRESH_SECONDS` (a day), and
  after a 404 "data policy" refusal, which is then retried once on the new pin. A provider
  never read counts as passing (OpenRouter still enforces `deny`).
- `/model-roles` shows each OpenRouter role's `pin` (`on`: main / alternate N / operator
  choice / none, the reason, when the policies were read, the operator's choice); the smoke
  run lists every role not on its main pin. `POST /model-roles/{role_id}/choice` (operators,
  not the build agent): `wait`, `pause` or `allow_synthetic` until a date.

### WP-54 GLM 5.3 reasons
- Smoke run of 2026-10-03 after WP-53: every explanation failed, OpenRouter HTTP 400 "Reasoning
  is mandatory for this endpoint and cannot be disabled" (WP-52 had turned it off).
- The request asks `reasoning: {effort: low, exclude: true}` (the answer carries no reasoning)
  and allows 6000 tokens, reasoning included. Policies and pins were fine: every OpenRouter
  role on its main pin, policies read at start.

### WP-55 Jev's own key
- Smoke run of 2026-10-03 after WP-54: the shared key (`OPENROUTER_SYS2_API_KEY`, WP-49) could
  afford 4137 more tokens (OpenRouter HTTP 402), so Jev and System Two would run dry together.
- Owner, 2026-10-03: Jev uses `OPENROUTER_SYS1_API_KEY`. `model_roles.KEY_ENV["system_one"]`
  and the catalog's `systems.system_one.key_env` name it; System Two keeps
  `OPENROUTER_SYS2_API_KEY`. Each system spends against its own key's credit limit.

### WP-56 Spend per key, from OpenRouter
- Owner, 2026-10-03: read the actual spend per key from OpenRouter instead of estimating it.
- `GET /model-keys` (operator and build agent; tenantless): for each OpenRouter `key_env` the
  catalog uses, `GET https://openrouter.ai/api/v1/key` with that key → `usage` (all time),
  `usage_daily`, `usage_weekly`, `usage_monthly`, `limit`, `limit_remaining`, `limit_reset`,
  `is_free_tier`, and the roles that spend it. OpenRouter's `label` is dropped (it can show part
  of the key); no key value is ever answered or logged.
- With `OPENROUTER_MANAGEMENT_KEY` set (optional): `GET /api/v1/credits` (credits bought and
  used) and `GET /api/v1/keys` (every key by name: spend, limit, left, disabled). Read only.
- The smoke run prints one line per key (`openrouter key`), as OpenRouter gave the figures.

### WP-57 Free-tier token cap
- Owner, 2026-10-03: System Two calls fail HTTP 402 "can only afford 4137" despite the key
  showing $0.98 left of $1.00. Root cause: `is_free_tier: true` makes OpenRouter cap the
  per-request token budget to what the free credit pool can cover (~4137 tokens ≈ $0.018).
  The key's own limit ($1.00) is irrelevant under the free-tier constraint.
- Resolution: owner added credits → `is_free_tier` flipped to `false` on both keys, removing
  the per-request cap. `MAX_TOKENS` stays at 6000 (needed for close questions with reasoning).

### WP-58 System Two answers on the card
- Smoke of 2026-10-03 after WP-57: GLM answered, but `explanation is empty` (twice) and
  `fact 'question.blockers' = [] is not in the question`.
- The card's `output_rule` now says the explanation is never empty and written in the answer
  (not only in the reasoning), and that only single values are cited: an empty field is not a fact.
- `explain.send`: an answer that fails `check_explanation` is asked once more (`RETRIES = 1`),
  with the model's answer and the refusal reason added to the conversation. A second bad answer
  is `failed` with `(after 2 answers)`. The call's output records `answers` and the summed usage.
- Next, owner 2026-10-03: try the approved alternate `moonshotai/kimi-k2.6` if GLM still misses.

### WP-59 Compare a role's approved alternates
- Owner, 2026-10-03: compare `moonshotai/kimi-k2.6` (approved alternate, A7) with GLM before
  any change of pin.
- `POST /model-roles/{role_id}/compare?inputs=2&runs=3` (operator and build agent: synthetic questions only): a System Two
  role's latest distinct questions of synthetic tenants, each sent `runs` times to the main pin
  and to every approved alternate with its own provider pin (`data_collection: deny`), no retry.
  Answers: per candidate, first-try passes of `check_explanation`, cost per pass, each result.
- Returned, never recorded; it changes no pin. Choosing a new main pin stays a catalog change.

### WP-60 After the first comparison
- Comparison of 2026-10-03 (close questions, 6 tries each, first answer): GLM on Z.AI 5/6,
  GLM on Together 2/6 (both passes were `"..."`), Kimi on Moonshot AI 0/6 (every answer empty).
- `check_explanation` refuses an explanation of fewer than 4 words (`...`, `N/A`).
- `reasoning: {effort: low, exclude: true}` is sent to `z-ai/` models only (`REASONING`); other
  families get no reasoning field. An answer with empty content and only reasoning is failed
  as `the model wrote only reasoning`, so the cause shows.
- `compare` defaults to `runs=1` (at most 3): a call takes ~40 s and 18 calls ran past the edge
  timeout.

### WP-61 Compare one call per request
- After WP-60 a 6-call comparison ran past the edge's 300 s (HTTP 499): without GLM's reasoning
  settings a call can take a minute or more.
- `candidate` (0 = main pin, N = alternate N) and `skip` (start after that many of the latest
  questions) let a request send exactly one call (`inputs=1`).

### WP-62 GLM's two habits
- Comparison of 2026-10-03 after WP-61 (6 first answers each): GLM on Z.AI 1/6, Together 3/6,
  Kimi 1/6 (reasoning only, ~139 s, ~$0.02 a pass). GLM's misses: `{"answer": {...}}` (3) and
  `blockers = []` cited as a fact (2).
- `check_explanation` unwraps one outer key when its value has exactly the card's fields, as an
  object or as a JSON string (Z.AI sends `{"answer": "{\"explanation\": …}"}`).
- A cited fact whose value is empty (`[]`, `{}`, `""`, null) claims nothing: it is dropped. Its
  field must still be in the question; any other value must still be found there.
- Kimi stays an approved alternate but is not used by choice until its call is reworked.

### WP-63 English, dated
- Owner, 2026-10-03: write and answer in English (fewer tokens; GLM's generated Romanian had
  slips such as "bloqueazători"); frame it as Romanian accounting as of today.
- Card `language`: English; Romanian domain words stay Romanian (00_LAW: the card's terms,
  SAGA's names, field values).
- Each question is sent with `as_of` (today, UTC date) next to its fields. It is not part of
  the recorded input, so the explanation's input hash stays the same on later days.
- New card limit: rules apply as of `as_of`; the model's knowledge of Romanian rules may be out
  of date, the input wins, and no rule is stated from memory. A rule that matters reaches the
  model as an input field from the catalog.

### WP-64 The approval explanation in the smoke run
- `sys2_explain_approve` was never exercised after WP-50: smoke's `AB 0099` was approved on its
  first run, and every rerun finds the same job.
- Smoke now ingests `AB 0102` (25.09.2026, own SPV id) before the closes and never answers it,
  so its `v3_approve` waits and step `approval explanation` shows the explanation (sent once,
  then found again by its input hash), or the call's status and reason.
- It is dated September because the journal covers August and September only (an October
  invoice stops at `need_rj_export`). September is already held as material; this adds one
  expected job and 807.81 to C0's expected 401 credit there.

### WP-65 A run stopped between nodes goes on
- Smoke of 2026-10-03: September's close returned 502 while the server restarted for a deploy;
  its run stayed `v2_ready` with `layer2` next and no question. `start_close` read any pending
  task as "waiting on a person", so every later start showed nothing.
- `Runtime._start` (close and reconcile_sink): a run with a question waits; a run with a next
  node and no question continues from its checkpoint (`invoke(None)`); otherwise it starts.

### WP-66 Review page (00_LAW §8 A8)
- Owner, 2026-10-03: a thin page of our own instead of a hosted chat front end. A1 §4 put the
  review page in v2; A8 brings it into v1. WP-17 (`chat:` face) stays parked.
- `GET /inbox/{cui}/{period}` (`Runtime.inbox`): the firm's open jobs (any month; acked,
  already_in_sink, rejected and failed are never open) with the question each waits on, plus
  the month's reconcile_sink and monthly_close. Each item: `kind`, `actor`, `answer_schema`
  (ArticoleHITL `resume_schema`), `answer_path`, `question`, `explanation`, `job`. Questions
  whose actor is not `accountant` (`wait_validare`) are left out; a `needs_human` job with no
  question is listed with its error and no answer. The path names the firm, so the build
  agent's token is held to synthetic firms as everywhere else (WP-38).
- `GET /review` (+ `review.js`, `review.css`, `icon.svg`, `poarta_contabila/ui/`): no token to
  load (the files hold no data); CSP `default-src 'none'`, scripts and calls to this origin
  only, no framing, no referrer, `no-store`.
- The page: name + operator token (token in the tab's session storage only; ă, ș, ț are
  written without marks because the name travels as an HTTP header). Per card: summary
  (number, date, partner, gross, articol de cale), Jev's flags, lines, blockers, the System
  Two explanation (labelled: it decides nothing), the whole question, and the answer. Choices
  come from the catalog's enum fields; the answer starts empty, Send stays disabled until the
  person chooses or writes, and the JSON that will be sent is shown first. A refused answer
  shows the server's reason. Every value is written as text (`textContent`), never markup.
- Checked in Chromium on a local in-memory server filled by the smoke run: wrong token → sign
  in again; four cards; an invoice whose supplier name is an `<img onerror>` payload shows as
  text and runs nothing; a bad answer is refused readably; approve and hold go through and the
  cards leave; no horizontal scroll at 390 px; sign out forgets the token.

### WP-67 Expense-report splits on the review page
- Owner, 2026-10-03: put `decont_split` on the review page.
- `domain.triage_batches` (`InMemoryBatchIndex` / `PostgresBatchIndex`): every folder_triage
  batch with its firm and month, written when a report is uploaded (again, for a report
  uploaded before this WP). The inbox lists each batch's waiting question, whatever the month
  shown; its answer goes to `POST /triage/{batch_id}/resume` (A8 §1).
- The page's split form: one row per part; the person chooses the part's file, the browser
  computes its SHA-256 (`crypto.subtle`) and reads the kind from the extension; the file is
  never uploaded (the answer names parts by hash, as the API does). Then what the part is
  (the question's `children`), whether our CUI is on a bon, and the counterparty CUI. Send stays
  disabled until a part has a file; `check_split` still judges the answer.
- Checked in Chromium: hashes equal the files' SHA-256; the only request is the JSON answer
  (374 bytes); the card leaves once the split is accepted.

### WP-68 Tidy
- Owner, 2026-10-03: tidy the repo before the synthetic-data program (WP-69 – WP-74).
- `BUILD.md` kept the status table and the open WPs' details (83 KB → 13 KB, read by every
  session); the 63 done WPs' details moved here unchanged. `CLAUDE.md` and `AGENTS.md`: a done
  WP's details move here in the same commit.
- `ARCHITECTURE.md` §11 lists the modules as built (it listed `graphs/…`, `maps.py`, which never
  existed). `INDEX.md` names `poarta_contabila/`, `tests/`, `docs/` and marks `docs/harvest/` as
  history next to `annex/`. Nothing deleted.

### WP-69 Coverage map
- Owner, 2026-10-03: the synthetic-data program (BUILD.md) starts with a map of what is covered.
- `python -m poarta_contabila.coverage [--json]` (`coverage.py`): every catalog row a document
  or a month can reach — articole de cale (Flux and Reconcile), source docs, job kinds, HITL
  kinds with their actor, controls once as PASS and once as FAIL, recon profiles, write
  modules, filings, close kinds — with the scenarios whose expected path names it and the test
  files that name it (a quoted id in `tests/*.py`; this reproduces the baseline counts: 6 of 22
  articole, 17 of 27 HITL kinds, 9 of 13 controls, 6 of 10 write modules).
- A row is covered only when a *passing* scenario names it; a test naming it is shown, never
  counted. A reachable row with no scenario is a scenario to write.
- `OUT_OF_REACH`, written by hand against the code, says why a row cannot be reached today:
  parked (WP-14: bonuri), decision (WP-D3: `foreign_rc_neplatitor`, `nota_nc_dbf`), no code
  path (triage articole are never bound; no foreign-invoice route; 13 HITL kinds no node asks;
  `parteneri_xml` / `articole_xml` / storno mouths not rendered), not computed in v1
  (`M1_8_4428_open` PASS, `M1_9_4424_watched`), live only (`recon_review_contest`: in dry mode
  `llm_review` abstains). It is checked both ways: a key that names no row, or a listed row a
  passing scenario reaches, is a problem (exit code 1).
- Data → catalog: from a run's actual outcomes (`DocActual`, `MonthActual`), the map lists
  `define_articol` / `define_class` / `define_module` questions, `needs_human` with no articol,
  a job minted that never binds one, an upload refused at the door, and a close blocker whose
  head is no control id. The scenario runner (WP-71) produces these outcomes.
- Today: 11 of 22 articole, 10 of 27 HITL kinds, 21 of 26 control outcomes, 4 of 10 write
  modules, all 8 filings and both close kinds are reachable; none has a scenario yet.
- Tests: `tests/test_coverage.py`.

### WP-70 Synthetic firms and books
- `poarta_contabila/synthetic/`: seeded generators, invented data only (CUIs `1001…` firms,
  `2001…` partners, all with valid check digits; IBANs on the non-existent bank code `AAAA`;
  names SINTETIC / FURNIZOR / CLIENT / EXEMPLU). The same `(firm, period, seed)` gives the same
  bytes: zip members and workbook properties carry fixed timestamps.
- `firms.py` — five firms whose CO.DiT differs where the paths do: `platitor` (profit, staff),
  `incasare` (TVA la încasare → `close_tva_incasare`), `neplatitor` (micro, buys EU services),
  `abroad` (payer, `cross_border: mixed`), `bonuri` (receipts, expense reports, payroll).
  Between them every filing falls due. `firm(key, book_of_record="nextup")` is a NextUp twin
  under its own CUI (one book of record per firm-period, A2).
- `docs.py` — SPV zips (invoice + `semnatura_`) in and out, credit notes both sides (with
  `BillingReference`), invoices from abroad (UBL XML, reverse charge, EUR; and PDF), bonuri
  (PDF, with and without our CUI), bank statements (`POST /extras` body: header, tables in
  the bank's number format, a real PDF), expense reports (container PDF, parts, and the
  `decont_split` answer naming each part by the hash of the file a person would upload),
  workings, a payroll statement. `Gen` draws one firm-month and numbers it without repeats.
- `books.py` — `Book` posts documents the way SAGA posts them, not the way this system
  expects: VAT on 4426 / 4427, on 4428 for TVA la încasare (moved to 4426 / 4427 as it is
  paid), into the cost for a neplătitor; reverse charge 4426 = 4427 for a payer, nothing
  invented for a neplătitor (WP-D3 open); bank lines one journal line per invoice settled;
  bonuri against 542 (in a report) or 5311; payroll on 641 / 646 / 421 / 431x / 444 / 436.
  Renders only the shapes in `fixtures/sink/`: SAGA registru jurnal, balanță, jurnal de
  cumpărări / vânzări (a `Baza 0%` column only when a 0 % base exists); NextUp journal and
  balance; the SPV register. Journal types `Diverse`, `Casa`, `Salarii` for notes, cash and
  payroll are `[de confirmat]` on a real book (only `Intrari` / `Iesiri` / `Banca` are read
  as documents).
- `months.py` — `month(firm, period, seed, defect)`: a standard month (purchases incl. one from
  a supplier that is not a VAT payer, sales, a statement that pays, collects and charges a
  fee, plus what the profile adds), its uploads in order and its exports. Ten named defects,
  one each: missing from the books, in the books with no document, amount differs, VAT
  differs, posted another way, duplicate upload, a late document of the prior month, storno of
  a sale, one bank line paying two invoices, a partial payment. `Book.skew_analytic` breaks
  an M1 tie on the balanță.
- Checked: every firm × every defect reads through the real parsers (`parse_ubl`,
  `parse_statement`, every export reader); a clean month's books hold exactly its documents
  and its M1 ties hold; the decont answer passes `check_split`.
- Tests: `tests/test_synthetic.py`.

### WP-71 Scenario runner
- A scenario is YAML in `fixtures/scenarios/` (closed schema, named after its file): a firm
  and month of `poarta_contabila/synthetic` with a seed and at most one named defect; how the
  books stand when documents arrive (`books: agent | in_books | none`; `report_pack: true`
  also uploads SAGA's purchase / sales journals); scripted answers per question kind; and
  `expect:` — per document its source doc, job kind, articol de cale, questions in order,
  final status, SAGA mouth, PRE and POST profiles and POST verdict; per month the close
  kind, `material`, the blockers by head (a control id or the words before `:`), control
  outcomes, filings due, receipts, the recon and close questions and the V2 action.
- `python -m poarta_contabila.scenarios [--local | --base-url URL] [names] [--json | --actual]`
  drives the operator API like the smoke run (a fresh in-memory runtime per scenario, dry):
  tenant, CO.DiT, rules; the books as SAGA holds them before our packages; uploads (SPV zips,
  statements, expense reports and their split, an XML part's zip after the split); a person's
  answers (approve invoices; bind a bank line to the partner and invoice it settles); a
  **simulated SAGA agent**, labelled in every report: pull, backup label, import, the books
  uploaded again as after the import, a validated snapshot (net / VAT / partner CUI only with
  the report pack, ARCHITECTURE §13); then reconcile_sink, monthly_close (hold, or file and
  `v4_codit`), filings and receipts, the period's controls. Every expectation is compared;
  any difference fails. `--actual` prints what happened in `expect:` shape, for review.
- The job view (`GET /jobs/{id}`) now shows its PRE verdict and profile; POST settlements in
  `GET /recon` carry their profile (additive).
- The coverage map runs every scenario by default (`--no-run` to skip): a passing scenario's
  expected path names its rows; what actually happened feeds data → catalog.
- Found and fixed in its own commit: a packaged bank line never acked and POST never found
  its posting — SAGA holds it under the bank's reference, in `Banca`
  (`saga_xml.packaged_number`).
- First scenarios: `platitor_clean` (filed, every control passing, all documents through the
  agent), `platitor_posted_another_way` (VAT carried in the cost: POST accepts it, C0 does
  not), `bonuri_decont` (the expense report; bon parts stall as `job_bon` — a WP-73 finding).
- Found for WP-73 (not changed): with the report pack's journals uploaded the eye holds no
  bank documents, so no statement line is found in the books; bon parts of an expense report
  mint a job that never binds and that the close never counts.
- Tests: `tests/test_scenarios.py` (every scenario passes locally; runner mechanics).
