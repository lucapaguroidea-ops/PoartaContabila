# Architecture — the system as built

The machine, as built on 2026-10-04; what is not built yet is named in §17. `LAW.md` is the
law (cited as `L<n>`). The catalog (`catalog/`) is the row-level law and the system's
ontology: what each document, path, gate and account *means* and how they connect. The domain
store (§4) is its data model: what is held and where. This file is how the two run.

## 1. Shape

```
sources (SPV UBL, S3 dump, Telegram, email, photo, SPV register, SAGA report pack)
    → Railway  four compiled LangGraph graphs
         model roles in nodes (catalog ArticoleModelRoles): Jev classify ·
         GLM explain · Gemini read scans — pinned models (L28–L32)
         Postgres domain + checkpointer · Bucket blobs
    → XML/DBF packages
    → Windows VPS  SAGA C as AGENT (Import; Validare human in v1)
    ← SagaEye v1 from SAGA report pack / RJ-CM export
```

SAGA is the mouth (L5, L9). The report pack is the eye (L6). This system hops documente primare through articole de cale and PreFiles. It does not keep books.

Deploy: Railway project `faithful-mercy`, region `europe-west4` (LAW: EU region); the operator
token is kept in the browser tab only (the review page).

## 2. Four graphs

| graph_id | thread | In | Out |
|---|---|---|---|
| folder_triage | `batch:{id}` | dump | Packs + emit |
| ingest_source_doc | `job:{id}` | Job | packaged / acked / already_in_sink |
| reconcile_sink | `recon:{cui}:{period}` | Jobs + sink lines | pre/post verdict |
| monthly_close | `close:{cui}:{period}` | lock | file / hold + V4 |

Do not nest compiled graphs (L20). Glue = domain-store ids.

### folder_triage

sniff → aisle (SPV > foreign > bon CUI > extras > rest) → pair UBL+PDF → fork bon → emit if class ∧ identity ∧ primary ∧ posting_eligible.

PDF RO without UBL is not primary.

A container row (`split`, e.g. `decont_cheltuieli`) never emits: once its identity and primary gates pass, `decont_split` names its parts and each part is a child Pack through the same gates (XML first: a part with the invoice XML is `ro_efactura_ubl`).

### ingest_source_doc

```
extract → v3_classify → match → v3_judge → checks
  → interrupt v3_approve? 
  → PRE reconcile_sink
  → package WriteModule (blocked if ArticoleControls hard_failures)
  → interrupt wait_validare
  → intent_check SagaEye
  → acked | reopened | failed
```

`package` does not talk to Firebird. No SAGA call before `interrupt()` in the approve node.

Job unique on `(tenant_cui, source_hash)`.

### reconcile_sink

PRE: already in RJ or SPV register → do not package.  
POST: how vs expected accounts.  
det first, llm_review cannot flip to posted. contest → HITL.  
Matcher tolerance 0.05 on keys. Missing sink → `need_rj_export`.

### monthly_close

```
lock_expected_set → recon POST → pull report pack → PeriodDiff
  → run ArticoleControls
  → v2_gate (Jev may not clear material)
  → file | hold | patch_maps | reopen
  → v4_codit after file
```

Buckets: expected | explained_sink_only | unexplained.  
material if outbound hole, unexplained inbound, watched |Δ| ≥ 0.01, lock mismatch, blocking control FAIL.

## 3. Types (minimum)

Money and dates in state are strings.

```
TenantRef        cui, punct="default", saga_firm_folder
SourceRef        kind, bucket_key, content_type, source_hash
PartnerRef       cui?, name, role, saga_analytic?
CanonicalDocument  job_id, tenant, period, doc_class, number, date, partner,
                   totals, lines, is_storno, storno_of, source, maps, jev
JobRecord        status machine below; export_key; module_id; saga{}
ExpectedItem     job_id, doc_class, number, date, partner_cui, gross, net, vat, analytic
SinkDoc          saga_key, same business keys, validated
BucketRow        kind, expected?, sink?, rule_id?, delta_gross
PeriodDiff       outbound_holes, inbound[], synthetic_delta, analytic_delta,
                 material, blockers[], snapshot_id, hard_failures
WriteModule      see catalog
ControlRun       control_id, status PASS|FAIL|INFO, target, actual, diff
FilingItem       filing_id, period, state open|filed, receipt_key?
CO.DiT           {cui, period} axes + pins + certainty + derive()
```

Job statuses (forward only except `reopened` after SAGA compensation):

```
ingested → extracted → bound → reconcile_pre
  → approved | already_in_sink | needs_human
approved → packaged → wait_validare → acked
acked | wait_validare → reopened → packaged
* → rejected | failed | needs_human
```

Close is a CloseRun, not a Job.

## 4. Storage

| Store | Holds | Does not |
|---|---|---|
| Postgres `domain` schema: jobs, job_events, answers, canonical, maps, expected_sets, explained_rules, write_modules, close_snapshots, codit, filings, control_runs, jev_answers | domain | FDB rows |
| Postgres checkpointer | cursor, interrupts | domain |
| Bucket | source, XML/DBF, report packs, backup labels, receipts | secrets |

After a SAGA side effect: write the domain row, then return from the node.

Object key: `tenants/{cui}/{punct}/{period}/{kind}/{jobId}/...`

## 5. WriteModules (v1 catalog, all draft)

`iesire_factura_xml` `intrare_factura_xml` `storno_iesire_xml` `storno_intrare_xml` `incasare_xml` `plata_xml` `parteneri_xml` `articole_xml` `nota_nc_dbf`

Parked: `bon_via_nota`.

Facturi routing: FurnizorCIF == societate CUI → Ieșiri; ClientCIF == societate CUI → Intrări. Analytics from Lane A maps.

Validare: human until the module is proven in SAGA C (L11, L42).

`hard_failures > 0` on prefile controls ⇒ do not package.

## 6. SagaEye v1

```
covers(cui, period) -> bool        # this witness holds that firm's books for that month
documents(cui, period) -> list[SinkDoc]
solduri(cui, period) -> dict
analytic(cui, period, root) -> dict
```

PRE may conclude `absent` only for covered months (`need_rj_export` otherwise).

SAGA readers: the journal register and balance (`sinks/exports.py`) and the report pack's purchase/sales journals (`ReportPackEye`, `sinks/saga_eye.py`; preferred: they carry partner CUIs, net and VAT). `intent_check` compares the posted document with the package; a difference goes to a person.

v1 reads SAGA report pack / RJ-CM export (practice takeover pack), or, for a tenant with `book_of_record = nextup`, NextUp's journal and balance exports (L8, eye only). A read-only database copy later, on a pinned SAGA C build (§17). Core graphs depend only on the protocol.

Watched: 401, 4111, 4426, 4427, 4428, 5121, 5311 (L37).

## 7. CO.DiT

Write order: exig defaults → T* → F* → F7/A* → derive().  
Hard pair → ValidationError, document not saved.  
Axes in `catalog/10_lege_firma` plus additive `catalog/60_practice/ARTICOLE_CODIT_AXES_v1.yaml`.  
Empty profile must not default to `tva_platitor`.  
Period document, not a sticky tenant flag.

## 8. HITL

Kind ∈ ArticoleHITL ∪ HITL_ADD ∩ graph.allowed_hitl. Unknown kind = bug. Resume `extra=forbid`.

Core kinds:

- `v3_approve` resume `{decision: approve|reject|edit, edit?}` — XOR, not three bools
  (on an unbound bank line the question carries `proposal`: the invoices it could settle and, when one leads, a ready `edit`)
- `v2_close` resume `{action: file|hold|patch_maps|reopen, explained_rule?}`
- `wait_validare`, `request_devalidare`, `define_articol`, `define_module`, `explained_rule`, `need_rj_export`
- additive: `decision_menu` (client sends `option` only; server stamps confirmer/at), `codit_premise`, `filing_receipt`, `control_disposition`

## 9. Compensation

| SAGA fact | SAGA action | Job |
|---|---|---|
| Imported, not validated | Anulează importul | rejected |
| Validated, not in SPV / not filed | Devalidare by human | reopened |
| In SPV or receipt exists | Stornare + Reglare | new job `is_storno=True` |
| Panic | Human restore of labeled snapshot | runbook |

Agent never devalidates. Agent never auto-restores. Archive metadata must include `tenant_cui`. Restore of another tenant is refused.

## 10. HTTP

Operator routes take `GRAPHUSERTOKEN_OPERATOR`, or the build agent's
`GRAPHUSERTOKEN_CLAUDE_SYSBUILDER` for synthetic tenants only (L35); every answer may carry
`X-Operator-Name` (L26, L41). Agent routes take `GRAPHUSERTOKEN_AGENT_SHARED`.

```
GET  /health  /ready                          # liveness; readiness and token strength
GET  /review  /review/{file}                  # the review page, no token (L26)

# tenants and witnesses
PUT  /tenants/{cui}                           # name, firm folder, book of record, bank accounts, data_class
POST /tenants/{cui}/exports/{rj|balanta|spv_register}
PUT  /codit/{cui}/{period}   GET /codit/{cui}/{period}            # CO.DiT

# documents in
POST /ingest                                  # SPV zip / UBL XML → Job (XML first)
POST /extras/{cui}                            # bank statement: PDF + header (+ tables)
POST /decont/{cui}                            # expense report → folder_triage
GET  /reading/{cui}/budget  /reading/{cui}/waiting                 # document reading (L31, §12.1)
POST /reading/{cui}/choice  /reading/{cui}/retry  /reading/{cui}/waiting/{wait_id}/skip

# questions and answers (the HITL surface; the review page is a client of it)
GET  /inbox/{cui}/{period}                    # what waits on an accountant
GET  /jobs/{job_id}              POST /jobs/{job_id}/resume          # ingest_source_doc
GET  /triage/{batch_id}          POST /triage/{batch_id}/resume      # folder_triage
POST /recon/{cui}/{period}  GET …  POST /recon/{cui}/{period}/resume # reconcile_sink
POST /close/{cui}/{period}  GET …  POST /close/{cui}/{period}/resume # monthly_close
GET  /answers                                 # every answer, who gave it
GET  /evidence/{cui}/{period}                 # the evidence ledger: friction and control

# the month
GET  /periods/{cui}/{period}/diff             # Layer 1: PeriodDiff and controls
POST /filings/{cui}/{period}  GET …  POST /filings/{cui}/{period}/{filing_id}/receipt
POST /rules                      GET /rules/{cui}                    # explained rules

# model roles
GET  /model-roles  /model-calls  /model-keys  # pins, what was sent, spend per key
POST /model-roles/{role_id}/choice            # operators only (L32)
POST /model-roles/{role_id}/compare           # main pin vs approved alternates
POST /ocr-eval/{cui}                          # the reading evaluation

# the Windows agent
GET  /agent/pull   POST /agent/imported  /agent/snapshot  /agent/ack-backup
```

Agent token ≠ operator token ≠ build agent's token ≠ model keys. No `SAGA_SYSDBA` in Railway env.

## 11. Package

Four compiled graphs, one module each; glue is the Postgres domain store.

```
poarta_contabila/
  triage.py ingest.py reconcile.py close.py   # the four graphs: folder_triage, ingest_source_doc,
                                              #   reconcile_sink, monthly_close
  runtime.py           # wiring: stores, bucket, checkpointer, graphs, model gateway, inbox
  app.py operator_api.py agent_api.py review.py ui/   # HTTP; the review page (L26)
  catalog.py flux.py hitl.py jsonlogic.py     # Catalog Cale loader, matches(), typed HITL
  types/               # closed domain types; money and fiscal dates are strings
  jobs.py packages.py registry.py storage.py answers.py rules.py codit.py filings.py
  extract/             # XML first (ubl.py); statements (statement.py, document_ai.py, gemini.py)
  recon/               # PRE / POST / settle (deterministic, no model)
  period_diff.py       # Layer 1 + ArticoleControls; not a ledger
  sinks/               # SAGA mouth (saga_xml.py), eye (saga_eye.py), witness exports, SPV register
  jev.py model_roles.py explain.py provider_policy.py key_usage.py   # model roles (L28)
  reading_waits.py ocr_eval.py synthetic_docs.py smoke.py coverage.py agent.py db/schema.sql
  synthetic/           # seeded invented firms, documents and SAGA books
  scenarios.py         # YAML scenarios (fixtures/scenarios/) over HTTP, simulated SAGA agent
  surface.py           # the four surface states; generates SURFACE.md (with coverage.py)
  evidence.py          # the evidence ledger of a firm-month (friction and control)
  loops.py             # the loop kit: files to a SAGA C test firm, its exports read back (loops/)
```

No ReAct supervisor. No `Journal.post`.

## 12. Jev packs

`v3_classify` → `{doc_class, needs_ocr, needs_human, confidence}`  
`v3_judge` → `{accounts_ok, risk, needs_human}`  
`v2_declaration_gate` → `{books_support_declaration, gap_materiality, action}`  

JSON only. Cache `{pack, input_hash}`. Layer 2 cannot clear `material`.
Code: `poarta_contabila/jev.py`. The answer is stored on the thread in its own node (`judge`,
`layer2`) before the node that asks a person, so a resume never asks Jev again.
Each pack is a role in `catalog/50_control/ARTICOLE_MODEL_ROLES_v1.yaml` (one pinned model,
provider pin, synthetic-only until the EU route) with a role card (Jev's questions and criteria,
Gemini's extraction rules, the System Two brief; no persona); `MODEL_CALLS=dry` records what a
role would be sent (`GET /model-calls`, with the card hash) and sends nothing.

### 12.1 Model routing in detail (behind LAW §5)

The mechanics behind L31 and L32 (owner, 2026-10-04: the law keeps the principles).

- **Document-reading tiers** (Google AI Studio, synthetic only). A role lists `tiers`:
  `everyday` models (most requests a day), `strong` models (more capable, fewer a day),
  optional `reserve`. Everyday models read first; the strong tier first only when the operator
  sends `strong: true`, and alone for a **second run** of a read that did not confirm (holder
  CUI, IBAN, every line tying opening − debits + credits = closing). A read that still does not
  confirm is refused and never stored. The page count never decides the tier.
- **Limits.** `rate_limits` per model: `rpm`, `tpm`, `rpd` (requests per Pacific day; every
  attempt counts, a 503 included); an `rpd` the owner has not confirmed is `null` and only
  Google's daily 429 stops it. The sender counts requests and tokens per model for the whole
  process.
- **Moving on.** The next model is taken at once on a 429 (a daily 429 skips the model until
  Pacific midnight), after one retry 10 s later on a busy answer (5xx, unreachable), or when
  this process's own count is full.
- **Waiting.** When no model can read now, the statement is parked with its PDF
  (`domain.reading_waits`) and read again every `READING_RETRY_SECONDS` and by
  `POST /reading/{cui}/retry`; the same PDF uploaded while it waits is the same parked
  statement. `GET /reading/{cui}/budget` shows reads left per model, what waits, and with
  `documents=N` warns before a batch the day's budget does not cover.
- **Reserve.** Read with only when an operator chooses: the parked upload's answer and the
  budget carry the question (`wait` | `reserve` | skip one statement). `POST
  /reading/{cui}/choice` is recorded insert-only (`domain.reading_choices`: who, when, which
  statements, until when, how many released); `reserve` holds until the next Pacific midnight.
  `POST /reading/{cui}/waiting/{wait_id}/skip {reason}` sets a statement aside; it is never read
  by a model afterwards. **No paid key** is used for reserve reads.
- **Recorded.** Every reading call records the model that read, its tier, whether it was the
  first choice, and whether it was a second run.
- **The reading evaluation** (`POST /ocr-eval/{cui}`) reads with one model only, never another
  tier, so a score belongs to one model.
- **OpenRouter alternates.** The provider list (`dataPolicy` per provider) is read daily and
  right after a call is refused for its data policy (`domain.provider_policies`). An alternate
  may name a provider other than the model's maker; a System Two alternate may be of the `kimi`
  family. Each call records the pin it went by and why. With no pin passing: Jev answers with
  cautious values and asks a person; System Two sends the question without an explanation;
  `/model-roles` says so. `POST /model-roles/{role_id}/choice {choice: wait | pause |
  allow_synthetic, until}` is recorded with who chose it; `allow_synthetic` expires by itself.

## 13. Windows agent

```
GET /agent/pull → backup label → Import as AGENT → POST /agent/imported
snapshot_request → parse report pack or replica → POST /agent/snapshot
```

AGENT: import only. No Devalidare, no închidere lună, no admin.

In SAGA (RESEARCH_LOG R1, "Configurare utilizatori"), AGENT is **not** SAGA's user type
"Agent": that type is a sales agent who sees only the clients, suppliers and invoices they
entered. AGENT is an "Operare" (or "Standard") user with modificare, ștergere, devalidare and
validare taken away (Validare is human in v1), no access to Închidere lună or to the
listing menu beyond what the snapshot needs, and access to its tenant's firm only. A
non-Admin user cannot operate on a closed month nor devalidate one, so SAGA itself enforces
"month closed ⇒ agent writes 0" (L12). Which right "Import date" itself needs is
`[de confirmat]` on the copy firm.

Running an import (R1, "Diverse → Import date"):

- backup first ("Înainte de import, efectuați o salvare a bazei de date"). SAGA names the
  archive `ZZ-LL-AAAA_N.ZIP` in `SAGA C.3.0\salv_bd\<firm folder>`. `POST /agent/ack-backup`
  carries only the `{cui}:{folder}:{utc}` label, so the agent keeps label → archive file in its
  own log. Restore stays a person's step (it replaces the firm's data).
- sync mode **"Nr.+data"**, always: SAGA then skips a document whose number and date it
  already holds, a second guard behind the `(tenant_cui, source_hash)` Job key and PRE.
- one pull is one import folder: files keep the names SAGA expects (`F_…`, `I_<data>`,
  `P_<data>`), so a second file of the same name waits for the next pull.
- imported invoices arrive not validated; "Anulează importul" undoes an import, and once
  validated a person must devalidate first (§9).

Pull hands out packages per `(cui, saga_firm_folder)` with the module's backup rule; an import
under a module that needs a backup is accepted only with an acknowledged label of that firm and
folder. A snapshot lists SAGA documents (`saga_doc_key`, class, number, date, gross,
`validated`, and net / VAT / partner CUI when read from the report pack) and closed months; a closed month gets nothing. `acked` = a snapshot shows the
matching document validated. A snapshot never moves a job out of `acked`.

## 14. Env

As read by the code.

```
DATABASE_URL=          # one Postgres: schema `domain` + LangGraph checkpointer tables
S3_ENDPOINT= S3_REGION= S3_ACCESS_KEY= S3_SECRET_KEY= S3_BUCKET=
GRAPHUSERTOKEN_AGENT_SHARED=       # the Windows agent (old name AGENT_SHARED_TOKEN)
GRAPHUSERTOKEN_OPERATOR=           # people: tenants, uploads, ingest, answers (≠ agent token;
                                   #   old name OPERATOR_TOKEN)
GRAPHUSERTOKEN_CLAUDE_SYSBUILDER=  # the build agent: operator routes, synthetic tenants only (L35)
MODEL_CALLS=off                # off | dry (record only) | live (synthetic tenants only)
OPENROUTER_SYS1_API_KEY=       # Jev (System One) roles: own key and credit limit
OPENROUTER_SYS2_API_KEY=       # System Two roles (explanations, rule drafts)
OPENROUTER_MANAGEMENT_KEY=     # optional: GET /model-keys also reads the account's credits and keys
POLICY_REFRESH_SECONDS=86400   # OpenRouter provider data policies, re-read (0 = off)
GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC=  # document reading: Gemini direct, synthetic tenants only (L30)
READING_RETRY_SECONDS=60       # parked statements read again (§12.1; 0 = off)
DOCUMENT_AI_PROCESSOR=          # projects/{p}/locations/{eu}/processors/{id}
DOCUMENT_AI_CREDENTIALS_JSON=   # service-account key; else Application Default Credentials
JEV_BASE_URL= JEV_API_KEY=      # only for a direct Jev route; on OpenRouter these stay unset
MAX_UPLOAD_MB=32               # request-body cap; over it → 413
POARTA_CATALOG_DIR=            # optional: another catalog/ directory (tests)
```

Not read by any code (planned, or left from earlier designs): `OPENROUTER_BASE_URL`,
`ANAF_SPV_CLIENT_ID`, `ANAF_SPV_CLIENT_SECRET`. EU-route variables are named per role in the
catalog's `eu_route` once WP-D4 is decided (`docs/owner/EU_VERTEX_SETUP.md` §E).

Absent: `SAGA_SYSDBA`, Firebird write password, `CIEL_SA`, `NEXTUP_*`.

## 15. Extract contract

One contract for every backend (`ubl`, `document_ai`, `gemini`; later `mt940`, `docling`).
Under the source object's bucket prefix:

```
normalized/markdown.md        text the graph may read
normalized/tables.json        list of {headers, rows} as strings
normalized/extract_meta.json  {backend, source_hash, model_or_version, needs_ocr, identity_ok}
```

- XML first (L14): when a document exists as XML (UBL CIUS-RO, EU e-invoice), the XML is parsed
  into CanonicalDocument fields; a PDF of the same document is never read. In SPV zips,
  `semnatura_*.xml` is the signature companion. Code: `extract/ubl.py` — `read_spv_zip`
  (members split by root element), `parse_ubl` (totals checked, fail closed), `to_canonical`
  (tenant side, signed storno). Unit codes (`H87`, `C62`) reach SAGA unmapped until `maps`
  covers them.
- `skip_if: [has_text_layer, is_ubl]` is on the SourceDoc row.
- Graph state stores field strings, not raw model JSON.
- Statement PDFs of synthetic tenants are read by Gemini through Google AI Studio
  (`extract/gemini.py`; L31, §12.1) or by Google Document AI (`extract/document_ai.py`); a
  client tenant's need the EU route (L33). A statement becomes line Jobs, never one Job per
  statement total (`catalog/60_practice/ARTICOLE_EXTRAS_GRAIN_v1.yaml`).
- An extract is written once per `(source_hash, backend)` (`extract/contract.py`,
  `domain.extracts`); a later backend (Docling) keeps the same three files and node names.

## 16. Idempotency keys

The domain row (Postgres) is written after the SAGA side effect; a resume re-enters the node
from its first line (L22).

| Object | Key | Collision |
|---|---|---|
| Job | `(tenant_cui, source_hash)` | second emit is a no-op |
| threads | `job:{job_id}`, `batch:{batch_id}`, `recon:{cui}:{period}`, `close:{cui}:{period}` | prefixes never mixed (L23) |
| extract | `source_hash` + backend | reuse `normalized/` |
| package XML/DBF | `export_key` = `{module_id}:{job_id}:{schema_version}` | written once |
| PRE / POST recon | `(job_id, stage, sink_snapshot_id)` | |
| Jev answer | `(pack, input_hash)`, hash of `{pack, version, input}` | reused, never paid twice |
| HITL resume | `(thread_id, interrupt_id)` | same body twice = same state |
| CloseRun lock | `(cui, period)` | one expected-set hash |
| ControlRun | `(cui, period, control_id, snapshot_id)` | |
| FilingItem | `(cui, period, filing_id)` | a receipt closes it, a date does not |
| Backup label | `{cui}:{folder}:{utc}` | restore refused on a tenant mismatch |

Money and fiscal dates in graph state are strings; Decimal lives inside the compute node (L24).

## 17. Not built yet

What the law or the catalog names and the code does not do yet. Open work is in `BUILD.md`;
every row's state, and the rows not yet in the catalog, are in `SURFACE.md`.

| Piece | State | Tracked in |
|---|---|---|
| The Windows agent program (pull, backup, Import date, snapshot) | the HTTP side is built (§13); the program is not in this repo | `BUILD.md`; copy-firm test §6, §10 |
| SAGA C proof of every write module | all `draft`; tags from R1 only | WP-03; the SAGA C loops |
| A read-only SAGA database copy as an eye | parked | WP-15; copy-firm test §9 |
| DBF note mouth (`nota_nc_dbf`), bonuri (`bon_via_nota`) | decision / parked | WP-D3, WP-14; Loop 5 |
| Storno, partner and article mouths | wait on SAGA's own sample XML | copy-firm test §3 |
| EU route for client data | `eu_route: null` on every role: client tenants are refused | WP-D4 |
| SAGA WEB as a second mouth | not started; a change of law (L5, L46) | `RESEARCH_LOG.md` R5 |
| `chat:` face | parked | WP-17 |
