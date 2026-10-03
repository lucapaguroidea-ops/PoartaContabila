# Poarta Primară — standalone pack

This directory is the source of truth. Do not open the Word drafts, the harvest zip, or `annex/` unless you are tracing history.

```
INDEX.md                 this file
AGENTS.md                how a coding agent must work
00_LAW.md                unit, lexicon, invariants, locked decisions (§8 amendments)
ARCHITECTURE.md          system to build (self-contained)
BUILD.md                 work packages: the status table, and the open WPs' details
EXTRACT.md               extract adaptor contract
IDEMPOTENCY.md           keys
RESEARCH_LOG.md          external formats/APIs quoted from official pages (or why not)
CATALOG_LOOKUP.md        which YAML to open
catalog/                 Catalog Cale — executable law
  10_lege_firma          Pins, T*, F*
  20_document            SourceDoc, Jobs
  30_cale                Graph, Flux (= căi), WriteModule, Bon (parked)
  40_sink                Reconcile, Close
  50_control             HITL, Jev, model roles
  60_harvest             Controls, Filings, CO.DiT axes, extra HITL — added from practice
poarta_contabila/        the package (ARCHITECTURE §11); ui/ = the review page
tests/                   pytest; DB tests need POARTA_TEST_DSN
fixtures/                synthetic documents and exports, json-logic, jev tests (no client data)
docs/                    owner guides (copy firm, EU route, checklist); BUILD_DONE.md = done WPs
annex/, docs/harvest/    superseded briefs and harvest notes — history, not SoT
```

**Unit you think in:** articol de cale.

**Lege:** Documentul primar nu ia calea fără poartă.

**Product face:** Poarta Primară.  
**Method:** Catalog Cale.  
**Machine:** Graful Primar (four compiled LangGraph graphs).  
**Package:** `poarta_contabila`.

A Flux row in `ARTICOLE_FLUX_v1.yaml` *is* an articol de cale. The filename stays Flux so nothing is lost. Say **cale** / **articol de cale** in prose. Say `articol_id` in code.
