# 00 — Law

Status: LOCKED for implementers.  
Package: `poarta_contabila` (A1).  
Product face: Poarta Primară.

## 0. Unit

An **articol de cale** is a bookkeeping state that already contains its next path and the gate that must open before the path moves.

Think: which articol is this document on, and is its poartă open?

If a change cannot be stated that way, it is not ready.

## 1. Expansions

Documentul primar nu ia calea fără poartă.

Articolele de cale stau într-un catalog de cale.

Graful Primar walks that catalog: more expandable than a frozen database application, more controlled than an LLM interaction. Models classify inside nodes. Edges, mouths, and month-close are deterministic.

## 2. One-sentence statutory split

SAGA C is the only statutory mouth.  
Firebird replica / SAGA report pack is the only statutory eye.  
Nothing in this system posts a *notă contabilă*.  
The domain store (Postgres, A1) may hold an expected set and witness snapshots. Not a ledger.

## 3. Invariants (fail the build)

1. No chart of accounts, journal, or 5-column trial balance stored as books in any store.
2. No process on Railway holds SYSDBA or writes INSERT/UPDATE/DELETE on `CONT_BAZA.FDB`.
3. Posting = official SAGA path only: XML/DBF → Import date → Validare. Direct FDB write = `FORBIDDEN_FDB`.
4. Graph edges read only stored fields or Jev answers already on state. No LLM on an edge.
5. Models act only inside nodes, by **role**, and every role is pinned to one exact model in
   `catalog/50_control/ARTICOLE_MODEL_ROLES_v1.yaml` (no alias, no auto-router, no fallback model
   but the model tiers of Google AI Studio document reading, §8 A3–A4;
   an unset model means the role refuses and a person is asked). **System One = Jev**: routes and
   classifies JSON / normalized data. **System Two = DeepSeek or GLM**: explains and drafts for a
   person; never posts, never decides a gate. **Document reading = Gemini**: only where there is no
   XML or text layer (`needs_ocr`), and its output is checked deterministically before use. Bank
   statement tables are the exception: a model may read them even from a text-layer PDF, because
   every line must tie (opening − debits + credits = closing) and the holder CUI must be the
   tenant's (owner, 2026-10-02). Calls go
   through OpenRouter, one key per role group, except **document reading on synthetic data, which
   goes directly to Google AI Studio** (`GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC`; owner, 2026-10-02).
   That route refuses every tenant not marked `data_class: synthetic`, in code, before any request.
   **Synthetic tenants only** until an EU host serves the roles (`eu_route`); a client tenant's
   data never reaches another route.
6. `interrupt()` resume re-enters the node from line 1. Side effects sit after the interrupt, behind domain-store idempotency (Postgres unique keys).
7. One firm-period has one statutory sink: SAGA C.
8. Compensation is SAGA-shaped: Anulează importul | Devalidare | Stornare. Backup/restore is firm-wide.
9. Month closed in SAGA ⇒ agent writes `0`.
10. `thread_id` prefixes: `batch:` | `job:` | `recon:` | `close:` | `chat:`. Never mix.
11. Fail closed. Extra keys on Job/Pack/resume = forbid. Money and fiscal dates in graph state are strings.
12. PDF RO without UBL is not primary. No CUI on a bon is not deductibility.
13. Layer 1 `material == true` ⇒ `file` is impossible. Layer 2 cannot clear `material`.
14. An articol that does not name a cale is a comment. A cale with no poartă is a silent post. A catalog that does not compose căi is a nomenclator.
15. Law values carry `source`, `as_of`, `certainty`. Unconfirmed stays `[de confirmat]`.
16. No client identifiers, IBANs, or live amounts in this repo, tests, or fixtures.

## 4. Two faces

| Face | Says | Does not lead with |
|---|---|---|
| Cabinet — Poarta Primară | document primar, articol de cale, catalog de cale, poartă, buckets | Graph, LangGraph, chat |
| Engineering — Graful Primar | four compiled graphs, Path/cale, WriteModule, PreFile, Latch/Hold/Gate | Chat supervisor, ReAct, ledger |

Chat / multi-tool is a later `chat:` face. It is not a mouth, matcher, or closer. It never resumes `job:`, `recon:`, or `close:`.

## 5. Lexicon (complete for this pack)

### Face A

| Term | Means | Does not mean |
|---|---|---|
| Articol de cale | Unit: state + path + gate. In YAML this is a Flux/Close/Reconcile/Bon/Control row | SAGA stoc; a comment |
| Cale | Pre-defined walk: document primar × contabilitate RO × fiscalitate | LLM trajectory |
| Catalog de cale | Versioned book of those walks | A drawer of things |
| Poartă | Guard on a hop | Chat “ok” |
| Poarta Primară | Product face | The ledger; ANAF filing |
| Document primar | Factură, UBL, bon, extras | Notă contabilă |
| Hopper | Intake mechanism. Not branded | The product |
| PreFile | Pack XML/DBF for SAGA Import | File at ANAF |
| Bucket | expected \| explained_sink_only \| unexplained | A local account |

### Face B

| Term | Means | Does not mean |
|---|---|---|
| Graful Primar | Compiled walker | Product name |
| LangGraph | Substrate | Product; ReAct licence |
| Path | Runtime name for cale. Code: `articol_id` in ArticoleFlux | LLM route |
| Pack | Source-doc dossier before emit | Thinking unit |
| Job | Posting unit after emit | CloseRun |
| CloseRun | One firm-month | A Job |
| WriteModule | Approved SAGA mouth | FDB INSERT |
| Expected set | Document-derived totals | General ledger |
| SagaEye | Read protocol | Write path |
| Jev / System Two (DeepSeek, GLM) / Gemini | Classify in-node / explain, draft / read scans | Poster / edge / gate |

### Statutory

Mouth = SAGA C Import + Validare. Eye = report pack / RJ-CM / later FDB replica. *Notă contabilă* is what SAGA posts. Compensation = Anulează / Devalidare / Stornare. PeriodDiff and CO.DiT are not books.

### Collisions

LangClaw, langclaw_acct, OpenClaw = retired names (A1). This repo does not depend on or reference that framework. Flux = keep filename; say cale. Naked “articol” / “catalog” / “graph” / “flow” / “file at ANAF” are banned in new prose.

Romanian domain words stay Romanian. Code identifiers stay English.

## 6. Decisions locked (harvest v1.3)

1. Witness v1 = SAGA report pack and/or RJ-CM export → SagaEye DTOs. FDB SQL later.
2. Validare on posting modules is human until that `module_id` has a green copy-firm fixture. No agent Validare in v1.
3. Explained rules = `POST /rules` + HITL `explained_rule`. Engagement backlog deferred.
4. Write adapter seam kept. No Web reads. Book of record = SAGA C.
5. V2 materiality = 0.01 RON on watched accounts. PRE/POST matcher may use 0.05 on match keys only.
6. `bon_via_nota` and ArticolBon are parked. Not in BUILD v1 sequence.

## 7. Amendment

v1 watched synthetic accounts (Layer 1 blocking): 401, 4111, 4426, 4427, 4428, 5121, 5311.

5124, 403–409, 411/413/418/419, 4423, 4424 are not on this list. Advisory controls may name them. Making them blocking is an amendment.

Changing sink product, FDB write policy, graph topology, interrupt kinds, or watched accounts requires a dated section in this file and `schema_version` bump on affected catalogs.

Adding an articol de cale inside existing enums is not an amendment. It still needs `status: draft` until the fixture/accountant rule in the row is met.

A Telegram message is not an amendment.

## 8. Amendments

### A1 · 2026-10-01 — standalone stack, Postgres domain

Decided by the owner on 2026-10-01.

1. **Standalone.** This repo is built from scratch on LangGraph + Pydantic + FastAPI. It does not depend on, import, or copy code from the LangClaw framework or its fork. Ideas may be re-implemented; files are not copied.
2. **Package** is `poarta_contabila` (was the working name `langclaw_acct`).
3. **Domain store = Postgres**, schema `domain`, alongside the LangGraph checkpointer tables in the same database. Idempotency keys in `IDEMPOTENCY.md` become unique indexes. Mongo is not used. Invariant 1 applies to every schema in that database.
4. **Review page = v2.** v1 HITL surface is the HTTP resume endpoints only (`ARCHITECTURE.md` §10). No chat surface in v1.
5. **Fresh start.** No data is migrated from the previous deployment. Old journal rows are not books here and never enter this database.
6. **Deploy target** = a dedicated Railway project (`faithful-mercy`), region `europe-west4`, separate from the previous deployment's project (amended 2026-10-01 from "replaced in place": clean logs and variables). The previous project is not migrated; its code and setup are recorded outside this repo.

Not changed by A1: sink product, FDB write policy, graph topology, interrupt kinds, watched accounts. `schema_version` of catalogs is unchanged.

### A2 · 2026-10-01 — XML first; NextUp as a read-only witness; expense reports and payroll as sources

Decided by the owner on 2026-10-01.

1. **XML first.** Where a document exists as XML, the XML is the document primar and the only extract source; a PDF or scan of the same document is a companion and is not parsed. This covers RO e-Factura (UBL CIUS-RO from SPV) and EU/foreign e-invoices that arrive as XML. In an SPV download, `<id>.xml` is the invoice and `semnatura_<id>.xml` is its signature (a companion, never a second invoice); they are told apart by the XML root element, not by file name alone.
2. **NextUp witness.** For a tenant whose books are kept in NextUp, NextUp's journal (registru jurnal) and trial balance (balanță) exports are an accepted *eye*: read-only inputs to reconciliation and close, through the same witness protocol as SAGA's report pack. CO.DiT axis `book_of_record` gains the value `nextup`.
3. **No NextUp mouth.** Nothing is written to NextUp. A tenant with `book_of_record = nextup` gets gating (reconcile, controls, close) but no PreFile: WriteModules apply only where `book_of_record = saga_c`. One firm-period still has exactly one book of record.
4. **New source documents** (Lane B, `draft`): `sink_rj_nextup`, `sink_balanta_saga`, `sink_balanta_nextup` (witness exports), `decont_cheltuieli` (expense report) and `stat_salarii` (payroll statement). New `fiscal_class` values `decont` and `payroll`; new `primary_kind` values `xls` and `msg`.
5. **Split before emit.** An expense report is a container: folder_triage splits it into child packs (receipts, invoices, the report itself as evidence) before any emit, confirmed by a person through the new HITL kind `decont_split` on `folder_triage`. The container never becomes a Job. An invoice inside the report that implies SPV (company to company) is taken from its SPV `.xml` (rule 1); with only a PDF or scan, the child is `ro_efactura_pdf` in `_incomplete_spv` and waits for the XML. The 542 settlement note for the report is not built in v1 (`[de confirmat]`).
6. **Payroll is evidence.** `stat_salarii` never emits a Job: payroll is posted in the book of record and arrives as `explained_sink_only`; the statement supports the payroll explained rule and the D112 filing item.
7. **Reading exports:** account codes are read through the cell's display format, never from the stored number (SAGA stores analytic `401.00010` as the number 401.0001). Matching invoice numbers between documents and the book's journal uses a normalisation rule recorded on the reconcile profile and stays `[de confirmat]` until checked on a real book.

Changed by A2: sink product (adds NextUp as a read-only eye), interrupt kinds (adds `decont_split`). Not changed: FDB write policy, graph topology, watched accounts. Catalog `schema_version` is unchanged; every new row is `draft`.

### A3 · 2026-10-02 — one rate-limit backup for Google AI Studio document reading

Decided by the owner on 2026-10-02, while document reading stays on the Google AI Studio free tier (until the owner moves it to the EU route).

1. **Rate limits are catalog values.** A Google AI Studio role names, per model it may use, the free tier's per-minute quota (`rate_limits: {model: {rpm, tpm}}`), as the owner's AI Studio page shows it. The sender keeps under it: it counts the requests and tokens it sent in the last minute, per model, for the whole process.
2. **One backup model.** Such a role may pin exactly one `backup_model`: an exact `gemini-…` id, never an alias, never a list. It is read with only while the main model is at its rate limit (its own count is full, or Google answered 429). A busy main model (503) is retried on itself, not moved to the backup.
3. **Both full:** the sender waits for the first free slot, at most 90 s; past that the statement is refused (fail closed).
4. **Recorded.** Every call records the model that actually read; a backup read says so in its reason and output.
5. **Not changed:** every other role keeps "no fallback model"; OpenRouter roles take no backup; the synthetic-only guard, the key and the client-data rules are untouched. The reading evaluation scores one model and never uses the backup.

Not an amendment of: sink product, FDB write policy, graph topology, interrupt kinds, watched accounts. `schema_version` is unchanged.

### A4 · 2026-10-02 — model tiers for Google AI Studio document reading (replaces A3's backup)

Decided by the owner on 2026-10-02, after the free tier's daily quota (20 requests a day for the Flash models) ran out during a run, and Google's busy (503) answers appeared to count against it.

1. **Tiers.** A Google AI Studio document-reading role names `tiers`: `everyday` models (the most requests a day) and `strong` models (more capable, fewer a day). Its `model` is the first everyday model. A3's single `backup_model` is replaced by these tiers.
2. **Order.** Everyday models first. The strong tier first for a hard statement (2 pages or more) or when the operator asks (`strong: true` on the upload). The strong tier only for a **second run**: a read that does not confirm (holder CUI, IBAN, every line tying opening − debits + credits = closing) is read once more by the strong tier. A read that still does not confirm is refused and never stored.
3. **Limits.** `rate_limits` per model carries `rpm`, `tpm` and `rpd` (requests per Pacific day; every attempt counts, a 503 included). An `rpd` the owner has not confirmed is `null` (`[de confirmat]`): only Google's daily 429 stops it.
4. **Moving on.** The next model in the order is taken at once on a 429 (a daily 429, as Google names its quota, skips the model until Pacific midnight), after one retry 10 s later on a busy answer (5xx, unreachable), or when this process's own count of that model is full. When every model is full the reader waits for the first free slot, at most 90 s, then refuses.
5. **Recorded.** Every call records the model that read, its tier, whether it was the first choice, and whether it was a second run.
6. **Not changed:** every other role keeps one model and no fallback; the synthetic-only guard, the key and the client-data rules are untouched. The reading evaluation reads with one model and never another tier.

Not an amendment of: sink product, FDB write policy, graph topology, interrupt kinds, watched accounts. `schema_version` is unchanged.
