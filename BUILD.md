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
| WP-17 | parked | — | Engagement backlog / `chat:` face (the review page is WP-66, not this face: A8 §6) |
| WP-18 | parked | — | Take-on / year-end / D406 producer / FX engine |
| WP-D3 | decision | WP-11 | Non-payer RC books: 4423 vs 446x on copy-firm note |
| WP-D4 | decision | WP-35 | The EU route per model family (client data): Vertex `eu` for Gemini; Scaleway or OpenRouter EU for GLM; no EU route for Jev |
| WP-19 | done | WP-13 | Bank mouths `incasare_xml` / `plata_xml` from the SAGA manual (R1) |
| WP-20 | done | WP-10 | Jev Layer 1 `v3_judge` + Layer 2 `v2_declaration_gate`; live through OpenRouter's Decisions endpoint (synthetic only) |
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
| WP-41 | done | WP-40 | Model tiers (Lite everyday, Flash strong), daily limits, second run on a read that does not tie |
| WP-42 | done | WP-41 | Lite first always; a statement no model can read waits and is read later; reading budget |
| WP-43 | done | WP-42 | The operator's choice when every tier is spent: wait, reserve models until midnight, or set aside |
| WP-44 | done | WP-37 | The reading evaluation says why a read does not tie, and how many rows the model returned |
| WP-45 | done | WP-44 | A balance or total row is not a line, whatever column its label is in; the brief keeps balances out of tables |
| WP-46 | done | WP-08, WP-13 | C0 counts a statement line's counterpart: from its binding, or one matching posting in the books |
| WP-47 | done | WP-29, WP-46 | The smoke run closes a clean August (books hold exactly its documents); September reopens on a lock mismatch |
| WP-48 | done | WP-43 | Reserve order from the 2026-10-03 evaluation: 3.5 Flash, 3 Flash (preview), 3.6 Flash last |
| WP-49 | done | WP-20 | One OpenRouter key for Jev and System Two: `OPENROUTER_SYS2_API_KEY` |
| WP-50 | done | WP-32, WP-49 | System Two sender: a person's question comes with a checked explanation (DeepSeek through OpenRouter) |
| WP-51 | done | WP-50 | The explain roles move to GLM (`z-ai/glm-5.3`): DeepSeek's provider trains on prompts |
| WP-52 | done | WP-51 | GLM answers: reasoning off, a larger budget, JSON read from inside prose, a bad answer quoted |
| WP-53 | done | WP-51 | Provider data policies read daily; approved alternates by themselves; the operator's choice when none passes (00_LAW §8 A7) |
| WP-54 | done | WP-52 | GLM 5.3 needs reasoning: low effort, left out of the answer, 6000 tokens |
| WP-55 | done | WP-49 | Jev back on its own key: `OPENROUTER_SYS1_API_KEY` (System Two keeps `OPENROUTER_SYS2_API_KEY`) |
| WP-56 | done | WP-55 | `GET /model-keys`: each OpenRouter key's spend and what is left, read from OpenRouter; the account's with a management key |
| WP-57 | done | WP-54 | Free-tier token cap: diagnosed `is_free_tier` per-request budget; resolved by adding credits (`is_free_tier` → `false`); `max_tokens` stays 6000 |
| WP-58 | done | WP-57 | System Two brief: never an empty explanation, never an empty field cited; an answer off the card is asked once more with its reason |
| WP-59 | done | WP-58 | `POST /model-roles/{role_id}/compare`: main pin vs each approved alternate on the latest synthetic questions, first answer only; nothing recorded |
| WP-60 | done | WP-59 | A placeholder explanation is refused; reasoning settings sent to GLM only; a reasoning-only answer is named; compare defaults to one run |
| WP-61 | done | WP-60 | `compare` one candidate on one question per request (`candidate`, `skip`): the edge closes at 300 s |
| WP-62 | done | WP-61 | An answer wrapped once around the card's fields is unwrapped; a cited fact with an empty value is dropped, not refused |
| WP-63 | done | WP-62 | System Two answers in English, Romanian domain words kept; each question carries `as_of`; the model's own memory of Romanian rules never wins over the input |
| WP-64 | done | WP-63 | Smoke leaves a September invoice (`AB 0102`) at `v3_approve` and reports its System Two explanation |
| WP-65 | done | WP-64 | A close or reconcile run stopped between nodes (process died) continues when started again |
| WP-66 | done | WP-65 | Review page (00_LAW §8 A8): `GET /inbox/{cui}/{period}` and `/review`, a thin page that sends each answer unchanged to its resume route |
| WP-67 | done | WP-66 | Expense-report splits (`decont_split`) on the review page: a batch index per firm; parts named by a hash the browser computes |
| WP-68 | done | WP-67 | Tidy: done WPs' details moved to `docs/BUILD_DONE.md`; INDEX, ARCHITECTURE §11 and the loader brought up to date |
| WP-69 | done | WP-68 | Coverage map: every reachable catalog row × the scenarios and tests that drive it, both ways |
| WP-70 | done | WP-69 | Synthetic firms and books: seeded documents per source doc, and SAGA exports that agree (clean and with named defects) |
| WP-71 | done | WP-70 | Scenario runner: YAML scenarios with expected paths, run over HTTP with a simulated SAGA agent |
| WP-72 | done | WP-71 | Catalog → data: a scenario for every reachable articol de cale, HITL kind, control, recon profile and filing |
| WP-73 | done | WP-71 | Data → catalog: realistic months run blind; every gap becomes a proposed draft row in `docs/CATALOG_GAPS.md` |
| WP-74 | done | WP-72, WP-73 | A small live sample of the new paths on production's synthetic firms, within a spend limit |
| WP-75 | done | WP-73 | `M1_8_4428_open` computed: 4428 still open on unpaid la-încasare documents vs bal(4428) (G7) |

## WP details

Open work packages only. The details of every `done` WP (what was built, why, what was
checked) are in `docs/BUILD_DONE.md`: read it only to trace why something is as it is.

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

### The synthetic-data program (WP-69 – WP-74)
Owner, 2026-10-03: test the pipeline end to end, not just the model roles, on many angles.
Two approaches, both used: **catalog → data** (an articol de cale on a path says where synthetic
data must exist) and **data → catalog** (synthetic data run through the paths shows which
articole, source documents, controls or HITL kinds are missing). Coverage today: 22 articole de
cale (all `draft`), 6 named in a test, none named by the smoke run; 17 of 27 HITL kinds, 9 of 13
controls and 6 of 10 write modules named in a test; synthetic documents are one UBL invoice, one
credit note and a few SAGA exports.

Rules for every WP below: invented data only (CUIs pass `cui_is_valid`; no real names, IBANs or
amounts); new firms, never smoke's `1000009` or its months; same seed → same bytes (fixed zip
timestamps, as in `smoke.spv_invoice`); `MODEL_CALLS=dry` unless the WP says live; no SAGA XML
tag or export shape beyond what `fixtures/` already holds (AGENTS hard ban); WriteModules stay
`draft` (a simulated agent is never copy-firm proof); open decisions stay open (WP-D3:
`foreign_rc_neplatitor` is always-HITL; WP-D4); a catalog change enters only as `status: draft`
after the owner accepts it, and graph topology, interrupt kinds or watched accounts need a
00_LAW amendment (§7): list those, do not make them.

### WP-D3 Non-payer reverse charge books (`decision`)
- Ask: expected sink accounts for `foreign_rc_neplatitor` — harvest Y1 used 446x; some SAGA books use 4423.
- Until answered: articol exists, `expect_accounts: []`, `nota_nc_dbf` always-HITL, or SAGA-native + `explained_rule`.
- Do not silently fill 4423 or 446.

### WP-D4 The EU route per model family (`decision`)
Owner, 2026-10-03: kept open until the work reaches client data; synthetic firms go on as set up.
Research of 2026-10-03 (sources below). Until the owner decides, every role keeps `eu_route: null`
and a client tenant is refused by every model role (Jev: cautious values and a person; System
Two: the question without an explanation; reading: the statement's tables must be sent).

- **Document reading (Gemini) → Vertex AI, EU multi-region `eu`.** Every model the catalog pins
  (`gemini-3.5-flash-lite`, `-3.1-flash-lite`, `-3.8-flash`, `-3.7-flash`; reserve `-3.5-flash`,
  `-3.6-flash`) is GA on the `eu` multi-region, which Google ties to EU ML processing; a
  regional endpoint alone does not guarantee it. Zero retention: turn off caching and get the
  abuse-monitoring exception (invoiced billing) or an enterprise ZDR contract
  (`docs/EU_VERTEX_SETUP.md` §D). Code: `EU_LOCATIONS["vertex"]` lacks `eu`; no Vertex transport.
- **System Two (GLM) — two candidates:**
  - **Scaleway Generative APIs, `glm-5.2`** (one version behind the `z-ai/glm-5.3` pin; also
    `deepseek-v4-flash-0731`). Paris; zero data retention by default; no training; a French
    company, outside the US CLOUD Act; OpenAI-compatible chat. Caveats: an automatic cache of
    intermediate values (not prompt text) that cannot be turned off; the full request may be
    kept up to 2 weeks after a server error (500).
  - **OpenRouter EU in-region (`https://eu.openrouter.ai/api/v1`), `z-ai/glm-5.3`** on Mistral or
    Inceptron (Kimi K2.6 on Inceptron). Keeps the current pin and sender, but needs OpenRouter's
    Business or Enterprise plan (price from sales), and OpenRouter, Inc. (US) stays in the chain.
- **System One (Jev): no EU route.** `typesafe/jev-1.13` is served only by TypeSafe AI, Inc. (US;
  operated from the US West Coast per third-party listings; its DPA names no location and uses
  EU SCC Module 2). Zero data retention for enterprise customers on request. It is not on
  OpenRouter's EU list. Options: (a) no Jev on client data, its decisions go to a person (how the
  code behaves today); (b) amend invariant 5 to allow TypeSafe under SCCs plus an enterprise ZDR
  contract and a transfer assessment; (c) an EU model in System One's place for client data,
  evaluated against Jev on synthetic data first.

Sources: Scaleway supported models (validated 2026-08-14) and Generative APIs data privacy
(`github.com/scaleway/docs-content`, `pages/generative-apis/reference-content/`); OpenRouter
sovereign AI guide (`openrouter.ai/docs/guides/features/sovereign-ai`) and its models API with
`region=eu` / `eu.openrouter.ai` (read 2026-10-03: 70 EU-eligible models); TypeSafe legal and
DPA (`docs.typesafe.ai/legal`, `typesafe.ai/legal/data-processing`); Gemini EU listings
(`opper.ai/models/eu/gemini`) and Google's data residency page (not readable from the session).

**Pricing, read 2026-10-03** (per million tokens, before tax; EUR → USD at the ECB rate of
2026-10-02, 1 EUR = 1.1225 USD):

| Role / model | OpenRouter (the pinned provider) | Scaleway serverless, Paris |
|---|---|---|
| System Two `z-ai/glm-5.3` on Z.AI (alternate: same on Together) | $1.40 in / $4.40 out | not served |
| nearest on Scaleway: `glm-5.2` | Z.AI $1.40 / $4.40 | €1.80 / €5.50 (≈ $2.02 / $6.17); batch €0.90 / €2.75 (≈ $1.01 / $3.09) |
| System Two alternate `moonshotai/kimi-k2.6` on Moonshot | $0.95 / $4.00 | not served |
| System One `typesafe/jev-1.13` on TypeSafe | $0.042 / $0 | not served |
| Document reading (Gemini, direct on Google AI Studio) | — | not served |
| `deepseek-v4-flash` (dropped: its OpenRouter provider trained on prompts) | $0.09 / $0.18 (DeepInfra) to $0.44 / $1.32 (Cloudflare) | €0.40 / €0.80, cached €0.08 |

- Per System Two explanation (≈ 1,550 input / 610 output tokens, the WP-74 live sample):
  OpenRouter ≈ $0.0049 at list price (≈ $0.0042 as billed for those 5 calls); Scaleway live
  ≈ $0.0069 (about 1.4×); Scaleway batch ≈ $0.0035 (about 30 % below OpenRouter).
- OpenRouter: "no markup on inference pricing (however we do charge a fee when purchasing
  credits)" — the percentage was not on the FAQ page. Its EU in-region route
  (`eu.openrouter.ai`) needs a Business or Enterprise plan, priced on request.
- Scaleway: "You benefit from a free tier on the first 1,000,000 tokens" (reads as once per
  account); "All requests performed using Batches API are priced with a -50% discount".
- Scaleway Batches API (how-to validated 2026-02-17; FAQ): a JSONL file in an Object Storage
  bucket of the same project, one model per file ("The `method`, `url`, and `model` fields must
  remain consistent across all requests"); "We aim to process any batch within 24 hours.
  After this delay, batch processing will be stopped, and any remaining unprocessed queries
  will not be billed"; no rate limit. No model is excluded from batching in the docs, but none
  names `glm-5.2` either: **[de confirmat]** with one small test batch (no Scaleway key in the
  build sessions).
- Owner, 2026-10-03: with several clients, System Two's explanations could be batched on
  Scaleway (EU, Paris), bringing its cost below OpenRouter's. What that implies:
  - only System Two moves: Jev and Gemini are not on Scaleway, and Jev's `v3_judge` sits on the
    path to every approval, so a 24-hour wait there would stall the flow;
  - an explanation arrives up to 24 hours after its question (e.g. a nightly batch for the
    questions still waiting); until then the question shows without one, as today when none
    comes back;
  - requests a batch drops after 24 hours are sent again or left unexplained;
  - input and output pass through our own Scaleway bucket: deleting them after each batch is
    ours; Scaleway may keep a full request up to 2 weeks after a server error (above);
  - `glm-5.2` reasons at `max` by default: each line sets low effort, as the current sender
    does; and it is one version behind the GLM 5.3 pin, so it is compared with it on the
    synthetic questions first (`POST /model-roles/{role_id}/compare`).

Sources (2026-10-03): `openrouter.ai/api/v1/models/{model}/endpoints`, `openrouter.ai/docs/faq`;
`scaleway.com/en/pricing/model-as-a-service/`; `github.com/scaleway/docs-content`
`pages/generative-apis/` (`faq.mdx`, `concepts.mdx`, `how-to/use-batch-processing.mdx`);
`ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml`.

**LangSmith (tracing and evaluation), read 2026-10-03** — the owner asked whether to use it,
host it on Railway, migrate to it, and use its EU option on client data.

- Self-hosting: "Self-hosted LangSmith is an add-on to the Enterprise plan … Contact our sales
  team if you want to get a license key". It installs on Kubernetes (Helm) with ClickHouse
  (traces), PostgreSQL, Redis and blob storage. Railway is not Kubernetes, and a single VPS
  would mean running a cluster for an Enterprise product: in practice it is LangChain's cloud
  or an Enterprise contract. LangGraph itself (open source) stays on Railway either way.
- Cloud plans: Developer $0 (1 seat, 5k base traces a month), Plus $39 per seat (10k base
  traces), Enterprise custom ("Self-hosted and hybrid deployment options"). Base traces are
  kept 14 days, extended traces 180 days (extra fee).
- EU: "organizations on https://eu.smith.langchain.com are in GCP EU"; regional instances on
  all plans, free included; "pricing is the same across supported cloud regions"; paid in USD.
  GDPR, SOC 2 Type 2, a DPA on request. But: "We do not have a legal entity in the EU for
  customer contracting today" — a US contracting party, the same concern as OpenRouter above.
- Migrating what is built: not worth it. The answer log (who answered, append-only), the
  model-call record (role, pin, card hash, synthetic guard), the catalog, gates, scenarios and
  coverage map are the system's record and law, kept in our Postgres; a trace store with
  14 / 180-day retention does not replace them. What LangSmith adds is side-by-side model
  evaluation (better than `POST /model-roles/{role_id}/compare`) and a run-by-run trace view:
  an addition, not a migration.
- Client data: a trace holds the whole document (CUIs, amounts, partners), so LangSmith would be
  a new place client data goes — under invariant 5 a dated 00_LAW amendment, a DPA and a
  transfer assessment. Little gain for explanations (what each model was given and answered,
  under which card, and what the person decided are already recorded; its online scoring
  would be another model reading client data, and its annotation queues a second review
  surface beside the review page, which A8 keeps free of outside services). More gain if
  multi-step AI work on client data is built later: decide it then, with this WP, against a
  self-hostable open-source tracing tool on our own EU hosting (not checked yet).
- Recommendation (2026-10-03): migrate nothing now. If the WP-D4 model evaluations want it
  (Scaleway `glm-5.2`, Kimi, an EU model in Jev's place), the hosted EU free tier on synthetic
  data only, fed from `fixtures/scenarios/`: no amendment, no migration.

Sources (2026-10-03): `docs.langchain.com/langsmith/self-hosted`,
`docs.langchain.com/langsmith/regions-faq`, `www.langchain.com/pricing`.

## Definition of done for v1

WP-00–WP-12 green. WP-13 optional. Parked WPs untouched. No `Journal.post` in the tree. No SYSDBA in env samples. Catalogs that shipped without fixtures remain `draft`.
