# Plan — tidy the repo, then map the surface through SAGA C in loops

Status: **for the owner's review, 2026-10-03.** Nothing here is built or moved yet. Each
decision the owner makes is marked **D1 … D9** (§C). Once approved, Part A runs first and
this file is absorbed into `BUILD.md` (its WPs) and deleted, as Part A requires.

---

## Part A — Repo tidy

### A1. The rule

Every file in the repo is one of three things:

1. **used**: read by code, tests, the catalog loader or the build agent;
2. **explains what is used**: the mission, the law, the architecture as built, an owner guide;
3. **the plan**: open work, and the surface still to map.

History (done WPs, superseded briefs, resolved gaps, retired frameworks) lives in git only,
behind a tag `pre-tidy` on the last commit before Part A. Nothing that tells a first-time
agent **what we build, how and why** may be lost; it moves into the entry file (A3).

### A2. Inventory (2026-10-03)

| File | Read by | Is | Fate |
|---|---|---|---|
| `CLAUDE.md` | every session | loader | keep; points to `README.md` only |
| `INDEX.md` | people, agents | map + mission lines | **merge** into a new `README.md` (A3) |
| `00_LAW.md` (234 lines) | cited 50× in code (`§8` 42×, `§3` 8×) | law + amendment history A1–A8 | **rewrite**: today's rules, amendments folded in (D2) |
| `AGENTS.md` | build agent | how to work | **rewrite** short; takes the research rule from the GROK brief §5 |
| `ARCHITECTURE.md` (333) | cited 16× in code | system to build | **rewrite** as built + "not built yet" per section |
| `BUILD.md` (253) | cited by code (WP ids) | status table + open WPs | **rewrite**: open WPs only, plus Part B's program |
| `docs/BUILD_DONE.md` (1143) | nothing; 65 WP ids cited in code/tests/catalog point here | history | **delete** after A4 |
| `EXTRACT.md`, `IDEMPOTENCY.md` | cited by `extract/`, `jobs.py`, `packages.py` | contracts in use | **move** into `ARCHITECTURE.md` (one section each) |
| `CATALOG_LOOKUP.md` | nobody in code | which YAML to open | **move** into `catalog/README.md` |
| `RESEARCH_LOG.md` (304) | cited by `saga_xml.py`, `jev.py`, `document_ai.py` | external formats, quoted | keep; drop "not read" histories that a later read replaced |
| `docs/COPY_FIRM_TEST.md` | owner | the SAGA C test (Loop 0) | keep; becomes Loop 0's guide (B5) |
| `docs/OWNER_CHECKLIST.md` | owner | open asks | keep; remove ticked items |
| `docs/EU_VERTEX_SETUP.md` | cited by `model_roles.py` | owner guide, not configured | keep (it is the plan for the EU route) |
| `docs/CATALOG_GAPS.md` | nobody in code | G1–G9, mostly decided | **delete**; open G5/G9 live on the checklist already |
| `docs/harvest/*` (4 files) | catalog/code cite ~20 harvest ids (C-F11, J-07, D-01 …) | the practice's harvest; holds the **unbuilt surface** | **extract** unbuilt items into the surface backlog (A4), then delete |
| `annex/*` (5 files) | nothing | superseded briefs, LangClaw contract and catalog | **delete** (after the GROK §5 rule moves to `AGENTS.md`) |
| `catalog/60_harvest/*_ADD` | catalog loader (`mode: additive`) | live rows | keep the loader; **rename** the folder for what it holds (D5) |
| `catalog/**`, `fixtures/**`, `poarta_contabila/**`, `tests/**` | the system | code and data | keep; only comments change (A4) |

### A3. Target layout

```
README.md            first contact: mission, scope, the unit (articol de cale), the
                     statutory split, what is built, what is next, where things are
CLAUDE.md            loader: read README, LAW, AGENTS; commands
LAW.md               rules as of today, numbered with stable ids (L1 …), no history
ARCHITECTURE.md      the system as built (+ "not built yet" lines); extract and idempotency contracts
AGENTS.md            how an agent works here (one WP per commit, research rule, no client data)
BUILD.md             open WPs and programs (Part B lives here), decisions pending
RESEARCH_LOG.md      external formats and APIs, quoted
SURFACE.md           the articol map's surface: possible / proven synthetic / proven in SAGA (B2)
catalog/             Catalog Cale (README = which file to open)
docs/owner/          COPY_FIRM_TEST.md (Loop 0), OWNER_CHECKLIST.md, EU_VERTEX_SETUP.md
poarta_contabila/ tests/ fixtures/
```

`README.md` must state, in its first screen: what Poarta Primară is (documente primare walk
articole de cale to SAGA C, which posts; the system never keeps books), for whom (a Romanian
accounting practice and its clients), why (no document reaches the books without its poartă;
every exception reaches a person), how (catalog → four graphs → XML mouths → human Validare →
SAGA exports as the eye), the hard limits (no SYSDBA, no FDB writes, models by role, client
data only on the EU route), and what state the build is in.

### A4. The citation problem, and its fix

Code, tests and catalog cite `00_LAW §8 A4`, `ARCHITECTURE §13`, 65 WP ids and ~20 harvest ids.
A rewrite renumbers all of them. Fix, in this order:

1. The new `LAW.md` gives every rule a **stable id** (`L1` … `Ln`, never renumbered; a removed
   rule's id is retired). Each amendment A1–A8 maps to the rule(s) it now is.
2. A one-off script rewrites citations: `00_LAW §8 A4` → `LAW L17`, `ARCHITECTURE §13` → the
   new heading's anchor, `WP-xx` in comments → the rule or module it means (or dropped when it
   only said when). Harvest ids → the catalog row id that carries them.
3. A test fails the build on a citation to a missing `L` id or heading (so they cannot rot again).
4. The harvest's **unbuilt** items (catalogues, filings, scenarios not yet in the catalog)
   become `SURFACE.md` rows in state *possible* (B2) before `docs/harvest/` goes.

### A5. Steps (one commit each, tests and ruff green each time)

1. Tag `pre-tidy`. Extract the harvest's unbuilt surface into `SURFACE.md`.
2. Write `LAW.md` (stable ids) — **owner reviews the text before the commit** (it replaces a
   locked file).
3. Rewrite `ARCHITECTURE.md` (with EXTRACT, IDEMPOTENCY), `AGENTS.md`, `BUILD.md`.
4. Citation script + citation test; code comments updated.
5. Write `README.md`, `CLAUDE.md`, `catalog/README.md`; move owner guides to `docs/owner/`.
6. Delete `INDEX.md`, `00_LAW.md`, `EXTRACT.md`, `IDEMPOTENCY.md`, `CATALOG_LOOKUP.md`,
   `docs/BUILD_DONE.md`, `docs/CATALOG_GAPS.md`, `docs/harvest/`, `annex/`.
7. **First-contact check:** a fresh agent session, given only `CLAUDE.md`, answers ten fixed
   questions (what, for whom, why, the unit, the statutory split, what may never run on
   Railway, which data may reach which model, what is built, what is next, where the catalog
   is). Every wrong answer is a fix to `README.md`, not to the questions.

Size: about two build sessions. No behaviour changes; the suite stays at 776+ passing.

---

## Part B — Mapping the surface through SAGA C, in loops

### B1. Goal

Every articol de cale we have, plan, or will need is **proven in SAGA C**: synthetic documents
for it went through our ingestion, out through our mouth (or a person's keying where no mouth
exists), into a SAGA C test firm, back through SAGA's own exports, through reconcile and
close, and the result equals what the generator meant. Then SAGA WEB repeats the proven set.

### B2. The surface map (`SURFACE.md`, generated by `coverage.py`)

Each row (articol, source doc, job kind, mouth, export, control, HITL kind, filing) has one
state:

| State | Means | Proven by |
|---|---|---|
| **possible** | named (catalog, plan, harvest), not yet on a path we run | a line in `SURFACE.md` |
| **synthetic** | a passing scenario drives it (today's WP-69 "covered") | `scenarios.py` |
| **saga** | it went round-trip through a SAGA C test firm and the result matched | a loop's evidence |
| **out** | will not be built, with the reason | owner decision |

The program ends when every row is **saga** or **out**. Opportunities found along the way (a
row SAGA's data suggests and the catalog lacks) enter as **possible**, never straight into
the catalog.

### B3. One loop

A loop takes **one slice**: a handful of rows, one or two client types, two or three months.

| Step | Who | What |
|---|---|---|
| 1. Pick | build agent, owner OKs | the slice, its rows, its exit criteria (fixed now, not later) |
| 2. Generate | build agent | synthetic months for the slice's firms (`synthetic/`), seeded; documents + our mouth XML |
| 3. Ingest | runtime | our pipeline runs them on synthetic tenants, as today |
| 4. Import | owner (or the agent once Copy-firm §10 passes) | packages into the slice's SAGA C test firm; the owner validates; anything with no mouth is keyed by hand from the generator's list |
| 5. Export | owner | the slice's SAGA exports (RJ, balanță, jurnale), as for a client |
| 6. Read | build agent | exports become the eye: reconcile + close against them |
| 7. Compare | build agent | three diffs: generator ↔ SAGA (did SAGA book what we meant?), SAGA export ↔ our reader (did we read it right?), our simulated `Book` ↔ SAGA (does the generator's SAGA model match SAGA?) |
| 8. Review | owner | the gap list: each proposed row approved as `draft`, or `out`, or deferred |
| 9. Close | build agent | rows → **saga**; reader, generator and simulated book fixed to SAGA's truth; real exports of the test firm become fixtures (invented data) |

Each loop improves four things at once: the ingestion (step 3 failures), the reading (step 7
second diff), the generator's realism (third diff), and the map (step 8).

### B4. Rules that keep loops from sticking

1. **Fixed slice, fixed exit.** A loop ends when its rows are **saga** or explicitly deferred,
   not when everything it uncovered is solved.
2. **New nuance → backlog.** Anything outside the slice found during a loop becomes one
   **possible** line in `SURFACE.md` with one sentence; it is never worked in that loop.
3. **Two sessions per loop.** One owner session in SAGA C (import, validate, export), one build
   session before and after. A loop that needs a third session is split.
4. **Small months first.** 10–30 documents per firm-month in the first pass of a slice; volume
   only in a later loop that is about volume.
5. **No law change inside a loop.** A needed amendment is drafted at the loop's close and
   decided by the owner between loops.
6. **The SAGA C build is pinned** for a run of loops; an update of SAGA C is its own loop
   (re-run the proven set).

### B5. Loops, in order

Loop 0 is the infrastructure; every later loop assumes it passed.

| Loop | Slice | Client types | Mouths / keying | SAGA exports read |
|---|---|---|---|---|
| **0** | `docs/COPY_FIRM_TEST.md` §1–§10 | test firm | the four XML mouths | RJ, balanță, jurnale (§7) |
| 1 | RO e-Factura sales + purchases, settlement by bank | plătitor TVA lunar | `iesire_/intrare_factura_xml`, `incasare_/plata_xml` | RJ, balanță, jurnale |
| 2 | bank statements: fees, transfers, unmatched lines | plătitor | `incasare_/plata_xml`; fees keyed | RJ, balanță |
| 3 | storno (both sides) | plătitor | storno mouths (after Loop 0 §3) | jurnale |
| 4 | TVA la încasare | încasare | invoice + settlement mouths | jurnale with neexigible columns, 4428 |
| 5 | expense reports, bonuri with and without CUI | bonuri | DBF/nota decision (D7) or keyed | RJ, balanță |
| 6 | abroad: foreign invoices both sides, reverse charge | abroad | `FacturaTip` "T" if Loop 0 proves it | jurnale, D390/D300 inputs |
| 7 | non-payer reverse charge (WP-D3) | neplătitor | as Loop 6 | balanță 4423/446x |
| 8 | payroll | plătitor | keyed (no mouth) | RJ, balanță |
| 9 | close and filings across a quarter | all five | — | full report pack × 3 months |
| 10 | volume and mix: realistic months, all firms | all five | all | all |
| 11+ | the **possible** rows left in `SURFACE.md`, in slices the owner orders | | | |

The client types are today's five synthetic firms (`synthetic/firms.py`), each set up once as
a SAGA C test firm with the **same invented CUI**, so a SAGA export maps onto its synthetic
tenant with no translation.

### B6. What gets built for the program (WPs, after Part A)

1. **Surface states** in `coverage.py` and `SURFACE.md` generated from it (possible / synthetic
   / saga / out); a loop's evidence file marks rows **saga**.
2. **Loop kit**: `python -m poarta_contabila.loops prepare <loop>` writes, per SAGA test firm,
   the import folders in SAGA's file names and a keying list for documents with no mouth;
   `… read <loop> <exports>` runs reconcile + close against the uploaded exports and writes
   the three diffs and the proposed gap list.
3. **Readers pinned to real exports**: each loop's real SAGA exports become fixtures; the
   readers' tests run on them.
4. **Simulated book calibrated**: `synthetic/books.py` renderers checked against the same real
   exports (the third diff at zero), so synthetic-only scenarios stay honest between loops.

### B7. SAGA WEB, after SAGA C

SAGA WEB is no longer its own track. Once a client is on it (and not before):

1. Amendment: SAGA WEB as a second sink product (XML → API `Import` → human finish → Validare).
2. A **parity loop**: the fixtures of every loop already **saga** are imported through SAGA
   WEB's API, finished in its screen, exported. Passes when the exports equal SAGA C's.
3. Only rows proven by parity are **saga-web**; the transport WP (`RESEARCH_LOG.md` R5:
   single-writer rotating key in Postgres, staged import → `wait_validare`) follows.

---

## Part C — Order and decisions

Order: Part A (two build sessions; one owner review of `LAW.md`) → Loop 0 (owner) → B6 kit →
Loops 1 … n. Part A does not wait for Loop 0, and Loop 0 does not wait for Part A.

| # | Decision | Recommendation |
|---|---|---|
| D1 | Tidy before the loop program | yes |
| D2 | `LAW.md`: amendments folded into rules with stable ids, history only in git | yes; you review the text before it replaces `00_LAW.md` |
| D3 | Delete `docs/BUILD_DONE.md`, `docs/CATALOG_GAPS.md`, `annex/`, `docs/harvest/` (tag `pre-tidy` keeps them) | yes, after the harvest's unbuilt items are in `SURFACE.md` |
| D4 | WP numbers continue (WP-76 …) rather than restart | continue (git history keeps meaning) |
| D5 | `catalog/60_harvest/` renamed (e.g. `60_practice/`) | yes, or keep the name if you prefer |
| D6 | Client-type matrix = the five synthetic firms; others added as **possible** rows | yes; add any client type you know is coming |
| D7 | Slices with no XML mouth (expenses, bonuri, payroll, fees): keyed by you from a list, or wait for `nota_nc_dbf` | keyed in loops; the DBF mouth decision after Loop 5 shows the volume |
| D8 | Your time: one SAGA C session per loop, 10–30 documents per firm-month at first | confirm, or set the budget |
| D9 | Language: English prose, Romanian fiscal terms, as today | keep |
