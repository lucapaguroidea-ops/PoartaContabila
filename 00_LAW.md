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
5. Jev is System One. Grok is System Two (explain, HITL). Grok never posts. RunPod only if `needs_ocr`.
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
| Jev / Grok / RunPod | Classify in-node / explain / gated OCR | Poster / edge |

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
