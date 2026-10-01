# GROK BOT BRIEF — Romanian Accounting Loop (CO.DiT / V1–V5)

**Language of this file:** English (operating language for the agent). Romanian fiscal terms stay in Romanian and must not be translated away (`factură`, `chitanță`, `notă contabilă`, `TVA la încasare`, `plan de conturi`, `e-Factura`, `SAF-T`, `SPV`, `ANAF`, `CUI`).

**Human one-liner (RO):** Acest fișier îl dai unui Grok Bot ca unică sursă de adevăr. Botul cercetează ce nu e încă dovedit, scrie arhitectura și codul, și nu se oprește până fiecare legătură e fie **cod**, fie **instrucțiune verificată pe documentație oficială** (nu presupusă), astfel încât tu să poți seta cap-coadă și sistemul să pornească.

---

## 0. How the receiving Grok Bot must work

You are not asked for opinions. You are asked to **close the graph**.

### Operating loop (mandatory)

1. Read this brief end to end. Treat §1 as frozen.
2. Build a **connection graph**: every box, every arrow, every secret, every schema.
3. For each node and each edge, classify it as exactly one of:
   - `CODE` — types, functions, env names, file paths exist in the repo.
   - `INSTRUCT` — a human must click / pay / request access. Steps are copied from official docs, with URLs, not invented.
   - `RESEARCH` — official source not yet read in this run. You may not invent the missing piece.
4. Execute `RESEARCH` first. Use official docs listed in §6. If a URL is stale, search from the official domain and replace the URL in this file’s successor (`RESEARCH_LOG.md`).
5. After research: write `CODE` or write `INSTRUCT`. Never leave a “we’ll figure it out”.
6. Review the graph again. A node with an unlabeled edge is a defect.
7. Stop only when §10 Definition of Done is true.

### Hard bans

- Do not let an LLM (Grok included) choose posting target, document type, TVA treatment, or auto-post vs hold. That is **Jev** or **deterministic code**.
- Do not send raw model JSON to NextUp or SAGA. Canonical document + adapter only.
- Do not invent NextUp endpoints, SAGA XML tags, ANAF e-Factura fields, or Railway env var names. Open the official page.
- Do not put fiscal source PDFs on a public URL. Railway Buckets are private.
- Do not treat MongoDB as the statutory ledger. NextUp (primary) or SAGA is the ledger.
- Do not implement TypeScript LangClaw. LangClaw is Python 3.11+.
- Do not “close V2 specializations on the first loop”. First loop fills V5 + V3. Declaration close is a later pass.

### What you must emit (files)

Create / update in the project root (or `artifacts/` if no repo yet):

| File | Purpose |
|---|---|
| `RESEARCH_LOG.md` | Every research item: question, official URL, quote/paraphrase, date accessed, implication for code or instruct |
| `ARCHITECTURE.md` | System diagram + data flows V1–V5 + CO.DiT lifecycle |
| `CONTRACTS.md` | Canonical JSON schemas, Jev question packs, env var table, collection names, bucket key layout |
| `SETUP.md` | Human runbook: accounts, keys, Railway, Atlas, NextUp sandbox, SAGA, RunPod, Jev, xAI — each step sourced |
| `AGENTS.md` | Short rules for future coding agents |
| `TODO.md` | Remaining `RESEARCH` / `INSTRUCT` / `CODE` with owners (bot vs human) |
| Python package `roacc/` | Code for everything classified `CODE` |

If the human only handed you this brief and no repo, scaffold the repo first, then fill it.

---

## 1. Frozen decisions (do not reopen unless the human overrides in writing)

These came from the project owner’s conversation and notebook (Sep 2026).

| Decision | Value |
|---|---|
| Product | Bidirectional Romanian accounting loop around **CO.DiT**, not a chatbot that “does bookkeeping” |
| App logic | **LangClaw** on Railway Web Service — Python framework (`pip`/`uv add langclaw`), LangChain + LangGraph + deepagents |
| Language | **Python 3.11+** only for the Claw |
| Sorter / router / classifier / semantic brancher | **Jev** (TypeSafe AI System One), `POST https://api.typesafe.ai/v1/systemone` |
| Heavy generation / VLM / OCR | **RunPod Serverless** + open-weight models (vLLM). Called only after Jev says extraction is needed |
| Reasoning text, HITL talk, construction | **Grok** (xAI API). Explains and asks. Does not post |
| Objects | **Railway Buckets** (S3-compatible, private) |
| Operational DB | **MongoDB Atlas** |
| Statutory package | **NextUp API primary**, **SAGA secondary** (XML official schema; SAGA Online API only if research confirms access) |
| Conversation / workflow state inside LangClaw | LangClaw checkpointer (SQLite local, **Postgres** extra on Railway). Not Mongo |
| Notebook vectors | V1 ANAF as-is · V2 declarations top-down · V3 source-doc bottom-up · V4 fund-looking / CO.DiT impact · V5 source-doc state |
| Center object | **CO.DiT** = company fiscal universe, versioned **monthly**, stored in Mongo, not in NextUp |
| Exit path | ACC decision + reasoning/backup/citations + normalised data → DET sorter × CO.DiT → package normalizer → Import \| API \| Manual → ACC SYST → **action + intent check** |
| Formula | `context × prompt × model + coding (deterministic checks) + human (HITL) + GPU` under **privacy/data** |
| Channel for accountants | LangClaw channel (Telegram extra and/or WebSocket). TBD by human in SETUP — default WebSocket + HTTP if Telegram token missing |
| CO.DiT grain | **CUI × punct de lucru** if V1 shows workplaces; otherwise CUI. Research ANAF / NextUp workplace model before coding the key |

---

## 2. What the system is

A monthly fiscal grounding machine for one or many Romanian firms.

```
channels (accountant)
        │
   LANGCLAW  (Railway web service, Python)
        │
   ┌────┼──────────────┬──────────────┐
   Jev   Grok (text)    RunPod (GPU)
   branch rationale     OCR / extract
        │
   Mongo Atlas          Railway Buckets
   CO.DiT, jobs, maps   inbox / anaf / exports / audit
        │
   adapters
   NextUp API  │  SAGA XML (and Online API if proven)
        │
   intent check (Jev) ──► back into V5 / V1
```

**CO.DiT** (from the notebook): “company details; the fiscal universe in which we ground subsequent decisions; status updated monthly” from:

- V1 post facto = ANAF as-is + ANAF state folders
- V4 fund looking = CO.DiT variables reviewed through accounting data; criteria that affect CO.DiT from V2 / V3 specializations

Arrow V3 → V4: “know the fiscal impact on [CO.DiT]”.

### Vector meanings (do not flatten)

**V5 — source-doc STATE**  
File identity + what was already done for this CUI / rights from the first moment. Feeds V3. Can answer V3 queries without a full rerun. Lives in Bucket + `documents` collection.

**V3 — bottom-up (notebook: “content synthesizing decl. but bottom up”)**  
1 source doc → 2 specialized classifier → 3 specialized nomenclator → 4 matcher (**explicit notebook note: area for flow improvement with ERP**).  
Then three classification lenses: (1) acc. history (2) fiscal + acc. law (3) both. Then **judge**, optionally again with trimmed context.

**V2 — declarations top-down**  
Declaration specialization → subspecializations + diligence tasks. User aggregator on declared data. Dynamic balance / close list / quick-check loops. Correlation → JE audit → source-doc-to-JE audit in the context of the declaration. Bridge to V3/V4. Mutual guardrail across specializations (“self-watch”). Another classification exists at V3/V4 — do not duplicate it inside V2.

**V1 — ANAF state folders**  
ANAF as-is. Specialized contra-agent over Facturi / Încasări / Declarații. Nomenclator agent + aggregator agent + reviewer agent. Output: status-as-at on **tracked vs untracked** criteria. Then interpret / implications / present / plan (Grok text, after Jev scores).

**V4 — fund looking**  
Which CO.DiT fields change this month, given V1+V2+V3. Jev chooses the field patch; LangClaw applies a versioned Mongo update. Grok writes the human-readable “why”.

---

## 3. Connection graph the bot must close

Every line is an edge that must become `CODE` or `INSTRUCT`.

### Runtime path (one inbound file)

1. Upload / email / pull → LangClaw HTTP or channel  
2. Bytes → Railway Bucket `tenants/{cui}/{punct}/{period}/inbox/{jobId}/{filename}`  
3. Mongo `jobs` + `documents` row (V5)  
4. Deterministic text extract (PDF text, XML). If empty → Jev noul `needs_ocr` → RunPod VLM  
5. Jev V3 pack: doc_type, direction, tva_treatment, stock_flag, storno_flag, duplicate_risk, posting_mode  
6. Schema-validate extracted JSON into **CanonicalDocument**  
7. Matcher: Mongo maps `partners` / `articles` / `account_maps`; if miss → hold or NextUp-create (gated)  
8. Jev quality pack on canonical JSON + maps  
9. Optional Grok rationale (trimmed state only)  
10. Deterministic checks: CUI checksum, TVA lines == header, hash dedupe, leaf account  
11. Jev DET sorter: target `nextup|saga|both|hold`, channel `api|import|manual`  
12. Normalizer writes NextUp payload and/or SAGA XML into `.../exports/`  
13. Adapter posts or stages  
14. Jev intent check on adapter response  
15. Update V5 + exceptions + notify channel if hold/fail  

### Monthly path

16. V2 declaration workflow (which packs are due)  
17. V1 ANAF pull into `.../anaf/`  
18. V4 CO.DiT patch proposal → HITL → version bump  
19. Sync-back from NextUp (invoices, balances, PDF, cancel) and from SAGA ack if any  

### Construction path (this bot)

20. Research official APIs  
21. Write contracts + code stubs + SETUP  
22. Human executes SETUP  
23. Thin vertical slice on dummy XML/PDF  
24. Only then wire live sandbox NextUp  

---

## 4. Code contracts to define (names are normative)

Implement these as Pydantic v2 models in `roacc/contracts.py` (or split modules). Field lists below are the **minimum**; extend only after research.

### 4.1 Identity

```text
TenantKey = cui: str + punct_de_lucru: str | None
Period    = year: int + month: int   # fiscal month, Europe/Bucharest
JobId     = uuid4
DocHash   = sha256(canonical_bytes)
```

### 4.2 CO.DiT (`co_dit` collection, one current + history)

```text
CoDit
  key: TenantKey
  version: int
  as_of_period: Period
  identity: { legal_name, cui, nr_reg_com, vector_fiscal, puncte_de_lucru[] }
  tva: { regime: normal|incasare|scutit|neplatitor, rates_in_use[], next_deadline? }
  anaf_as_is: { efactura_status, last_spv_sync, declarations: { code: status }, rejects[] }
  internal_as_is: { trial_balance_ref, ar_ap_treasury_notes }
  maps_ref: { partners_updated_at, articles_updated_at, accounts_updated_at }
  tracked_criteria: [{ id, value, source: v1|v2|v3|v4, job_id }]
  untracked_criteria: [{ id, note }]
  v4_delta: [{ field, old, new, reason_job_ids[], approved_by }]
  created_at, updated_at
```

Jev does not write this document. LangClaw applies a `CoDitPatch` only after Jev choice + optional HITL.

### 4.3 CanonicalDocument (after V3, before adapters)

```text
CanonicalDocument
  tenant: TenantKey
  job_id, source_bucket_key, source_hash
  doc_type: factura_emisa|factura_primita|proforma|chitanta|bon_fiscal|nir|extras_bancar|nota_contabila|contract|stat_plata|efactura_xml|unknown
  direction: sales|purchase|treasury|payroll|inventory|closing|ignore
  dates: { issue, due, tax_point }
  parties: { supplier{name,cui}, customer{name,cui} }
  lines: [{ desc, qty, um, unit_net, net, vat_rate, vat, sku?, account_hint? }]
  totals: { net, vat, gross, currency }
  tva_treatment: tva_19|tva_9|tva_5|tva_0|scutit|neimpozabil|tva_incasare|reverse_charge|unknown
  flags: { storno, anulare, stock_movement, already_posted }
  maps: { nextup_partner_id?, nextup_article_ids[], saga_partner_code?, saga_article_codes[], accounts[] }
  jev: { packs: { name: raw_answer } }
  quality: { extraction_score, posting_risk, duplicate_risk }
```

### 4.4 Job state machine

```text
received → classified → extracted → mapped → gated → posting → acked → synced
side: needs_human | rejected | retry | duplicate
```

Transitions: Jev answers + adapter HTTP + deterministic predicates. Persist on `jobs`.

### 4.5 Jev packs (call `jev-latest`, text/JSON state only — Jev has no image input)

Official: https://docs.typesafe.ai/api.md  
SDK: `uv add typesafe-sdk` · env `TYPESAFE_API_KEY`  
Primitives: Choice (≤255 options), Score (2–10 levels), Noul (probability 0–1).  
Context budget: 64k tokens / request; 32k for state + longest question.  
Price research-check: input billed, output free (confirm on https://docs.typesafe.ai/models.md).

Pack files live in `roacc/jev_packs/`. Each pack is a typed Python structure, not a free prompt.

**Pack `v3_classify`**  
- choice `doc_type` (enum above)  
- choice `direction`  
- choice `tva_treatment`  
- noul `is_storno`, `is_anulare`, `stock_applies`, `looks_duplicate`, `cui_plausible`  
- score `extraction_quality` (low…high, 5 levels)  
- score `posting_risk` (5 levels)  
- choice `posting_mode`: auto_post | draft_only | needs_accountant | reject  

**Pack `v3_judge`** (after matcher)  
- noul `maps_sufficient`  
- noul `totals_consistent`  
- choice `lens_agreement`: history | law | both | conflict  
- score `confidence_to_post`  

**Pack `det_sorter`**  
- choice `target`: nextup | saga | both | hold  
- choice `channel`: api | import | manual  
- noul `requires_hitl`  

**Pack `intent_check`** (adapter response + intended CanonicalDocument)  
- noul `posted_as_intended`  
- noul `retryable`  
- choice `followup`: sync_ok | open_exception | rewrite_map | notify_human  

**Pack `v2_declaration_gate`**  
- choice `declaration`: D300 | D394 | D390 | D100 | D406_SAFT | other | none  
- noul `books_support_declaration`  
- score `gap_materiality`  

**Pack `v4_impact`**  
- choice `co_dit_action`: no_change | patch_tva_regime | patch_vector | patch_workplace | patch_threshold | needs_human  
- noul `anaf_diverges_from_internal`  

Default HITL policy (tune later, keep in config not code constants only):  
`requires_hitl ≥ 0.35` OR `posting_risk ≥ 4` OR `maps_sufficient < 0.7` OR `lens_agreement = conflict` → `needs_human`.

### 4.6 Mongo collections

`tenants` `co_dit` `co_dit_history` `partners` `articles` `account_maps` `documents` `jobs` `postings` `exceptions` `audit`

Indexes at minimum:  
`{cui, punct_de_lucru}`, `{tenant_key, hash}`, `{tenant_key, status, due_at}`, `{job_id}`.

Driver: **Motor** async (`motor.motor_asyncio.AsyncIOMotorClient`) for LangClaw async tools.  
Official: https://www.mongodb.com/docs/drivers/motor/

LangClaw’s own thread memory: **not** these collections. Use LangClaw checkpointer (Postgres extra in prod).

### 4.7 Bucket key layout (Railway Buckets, S3 API)

Official: https://docs.railway.com/storage-buckets.md · https://docs.railway.com/guides/storage-buckets.md  

Private by default. Presigned PUT for upload. Serve downloads only through LangClaw.

```text
tenants/{cui}/{punct_or__}/{period}/inbox/{jobId}/{filename}
tenants/{cui}/{punct_or__}/{period}/canonical/{jobId}.json
tenants/{cui}/{punct_or__}/{period}/exports/nextup/{jobId}.json
tenants/{cui}/{punct_or__}/{period}/exports/saga/{xml_filename}
tenants/{cui}/{punct_or__}/{period}/anaf/{kind}/{filename}
tenants/{cui}/{punct_or__}/{period}/audit/{jobId}/{ts}.json
```

SAGA export filenames must follow official rules after research (see §6.5). Known from SAGA manual: invoices `F_<cod-fiscal>_<numar-factura>_<data-factura>.xml`. Confirm before coding the renderer.

### 4.8 Environment variables (normative names)

```text
# LangClaw
LANGCLAW__AGENTS__MODEL=openai:grok-4.7
# If LangClaw cannot native-xAI, point OpenAI-compatible client:
OPENAI_API_KEY=${XAI_API_KEY}
OPENAI_BASE_URL=https://api.x.ai/v1
XAI_API_KEY=

# Jev
TYPESAFE_API_KEY=
TYPESAFE_DEFAULT_MODEL=jev-latest

# Data
MONGODB_URI=
MONGODB_DB=roacc
S3_ENDPOINT=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
S3_BUCKET_INBOX=
S3_BUCKET_EXPORTS=
S3_BUCKET_AUDIT=
S3_REGION=

# RunPod
RUNPOD_API_KEY=
RUNPOD_OCR_ENDPOINT_ID=
RUNPOD_EXTRACT_ENDPOINT_ID=

# Packages
NEXTUP_BASE_URL=
NEXTUP_USERNAME=
NEXTUP_PASSWORD=
NEXTUP_DB_NAME=
NEXTUP_MODE=sandbox|prod
SAGA_MODE=xml|online|off
SAGA_ONLINE_BASE_URL=
SAGA_ONLINE_TOKEN=

# Policy
HITL_NOUL_THRESHOLD=0.35
AUTO_POST_ENABLED=false
```

**Research task:** confirm how Railway injects Bucket credentials (exact variable names). Do not guess. Read https://docs.railway.com/guides/storage-buckets.md and write the real names into SETUP.md.

**Research task:** confirm LangClaw model string for xAI. LangClaw uses `init_chat_model()` and `LANGCLAW__AGENTS__MODEL`. If `xai:grok-4.7` is not supported, document the OpenAI-compatible workaround above after reading LangClaw provider docs: https://langclaw.dev/ and https://github.com/tisu19021997/langclaw

### 4.9 LangClaw app shape

```text
roacc_claw/
  app.py              # Langclaw(), roles, middleware
  tools/
    v5_ingest.py
    v3_classify.py    # Jev + optional RunPod
    matcher.py
    det_sorter.py
    normalize_nextup.py
    normalize_saga.py
    post_nextup.py
    post_saga.py
    intent_check.py
    v1_anaf_pull.py
    v2_declaration.py
    v4_codit_patch.py
  workflows/
    ingest_source_doc.py    # mode="python" — recommended LangClaw path
    monthly_close.py
  rbac.py
```

Roles: `admin`, `accountant`, `readonly`.  
Default-deny tools that post. `accountant` may run ingest + hold queue. `admin` may approve auto_post.

LangClaw official: https://langclaw.dev/ · https://pypi.org/project/langclaw/ · requires Python ≥3.11  
Install: `uv add langclaw` and extras as needed `telegram`, `postgres`.

Workflows: author in **Python** `mode="python"` (`ctx.parallel`, `ctx.phase`, `ctx.tool`). Do not use saved JS bodies for fiscal control flow.

### 4.10 Deterministic checks (coding, not models)

Must exist as pure functions with tests:

- Romanian CUI checksum (research official algorithm; do not invent — see ANAF / ONRC sources in RESEARCH_LOG)
- Hash dedupe `(tenant, supplier_cui, series, number, date, total)`
- `sum(line.net) == header.net` and VAT arithmetic per rate
- Account is a **leaf** analytic if posting to SAGA (SAGA rejects non-leaf, e.g. `5125` vs `5125.2` — confirm in SAGA manual)
- Filename and XML well-formedness for SAGA
- JSON Schema validation of CanonicalDocument
- Redact CNP / extra PII before any Grok call

---

## 5. Adapter rules

### NextUp (primary)

Marketing/integration page (starting point, **not** the contract): https://nextup.ro/integrari/  
Sandbox intro cited by NextUp: http://sandbox.nextup.ro/intro  
Access request: https://sandbox.nextup.ro/request-access  

Public page claims (must be verified against sandbox docs, then coded):

- create invoices, delete/cancel documents  
- PDF of invoices/proformas  
- add products and clients by inserting invoice/proforma  
- proformas → invoices after payment  
- receipts (încasări) against an invoice  
- email documents  
- articles CRUD-ish, stock by code, categories, partners, partner balances  

**RESEARCH required before any NextUp client method is marked done:**

1. Open sandbox docs. Copy auth scheme (basic? token? IP allowlist? database name? port?).  
2. List real routes + verbs + payload examples in `RESEARCH_LOG.md`.  
3. Generate `roacc/adapters/nextup.py` only from that list.  
4. If sandbox docs are gated: write `INSTRUCT` for the human to request access, and keep a **typed stub** that raises `NotDocumented`.

Never guess a path like `/api/invoices`.

### SAGA (secondary)

Official XML import structure: https://manual.sagasoft.ro/sagac/topic-76-import-date.html  
SAGA WEB API documentation page: https://web0.sagasoft.ro/sagac/DocumentatieAPI  
Product home: https://www.sagasoft.ro/

Proven rules to encode (re-read the page and quote in RESEARCH_LOG):

- Invoice file name: `F_<cod-fiscal>_<numar-factura>_<data-factura>.xml`  
- Root `<Facturi>` / `<Factura>` / `<Antet>` / `<Detalii><Continut><Linie>`  
- If `<FurnizorCIF>` equals the company’s CUI → import as **Ieșiri**; else **Intrări**  
- Client county = county **code** (e.g. AB), country = country code  
- Payments file `P_<data>.xml` root `<Plati>`  
- Suppliers `FUR_<data>.xml`, clients `CLI_<data>.xml`, articles `ART_<data>.xml`  

**RESEARCH:** whether the human’s SAGA is Desktop XML-only or SAGA WEB/Online API. Default code path is XML write to exports bucket + SETUP steps to import in SAGA C. Online API methods only after DocumentatieAPI is read and listed.

### ANAF / e-Factura / SAF-T

Do **not** scrape ANAF. Prefer NextUp’s SPV / e-Factura integration if the sandbox docs say it exists.  
If a direct ANAF API is required, research only official ANAF / mfinante pages and record auth (qualified certificate / SPV). Put the result under V1 `INSTRUCT` until a legal access path exists.

Tracked vs untracked criteria in V1 are CO.DiT fields plus declaration statuses — not a second ledger.

---

## 6. Official research queue (execute in this order)

For each item: open the page, write 5–15 lines in `RESEARCH_LOG.md`, then tick CODE or INSTRUCT.

1. **Jev API + Python SDK**  
   https://docs.typesafe.ai/api.md  
   https://docs.typesafe.ai/primitives.md  
   https://docs.typesafe.ai/sdk/python/usage.md  
   https://docs.typesafe.ai/models.md  
   https://docs.typesafe.ai/introduction/quickstart.md  
   https://docs.typesafe.ai/agent-skill.md  
   Key: `https://platform.typesafe.ai` or dashboard linked from docs (find current key page; do not invent).

2. **LangClaw**  
   https://langclaw.dev/  
   https://pypi.org/project/langclaw/  
   https://github.com/tisu19021997/langclaw  
   https://github.com/tisu19021997/langclaw/blob/main/.env.example  
   Confirm: start command, PORT, Telegram extra, Postgres checkpointer extra, how to expose HTTP besides channels, Railway-friendly `app.run()`.

3. **Railway service + Buckets + env**  
   https://docs.railway.com/quick-start.md  
   https://docs.railway.com/cli.md  
   https://docs.railway.com/storage-buckets.md  
   https://docs.railway.com/guides/storage-buckets.md  
   https://docs.railway.com/storage-buckets/billing.md  
   https://docs.railway.com/reference/config-as-code.md  
   Confirm: Bucket credential variable names, region immutability, no public URLs, service egress vs bucket egress.

4. **MongoDB Atlas + Motor**  
   https://www.mongodb.com/docs/atlas/getting-started/  
   https://www.mongodb.com/docs/drivers/motor/  
   https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/  
   Confirm: IP allowlist vs VPC, user roles, SRV URI, EU region (privacy). Prefer `eu-central-1` / Ireland / Frankfurt — record what Atlas actually offers.

5. **SAGA XML + API**  
   https://manual.sagasoft.ro/sagac/topic-76-import-date.html  
   https://web0.sagasoft.ro/sagac/DocumentatieAPI  
   Capture full invoice XML field list (the manual page is long — extract every tag used by Antet + Linie).

6. **NextUp sandbox**  
   http://sandbox.nextup.ro/intro  
   https://sandbox.nextup.ro/request-access  
   https://nextup.ro/integrari/  
   If intro is empty/gated → INSTRUCT human, stub adapter.

7. **RunPod Serverless vLLM**  
   https://docs.runpod.io/serverless/vllm/get-started  
   https://docs.runpod.io/serverless/endpoints/model-caching  
   https://www.runpod.io/blog/run-vllm-on-runpod-serverless  
   Confirm: request shape, OpenAI-compatible base URL `https://api.runpod.ai/v2/{id}/openai/v1`, flashboot, network volume for weights.

8. **xAI / Grok as LangClaw model**  
   https://docs.x.ai/docs  
   https://docs.x.ai/developers/models  
   https://api.x.ai/v1 + `XAI_API_KEY`  
   OpenClaw xAI notes are **not** LangClaw — only use them as hints: https://docs.openclaw.ai/providers/xai  
   Confirm a model id that exists today (do not hardcode a retired alias without checking models page). Construction may use Grok Build: https://x.ai/build

9. **Romanian CUI checksum + ANAF public company lookup**  
   Find official or widely used checksum spec; implement tests with known CUIs.  
   ANAF public register / open API if any — official domain only.

10. **e-Factura / SAF-T obligations (context for V2, not a how-to to evade)**  
    Official ANAF e-Factura and D406 pages. Record what NextUp already automates vs what V2 must track.

If a source contradicts this brief, **the official source wins for wire format**; this brief wins for product topology. Log the contradiction.

---

## 7. SETUP.md — what the human will actually do

Write SETUP.md as a checklist. Each step: action, official URL, what secret appears, where it is stored (Railway variables, never git).

Minimum checklist (refine after research):

1. Python 3.12 + `uv` locally  
2. Accounts: Railway, MongoDB Atlas (EU), TypeSafe AI (Jev key), xAI API key, RunPod, NextUp sandbox access, SAGA licence/path  
3. Atlas cluster + user + IP / Railway egress allowlist + `MONGODB_URI`  
4. Railway project `roacc` with environments `dev|staging|prod`  
5. Railway service `langclaw` from this repo; start command from LangClaw docs  
6. Railway Postgres (LangClaw checkpointer) if extra requires it  
7. Three Buckets: inbox, exports, audit — copy injected S3 vars onto `langclaw`  
8. Set env from §4.8  
9. `AUTO_POST_ENABLED=false` until 200-doc precision review  
10. Request NextUp sandbox; paste base URL + creds  
11. Deploy one RunPod vLLM endpoint only when dummy PDF scans exist  
12. Telegram token only if human chose that channel  
13. Seed one demo `CoDit` for a test CUI  
14. Run `uv run pytest` and the vertical slice in §8  
15. Intent-check a stub adapter response before touching prod NextUp  

Privacy: Bucket private; Grok sees redacted CanonicalDocument JSON; RunPod for raw scans; no public object ACL.

---

## 8. Thin vertical slice (must run before any live ERP write)

Golden fixture: a tiny well-formed SAGA-like or UBL-like invoice XML checked into `fixtures/invoice_in.xml` (synthetic CUI, not a real person).

Path that must pass locally without NextUp:

```text
ingest fixture
 → V5 job + fake bucket (MinIO or local dir backend)
 → V3 Jev pack OR recorded fixture answers if no API key
 → CanonicalDocument
 → matcher miss → hold
 → det_sorter hold
 → intent_check on synthetic ack
 → artifacts written
```

Provide a `LocalObjectStore` so tests do not need Railway. Provide `FakeJev` that loads `fixtures/jev_answers/*.json` when `TYPESAFE_API_KEY` is absent.

---

## 9. Review protocol until the graph is closed

After every batch of work, the bot runs this list and writes PASS/FAIL in `TODO.md`:

- [ ] Every box in the architecture diagram exists as a module or an INSTRUCT section  
- [ ] Every arrow has a function name + payload type  
- [ ] Every secret has an env name + SETUP step + official URL  
- [ ] Every Jev pack is code, not a paragraph  
- [ ] NextUp methods ⊆ researched routes (or explicitly stubbed)  
- [ ] SAGA XML tags ⊆ manual page tags  
- [ ] Bucket keys specified  
- [ ] Mongo collections + indexes specified  
- [ ] State machine transitions specified  
- [ ] HITL threshold specified  
- [ ] Grok is unreachable from `post_*` tools  
- [ ] RunPod unreachable unless `needs_ocr` / extract gate fired  
- [ ] CO.DiT writes are versioned  
- [ ] Tests for deterministic checks exist  
- [ ] Vertical slice command documented  
- [ ] RESEARCH_LOG has dates and URLs  
- [ ] No “TBD” without an owner and a next official URL  

Fail any box → do not start a new feature. Close the hole.

---

## 10. Definition of Done (for the bot’s first delivery)

Done means the human can, without asking the bot what to invent:

1. Clone / open the repo  
2. Follow SETUP.md with only official links and this project’s env names  
3. Run the vertical slice  
4. See a hold-queue item and a CanonicalDocument JSON  
5. Know exactly which dashboard to open for Jev, Railway, Atlas, NextUp, RunPod, xAI  
6. Know that live posting is still locked (`AUTO_POST_ENABLED=false`) until they say otherwise  

Done does **not** mean production bookkeeping. It means the loop is implementable without folklore.

---

## 11. Suggested first coding order (after research dump)

1. `roacc/contracts.py` + `jev_packs` + FakeJev  
2. `LocalObjectStore` + Motor repository interfaces  
3. LangClaw `app.py` with ingest tool + workflow python mode  
4. SAGA XML renderer from official tags (even if NextUp is still stubbed)  
5. NextUp client generated from sandbox research  
6. V4 patch + CO.DiT versioning  
7. Railway `railway.toml` + README pointer to SETUP.md  

---

## 12. Context the human already decided you may quote

- LangClaw is the production harness: tools, durable workflows, RBAC, cron, channels.  
- Jev returns choice / score / noul only.  
- Notebook pages define V1–V5 and the exit “DET SORTER × CO.STATE / CO.DiT → ACC PACKAGE NORMALIZER → Import | API | Manual → ACC SYST → ACTION + INTENT CHECK”.  
- Matcher against ERP is the named improvement at V3 step 4.  
- “Fury self-watch on specializations” = guardrail so V2 specializations cannot silently contradict each other; implement as Jev noul + deterministic equality on shared keys, not as a personality.

---

## 13. If you (Grok Bot) are reading this inside a chat with the owner

Ask only for missing **secrets and access**, not for architecture opinions:

1. Which first CUI / demo vs real  
2. Telegram or HTTP-only  
3. Which of these keys exist today: TypeSafe, xAI, Railway, Atlas, NextUp sandbox, RunPod, SAGA WEB  
4. SAGA mode: XML desktop / SAGA WEB / off for v1  

Then start §6 research and emit the files in §0.

Do not wait for all keys. FakeJev + LocalObjectStore + contracts are the first commit.
