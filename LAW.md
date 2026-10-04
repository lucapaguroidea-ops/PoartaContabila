# Law

Status: **in force, approved by the owner on 2026-10-04.** It replaced `00_LAW.md` and its
amendments A1–A8 (git history, branch `pre-tidy`).

Package: `poarta_contabila`. Product face: Poarta Primară.

**How to read it.** Every rule has a permanent id (`L1` …), never reused; a removed rule's id is
retired. `[owner, date]` marks a rule that came from a dated owner decision. `[test]` marks a
rule the build must enforce: a failing test fails the build, and the citation test checks that
every `[test]` rule has a test naming it. The history of how the rules were reached is in git
(branch `pre-tidy`).

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
  poartă is a silent post. A catalog that does not compose căi is a nomenclator. [test]

## 2. The statutory split

- **L5 · One mouth.** SAGA C is the only statutory mouth. One firm-period has exactly one book
  of record: SAGA C, or NextUp for a tenant with `book_of_record = nextup` (L8). The write
  adapter seam stays, so another mouth (SAGA WEB) is a change under L46. [test]
- **L6 · The only eye.** SAGA's report pack and its RJ-CM export are the only statutory eye; a
  read-only copy of SAGA's database is a later eye on a pinned SAGA C build. Nothing else is the
  eye: not a model's reading of a screen, an email or a client's spreadsheet, and not SAGA's web
  interface.
- **L7 · Not a ledger.** Nothing in this system posts a *notă contabilă*. No chart of accounts,
  journal or 5-column trial balance is stored as books in any store. The domain store
  (Postgres) may hold an expected set and witness snapshots; PeriodDiff and CO.DiT are not
  books. [test]
- **L8 · NextUp is an eye only.** For a tenant whose books are kept in NextUp, NextUp's journal
  and trial balance exports are an accepted eye, through the same witness protocol. Nothing is
  written to NextUp: such a tenant gets reconcile, controls and close, but no package.
  [owner, 2026-10-01]
- **L9 · The only way to post.** Posting = SAGA's official path: XML or DBF → Import date →
  Validare. A direct write to `CONT_BAZA.FDB` is `FORBIDDEN_FDB`. [test]
- **L10 · No database rights on Railway.** No process on Railway holds SYSDBA or runs
  INSERT, UPDATE or DELETE on `CONT_BAZA.FDB`. [test]
- **L11 · Validare is a person's.** The SAGA agent imports only. Validare on a posting module
  stays human until that module is proven in SAGA C (state **saga**, L42) and the owner decides
  otherwise; no agent Validare in v1. [owner, 2026-10-04]
- **L12 · A closed month gets nothing.** Month closed in SAGA ⇒ the agent writes nothing. [test]
- **L13 · Compensation is SAGA-shaped:** Anulează importul | Devalidare | Stornare. Backup and
  restore are firm-wide, and a restore is a person's step. [test]

## 3. Documents and formats

- **L14 · XML first.** Where a document exists as XML, the XML is the document primar and the
  only extract source; a PDF or scan of it is a companion and is not parsed. In an SPV
  download, `<id>.xml` is the invoice and `semnatura_<id>.xml` its signature, told apart by the
  XML root element. [owner, 2026-10-01]
- **L15 · What is not primary.** A Romanian PDF invoice without its UBL is not primary. No CUI
  on a bon is not deductibility. [test]
- **L16 · Containers split before emit.** An expense report is split into its parts by
  `folder_triage` and confirmed by a person (`decont_split`) before any emit; the container
  never becomes a Job. An invoice inside it that implies SPV (company to company) is taken from
  its SPV XML (L14); with only a PDF or scan, the part waits for the XML. The 542 settlement
  note for the report is not built (`[de confirmat]`). [owner, 2026-10-01]
- **L17 · Payroll is evidence.** A payroll statement never emits a Job: payroll is posted in
  the book of record and arrives as explained; the statement supports the explained rule and
  the D112 filing item. [owner, 2026-10-01]
- **L18 · Reading exports.** Account codes are read through the cell's display format, never
  from the stored number. Matching invoice numbers between documents and the book uses a
  normalisation recorded on the reconcile profile, `[de confirmat]` until checked on a real
  book. [owner, 2026-10-01]
- **L19 · External formats come from official sources.** No external format or API is
  guessed: it is read on the official page and quoted with its date in `RESEARCH_LOG.md`; a
  page that cannot be read gives a typed stub that refuses. SAGA XML tags are extended only
  from a successful copy-firm import. [owner, 2026-10-04]

## 4. Graphs

- **L20 · Four graphs only.** `folder_triage`, `ingest_source_doc`, `reconcile_sink`,
  `monthly_close`, joined by domain-store ids; a compiled graph is never a node of another.
  [owner, 2026-10-04]
- **L21 · Edges read facts.** Graph edges read only stored fields or Jev answers already on
  state. No model on an edge. [test]
- **L22 · Resume is idempotent.** `interrupt()` resume re-enters the node from its first line.
  Side effects sit after the interrupt, behind domain-store idempotency (Postgres unique keys).
  [test]
- **L23 · Thread prefixes.** `batch:` | `job:` | `recon:` | `close:` | `chat:`. Never mixed.
  [test]
- **L24 · Fail closed.** Extra keys on Job, Pack or resume are forbidden. Money and fiscal
  dates in graph state are strings. [test]
- **L25 · Material is never filed.** Layer 1 `material == true` ⇒ `file` is impossible. Layer
  2 cannot clear `material`. [test]
- **L26 · The review page.** The person answers through the review page (v1), a client of the
  HTTP resume routes: every answer goes unchanged to the question's own route, with the
  person's name (`X-Operator-Name`). No model in the answer path; an explanation decides
  nothing. The page loads nothing from outside its own origin and writes document values as
  text. [owner, 2026-10-03]
- **L27 · Chat is not a mouth.** A later `chat:` face is not a mouth, matcher or closer, and
  never resumes `job:`, `recon:` or `close:`.

## 5. Models

- **L28 · By role, pinned.** Models act only inside nodes, by role. Every role is pinned to one
  exact model in `catalog/50_control/ARTICOLE_MODEL_ROLES_v1.yaml`: no alias, no auto-router.
  No model outside the catalog is chosen at run time. An unset model means the role refuses and
  a person is asked. [test]
- **L29 · The roles.** **System One = Jev**: routes and classifies JSON and normalised data.
  **System Two** (a GLM, DeepSeek or Kimi model): explains and drafts for a person; never
  posts, never decides a gate. **Document reading = Gemini**: only where there is no XML or
  text layer, its output checked deterministically before use. Bank statement tables are the
  exception: a model may read them from a text-layer PDF, because every line must tie
  (opening − debits + credits = closing) and the holder CUI must be the tenant's. [owner,
  2026-10-02] [test]
- **L30 · Routes.** Calls go through OpenRouter, one key per role group, with
  `data_collection: deny` and `allow_fallbacks: false`; a provider passes only when OpenRouter
  lists it as neither training on prompts nor retaining them. Document reading on synthetic data
  goes directly to Google AI Studio, and that route refuses, in code and before any request,
  every tenant not marked `data_class: synthetic`. [owner, 2026-10-02]
- **L31 · Document reading never guesses.** A reading role may list tiers of Gemini models; a
  read that does not confirm is retried by a stronger tier and, if it still does not confirm,
  refused and never stored. A statement no model can read now waits; it has no Job until a
  read confirms. Reserve models are read with only by an operator's recorded choice. Every call
  records the model that read and why. (The mechanics: `ARCHITECTURE.md` §12.1.)
  [owner, 2026-10-02]
- **L32 · Approved alternates only.** An OpenRouter role may move to an alternate the owner
  wrote in the catalog (exact model, named providers, the same `deny` pin), only while its main
  pin fails a data-policy check, and back when it passes. With no pin passing, the role fails
  closed; `deny` is relaxed only by the owner's recorded, dated choice, for synthetic tenants
  only. Jev has no alternate. (The mechanics: `ARCHITECTURE.md` §12.1.) [owner, 2026-10-03]

## 6. Data boundaries

- **L33 · Client data only on the EU route.** Synthetic tenants only, until an EU host serves
  the roles (`eu_route`). A client tenant's data never reaches another route. [test]
- **L34 · Clients never mix.** No client's data in another client's run, model prompt,
  projection or export. Every stored row and model call carries the client's CUI and is refused
  on a mismatch. [owner, 2026-10-04]
- **L35 · Build tools touch synthetic data only.** Coding agents (Claude Code, browser
  automation) work only on synthetic tenants and SAGA test firms with invented data. The build
  agent's token is refused for a client tenant. [owner, 2026-10-04]
- **L36 · No client data in this repo.** No client identifiers, IBANs or live amounts in the
  repo, tests or fixtures. Invented CUIs pass the check digit. [test]

## 7. Controls and evidence

- **L37 · Watched accounts** (Layer 1, blocking): 401, 4111, 4426, 4427, 4428, 5121, 5311.
  Others (5124, 403–409, 411/413/418/419, 4423, 4424) may be named by advisory controls only.
- **L38 · Materiality.** V2 materiality is 0.01 RON on watched accounts. A PRE/POST matcher
  may use 0.05 on match keys only.
- **L39 · Explained rules** are made through `POST /rules` and the HITL kind `explained_rule`.
- **L40 · Law values are cited.** A legal value carries `source`, `as_of`, `certainty`.
  Unconfirmed stays `[de confirmat]`. [test]
- **L41 · Every answer is recorded.** Who answered, when, what was proposed, what was chosen,
  and the outcome, append-only; every control's disposition the same way. [owner, 2026-10-04]
- **L42 · Proven before active.** A catalog row becomes `active` only once it is proven in SAGA
  C (state **saga**, `SURFACE.md`) and the owner approves it. Synthetic proof alone keeps it
  `draft`. [owner, 2026-10-04]
- **L43 · Gates change only on evidence.** A question, control or poartă is added, removed or
  relaxed only by the owner's decision, with the evidence of L41: the friction it costs and the
  control it gives. A gate that has stopped a real error stays unless the owner decides
  otherwise. [owner, 2026-10-04]

## 8. The stack

- **L44 · Standalone.** Built from scratch on LangGraph, Pydantic and FastAPI. It depends on,
  imports and copies nothing from the retired LangClaw framework. [owner, 2026-10-01]
- **L45 · One database, in the EU.** The domain store is Postgres, schema `domain`, beside the
  LangGraph checkpointer in the same database; idempotency keys are unique indexes. L7 applies
  to every schema in it. The service runs in an EU region, with no data from any previous
  deployment. [owner, 2026-10-01]

## 9. Changing the law

- **L46 · What needs the owner.** A change to the sink product, the FDB write policy, graph
  topology (L20), interrupt kinds, watched accounts (L37), or any rule here is the owner's dated
  decision: the rule is edited in this file with `[owner, <date>]`, and affected catalogs bump
  `schema_version`. A Telegram message is not a decision.
- **L47 · What does not.** Adding an articol de cale inside existing enums is not a change of
  law; it still enters as `status: draft` until L42 is met.

## 10. Two faces and the lexicon

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
| Hopper | Intake mechanism; not branded | The product |
| PreFile | Package (XML/DBF) for SAGA Import | Filing at ANAF |
| Bucket | expected \| explained_sink_only \| unexplained | A local account |
| Graful Primar | The compiled walker | Product name |
| LangGraph | Substrate | The product; a ReAct licence |
| Path | Runtime name for cale; code: `articol_id` | An LLM route |
| Pack | Source-doc dossier before emit | Thinking unit |
| Job | Posting unit after emit | CloseRun |
| CloseRun | One firm-month | A Job |
| WriteModule | An approved SAGA mouth | FDB INSERT |
| Expected set | Document-derived totals | General ledger |
| SagaEye | Read protocol | Write path |
| Jev / System Two / Gemini | Classify in a node / explain and draft / read scans | Poster, edge or gate |

Mouth = SAGA C Import + Validare. Eye = report pack / RJ-CM / later the read-only copy.
Compensation = Anulează / Devalidare / Stornare. Flux files keep their name; say cale. Naked
"articol", "catalog", "graph", "flow" or "file at ANAF" are not used in new prose. Romanian
domain words stay Romanian; code identifiers stay English.
