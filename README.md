# Poarta Primară

**What it is.** A system that walks a Romanian accounting practice's *documente primare*
(e-Factura invoices, bank statements, receipts, expense reports) to SAGA C, the accounting
program that keeps the books. It reads each document, decides which path it is on, checks the
gate that path needs, prepares the XML that SAGA imports, and reads SAGA's own reports back to
check the month before it is closed. **It never keeps books and never posts**: SAGA does, and
a person validates every posting.

**For whom.** One accountant keeping many clients' books in SAGA C.

**Why.** No document should reach the books without its gate: *Documentul primar nu ia calea
fără poartă* (`LAW.md` L2). Every exception goes to a person with what the system knows, and
nothing a model says decides a gate. The aim is to steer and speed the accountant's month with
the least friction for enough control: that balance is what the work is heading for (below).

## How it works

```
documents (SPV zips, UBL XML, statement PDFs, expense reports)
  → folder_triage       what is this file, is it primary, may it emit       (batch:)
  → ingest_source_doc   extract → classify → match → check → person approves → package  (job:)
  → SAGA C              the agent imports the XML; a person validates (Validare)
  → reconcile_sink      is it already in the books / was it posted as expected  (recon:)
  → monthly_close       SAGA's report pack against the month's expected set → file or hold  (close:)
```

- **The unit is an *articol de cale*** (L1): a bookkeeping state that already knows its next
  path (*cale*) and the gate (*poartă*) that must open before the document moves.
- **The catalog is the ontology** (`catalog/`): every articol, source document, SAGA mouth,
  question kind, control and model role, as YAML. The four LangGraph graphs walk it; models
  classify inside steps, but edges, mouths and the month close follow fixed rules (L3, L21).
- **The domain store is the data model**: Postgres holds jobs, expected sets, snapshots of
  what SAGA shows, answers and control runs. It is not a ledger (L7).
- **SAGA C is the only mouth and its reports the only eye** (L5, L6). Posting is XML → Import
  date → Validare by a person (L9, L11); the database is never written (L10).
- **Models act only by role, pinned** (L28–L32): Jev (System One) classifies, a GLM model
  (System Two) explains for a person, Gemini reads scans. Client data reaches a model only
  through an EU route, which is not set up yet: today only synthetic firms are processed (L33).
- **People answer through a review page** with no model in between (L26); every answer is
  recorded (L41).

## Where it stands (2026-10-04)

- Built and running on Railway (EU region) for synthetic firms: the four graphs, the HTTP API,
  the review page, model roles (Jev, GLM, Gemini) with their guards, synthetic firms and
  months, a scenario runner and a coverage map. Every catalog row is still `draft`.
- Not built yet (`ARCHITECTURE.md` §17): the Windows agent program that presses Import in
  SAGA C, SAGA proof of any write module, the EU route for client data, the evidence ledger.
- Next (`BUILD.md`): **Loop 0**, the owner's copy-firm test in SAGA C
  (`docs/owner/COPY_FIRM_TEST.md`); then the **SAGA C loops** that prove every articol against
  real SAGA on synthetic data while measuring friction and control; then a **pilot** on a few
  real clients through the EU route; then the **graph loops**, the destination: each graph
  compared as it is, adjusted, and against alternatives, to find its balance of friction and
  control.

## Where things are

| File | Holds |
|---|---|
| `LAW.md` | the rules, `L1` … `L47`, with stable ids; what only the owner may change (L46) |
| `AGENTS.md` | how an agent works here: before any code, the loop, hard bans |
| `BUILD.md` | open work, the programs (SAGA C loops, pilot, graph loops), decisions |
| `ARCHITECTURE.md` | the machine as built: graphs, types, storage, HTTP, package, env; not built yet |
| `SURFACE.md` | what is not in the catalog yet: possible / synthetic / saga / out |
| `RESEARCH_LOG.md` | external formats and APIs, quoted from official pages with dates |
| `catalog/` | the row-level law (`catalog/README.md`: which file to open) |
| `docs/owner/` | the owner's guides: copy-firm test, checklist, EU route setup |
| `poarta_contabila/` | the package (`ARCHITECTURE.md` §11) |
| `tests/`, `fixtures/` | pytest; synthetic documents, SAGA exports and scenarios (no client data, L36) |

History (finished work, superseded briefs, the practice harvest) is in git: branch `pre-tidy`.

## Run it

```bash
uv sync                                   # install
uv run pytest -q                          # tests (DB tests need POARTA_TEST_DSN)
uv run ruff check . && uv run ruff format --check .
uv run python -m poarta_contabila.coverage --no-run   # which catalog rows a scenario drives
```
