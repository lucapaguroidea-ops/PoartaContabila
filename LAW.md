# Law

Status: **draft for the owner's review (2026-10-04).** `00_LAW.md` stays in force until the
owner approves this file; then this file replaces it (`docs/PLAN.md` A5 step 2) and the
citations in code are rewritten to these ids (step 4).

Package: `poarta_contabila`. Product face: Poarta Primară.

**How to read it.** Every rule has a permanent id (`L1` …). An id is never renumbered or reused;
a removed rule's id is retired. A rule that came from a dated owner decision says so in
brackets. The history of how the rules were reached is in git (branch `pre-tidy`, `00_LAW.md`
§6–§8).

## 1. The unit

- **L1 · Articol de cale.** The unit is an articol de cale: a bookkeeping state that already
  contains its next path (cale) and the gate (poartă) that must open before the path moves.
  Think: which articol is this document on, and is its poartă open? A change that cannot be
  stated that way is not ready.
- **L2 · The law in one line.** Documentul primar nu ia calea fără poartă.
- **L3 · The catalog.** Articolele de cale stand in a catalog de cale (`catalog/`). Graful
  Primar walks it: more expandable than a frozen database application, more controlled than an
  LLM interaction. Models classify inside nodes; edges, mouths and month-close are
  deterministic.
- **L4 · What makes a row real.** An articol that names no cale is a comment. A cale with no
  poartă is a silent post. A catalog that does not compose căi is a nomenclator.

## 2. The statutory split

- **L5 · One mouth.** SAGA C is the only statutory mouth. One firm-period has exactly one book
  of record: SAGA C, or NextUp for a tenant with `book_of_record = nextup` (L8).
  The write adapter seam stays, so another mouth (SAGA WEB) is a change under L41.
- **L6 · The eye.** SAGA's report pack and its RJ-CM export are the statutory eye; a read-only
  copy of SAGA's database is a later eye on a pinned SAGA C build. No eye reads SAGA's web
  interface.
- **L7 · Not a ledger.** Nothing in this system posts a *notă contabilă*. No chart of accounts,
  journal or 5-column trial balance is stored as books in any store. The domain store
  (Postgres) may hold an expected set and witness snapshots; PeriodDiff and CO.DiT are not
  books.
- **L8 · NextUp is an eye only.** For a tenant whose books are kept in NextUp, NextUp's journal
  and trial balance exports are an accepted eye, through the same witness protocol. Nothing is
  written to NextUp: such a tenant gets reconcile, controls and close, but no package.
  [owner, 2026-10-01]
- **L9 · The only way to post.** Posting = SAGA's official path: XML or DBF → Import date →
  Validare. A direct write to `CONT_BAZA.FDB` is `FORBIDDEN_FDB`.
- **L10 · No database rights on Railway.** No process on Railway holds SYSDBA or runs
  INSERT, UPDATE or DELETE on `CONT_BAZA.FDB`.
- **L11 · Validare is a person's.** The SAGA agent imports only. Validare on a posting module
  stays human until that module has a green copy-firm fixture; no agent Validare in v1.
- **L12 · A closed month gets nothing.** Month closed in SAGA ⇒ the agent writes nothing.
- **L13 · Compensation is SAGA-shaped:** Anulează importul | Devalidare | Stornare.
  Backup and restore are firm-wide, and a restore is a person's step.

## 3. Documents

- **L14 · XML first.** Where a document exists as XML, the XML is the document primar and the
  only extract source; a PDF or scan of it is a companion and is not parsed. In an SPV
  download, `<id>.xml` is the invoice and `semnatura_<id>.xml` its signature, told apart by the
  XML root element. [owner, 2026-10-01]
- **L15 · What is not primary.** A Romanian PDF invoice without its UBL is not primary. No CUI
  on a bon is not deductibility.
- **L16 · Containers split before emit.** An expense report is split into its parts by
  `folder_triage` and confirmed by a person (`decont_split`) before any emit; the container
  never becomes a Job. [owner, 2026-10-01]
- **L17 · Payroll is evidence.** A payroll statement never emits a Job: payroll is posted in
  the book of record and arrives as explained; the statement supports the explained rule and
  the D112 filing item. [owner, 2026-10-01]
- **L18 · Reading exports.** Account codes are read through the cell's display format, never
  from the stored number. Matching invoice numbers between documents and the book uses a
  normalisation recorded on the reconcile profile, `[de confirmat]` until checked on a real
  book. [owner, 2026-10-01]

## 4. Graphs

- **L19 · Edges read facts.** Graph edges read only stored fields or Jev answers already on
  state. No model on an edge.
- **L20 · Resume is idempotent.** `interrupt()` resume re-enters the node from its first line.
  Side effects sit after the interrupt, behind domain-store idempotency (Postgres unique keys).
- **L21 · Thread prefixes.** `batch:` | `job:` | `recon:` | `close:` | `chat:`. Never mixed.
- **L22 · Fail closed.** Extra keys on Job, Pack or resume are forbidden. Money and fiscal
  dates in graph state are strings.
- **L23 · Material is never filed.** Layer 1 `material == true` ⇒ `file` is impossible. Layer
  2 cannot clear `material`.
- **L24 · The review page.** The person answers through the review page (v1), a client of the
  HTTP resume routes: every answer goes unchanged to the question's own route, with the
  person's name (`X-Operator-Name`). No model in the answer path; an explanation decides
  nothing. The page loads nothing from outside its own origin and writes document values as
  text. [owner, 2026-10-03]
- **L25 · Chat is not a mouth.** A later `chat:` face is not a mouth, matcher or closer, and
  never resumes `job:`, `recon:` or `close:`.

## 5. Models

- **L26 · By role, pinned.** Models act only inside nodes, by role. Every role is pinned to one
  exact model in `catalog/50_control/ARTICOLE_MODEL_ROLES_v1.yaml`: no alias, no auto-router,
  no fallback model except as L30–L31 allow. An unset model means the role refuses and a person
  is asked.
- **L27 · The roles.** **System One = Jev**: routes and classifies JSON and normalised data.
  **System Two** (a GLM, DeepSeek or Kimi model): explains and drafts for a person; never
  posts, never decides a gate. **Document reading = Gemini**: only where there is no XML or
  text layer, its output checked deterministically before use. Bank statement tables are the
  exception: a model may read them from a text-layer PDF, because every line must tie
  (opening − debits + credits = closing) and the holder CUI must be the tenant's. [owner,
  2026-10-02]
- **L28 · Client data only on the EU route.** Synthetic tenants only, until an EU host serves
  the roles (`eu_route`). A client tenant's data never reaches another route.
- **L29 · Routes.** Calls go through OpenRouter, one key per role group, with
  `data_collection: deny` and `allow_fallbacks: false`; a provider passes only when OpenRouter
  lists it as neither training on prompts nor retaining them. Document reading on synthetic data
  goes directly to Google AI Studio, and that route refuses, in code and before any request,
  every tenant not marked `data_class: synthetic`. [owner, 2026-10-02]
- **L30 · Document-reading tiers.** A Google AI Studio reading role lists `tiers`: everyday
  models first; the strong tier first only when the operator asks, and alone for a second run
  of a read that did not confirm (a read that still does not confirm is refused, never
  stored). Each model carries `rpm`, `tpm`, `rpd`; an unconfirmed `rpd` is `null`. The next
  model is taken at once on a 429, after one retry 10 s later on a busy answer, or when this
  process's own count is full. A statement no model can read now waits with its PDF and is
  read again later; it has no Job until a read confirms. `tiers.reserve` models are read with
  only when an operator chooses so, recorded with who and until when (the next Pacific
  midnight); a statement may be set aside with a reason, and is then never read by a model.
  Every call records the model that read and why. [owner, 2026-10-02]
- **L31 · Approved alternates.** An OpenRouter role may list `alternates` (exact model ids,
  named providers, the same `deny` pin), written by the owner. A role moves to the first
  alternate that passes only while its main pin fails, and back when it passes. With no pin
  passing, the role fails closed; the owner's recorded choice (`wait`, `pause`, or
  `allow_synthetic` until a date, synthetic tenants only) is the only way to relax `deny`. Jev
  has no alternate. [owner, 2026-10-03]

## 6. Values the controls stand on

- **L32 · Watched accounts** (Layer 1, blocking): 401, 4111, 4426, 4427, 4428, 5121, 5311.
  Others (5124, 403–409, 411/413/418/419, 4423, 4424) may be named by advisory controls only.
- **L33 · Materiality.** V2 materiality is 0.01 RON on watched accounts. A PRE/POST matcher
  may use 0.05 on match keys only.
- **L34 · Explained rules** are made through `POST /rules` and the HITL kind `explained_rule`.
- **L35 · Law values are cited.** A legal value carries `source`, `as_of`, `certainty`.
  Unconfirmed stays `[de confirmat]`.
- **L36 · No client data in this repo.** No client identifiers, IBANs or live amounts in the
  repo, tests or fixtures. Invented CUIs pass the check digit.
- **L37 · Parked.** `bon_via_nota` and ArticolBon are parked (`SURFACE.md` §1).

## 7. The stack

- **L38 · Standalone.** Built from scratch on LangGraph, Pydantic and FastAPI. It depends on,
  imports and copies nothing from the retired LangClaw framework. [owner, 2026-10-01]
- **L39 · One database.** The domain store is Postgres, schema `domain`, beside the LangGraph
  checkpointer in the same database; idempotency keys are unique indexes. L7 applies to every
  schema in it. [owner, 2026-10-01]
- **L40 · Deploy.** A dedicated Railway project (`faithful-mercy`), region `europe-west4`. No
  data from any previous deployment. [owner, 2026-10-01]

## 8. Changing the law

- **L41 · What needs the owner.** A change to the sink product, the FDB write policy, graph
  topology, interrupt kinds, watched accounts, or any rule here is the owner's dated decision:
  the rule is edited in this file with `[owner, <date>]`, and affected catalogs bump
  `schema_version`. A Telegram message is not a decision.
- **L42 · What does not.** Adding an articol de cale inside existing enums is not a change of
  law; it still enters as `status: draft` until its fixture and the accountant's rule are met.

## 9. Two faces and the lexicon

| Face | Says | Does not lead with |
|---|---|---|
| Cabinet — Poarta Primară | document primar, articol de cale, catalog de cale, poartă, buckets | Graph, LangGraph, chat |
| Engineering — Graful Primar | four compiled graphs, Path/cale, WriteModule, PreFile, Latch/Hold/Gate | Chat supervisor, ReAct, ledger |

| Term | Means | Does not mean |
|---|---|---|
| Articol de cale | State + path + gate; in YAML a Flux, Close, Reconcile, Bon or Control row | SAGA stoc; a comment |
| Cale | Pre-defined walk: document primar × contabilitate RO × fiscalitate | An LLM trajectory |
| Catalog de cale | Versioned book of those walks | A drawer of things |
| Poartă | Guard on a hop | A chat "ok" |
| Poarta Primară | Product face | The ledger; ANAF filing |
| Document primar | Factură, UBL, bon, extras | Notă contabilă |
| PreFile | Package (XML/DBF) for SAGA Import | Filing at ANAF |
| Bucket | expected \| explained_sink_only \| unexplained | A local account |
| Graful Primar | The compiled walker | Product name |
| Path | Runtime name for cale; code: `articol_id` | An LLM route |
| Pack | Source-doc dossier before emit | Thinking unit |
| Job | Posting unit after emit | CloseRun |
| CloseRun | One firm-month | A Job |
| WriteModule | An approved SAGA mouth | FDB INSERT |
| Expected set | Document-derived totals | General ledger |
| SagaEye | Read protocol | Write path |

Mouth = SAGA C Import + Validare. Eye = report pack / RJ-CM / later the read-only copy.
Compensation = Anulează / Devalidare / Stornare. Flux files keep their name; say cale. Naked
"articol", "catalog", "graph", "flow" or "file at ANAF" are not used in new prose. Romanian
domain words stay Romanian; code identifiers stay English.

---

## Appendix — old citations → new ids

Used once by the citation rewrite (`docs/PLAN.md` A5 step 4), then deleted.

| `00_LAW.md` | `LAW.md` |
|---|---|
| §0 | L1 |
| §1 | L2, L3 |
| §2 | L5, L6, L7 |
| §3.1 | L7 |
| §3.2 | L10 |
| §3.3 | L9 |
| §3.4 | L19 |
| §3.5 | L26, L27, L28, L29 |
| §3.6 | L20 |
| §3.7 | L5 |
| §3.8 | L13 |
| §3.9 | L12 |
| §3.10 | L21 |
| §3.11 | L22 |
| §3.12 | L15 |
| §3.13 | L23 |
| §3.14 | L4 |
| §3.15 | L35 |
| §3.16 | L36 |
| §4 | L25, §9 |
| §5 | §9 |
| §6.1 | L6 |
| §6.2 | L11 |
| §6.3 | L34 |
| §6.4 | L5, L8 |
| §6.5 | L33 |
| §6.6 | L37 |
| §7 | L32, L41, L42 |
| §8 A1 | L38, L39, L40 (A1 §4 superseded by L24) |
| §8 A2 | L8, L14, L16, L17, L18 |
| §8 A3, A4, A5, A6 | L30 |
| §8 A7 | L29, L31 |
| §8 A8 | L24 |
