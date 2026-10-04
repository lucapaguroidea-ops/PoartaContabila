# Catalog Cale — the row-level law

The catalog is the system's ontology: what each document, path, gate, account and question
*means*, and how they connect. The graphs walk it; the domain store (Postgres) holds the data
it is applied to. A row that names no cale is a comment (L4); every row enters as
`status: draft` and becomes `active` only when proven in SAGA C and approved by the owner (L42).

| Folder | Holds |
|---|---|
| `10_lege_firma/` | Pins (rates by year), T* (TVA × exigibility) and F* (legal form × tax) pairs: what is legal for a firm |
| `20_document/` | SourceDoc (what a file is, when it may emit) and Jobs (the posting unit after emit) |
| `30_cale/` | Graph (the four graphs, their allowed articole and HITL kinds), Flux (the articole de cale), WriteModule (SAGA mouths), Bon (parked) |
| `40_sink/` | Reconcile (PRE / POST against what SAGA shows) and Close (the month) |
| `50_control/` | HITL kinds, model roles, the Jev annex and its validation |
| `60_practice/` | Rows learned from practice, **added** to the files above (`mode: additive`): controls, filings, CO.DiT axes, extra source documents, Jobs and HITL kinds, the statement grain |

Loader rule (`poarta_contabila/catalog.py`): files merge by their `catalog:` name; additive
`rows` / `kinds` / `controls` / `filings` append to the base; a duplicate `id` is an error, and
so is an unknown `articol_id` or HITL kind.

## Which file to open

| You are asking | Open |
|---|---|
| What is this file? | `20_document/ARTICOLE_SOURCE_DOC_v1.yaml` + `60_practice/ARTICOLE_SOURCE_DOC_ADD_v1.yaml` |
| May we emit? | SourceDoc + `fixtures/architecture.jsonlogic.json` (`emit`) |
| Which walk? | `30_cale/ARTICOLE_FLUX_v1.yaml` |
| Which Job kind? | `20_document/ARTICOLE_JOBS_v1.yaml` + `60_practice/ARTICOLE_JOBS_ADD_v1.yaml` |
| Which SAGA mouth? | `30_cale/ARTICOLE_WRITE_MODULE_v1.yaml` |
| Which graph node, which HITL kind? | `30_cale/ARTICOLE_GRAPH_v1.yaml` + `50_control/ARTICOLE_HITL_v1.yaml` + `60_practice/ARTICOLE_HITL_ADD_v1.yaml` |
| TVA × exigibility legal? | `10_lege_firma/ARTICOLE_CODIT_T_v1.yaml` |
| Legal form × tax? | `10_lege_firma/ARTICOLE_CODIT_PAIRS_v1.yaml` |
| Rates this year? | `10_lege_firma/ARTICOLE_PINS_v1.yaml` |
| A CO.DiT axis? | `60_practice/ARTICOLE_CODIT_AXES_v1.yaml` |
| Already in the books? | `40_sink/ARTICOLE_RECONCILE_v1.yaml` |
| May we file the month? | `40_sink/ARTICOLE_CLOSE_v1.yaml` + `60_practice/ARTICOLE_CONTROLS_v1.yaml` + `60_practice/ARTICOLE_FILING_v1.yaml` |
| Bon matrix? | `30_cale/ARTICOL_BON_v1.yaml` (parked, WP-14) |
| Statement grain? | `60_practice/ARTICOLE_EXTRAS_GRAIN_v1.yaml`: one Job per movement line, never per statement total |
| May Jev answer this field? | `50_control/JEV_ANNEX_v1.yaml` + `JEV_VALIDATE_V_v1.yaml` (`JEV_ANNEX_EXAMPLE_source_bon.yaml` is a worked example, used by `fixtures/test_jev_validate.py`) |
| Which model, where? | `50_control/ARTICOLE_MODEL_ROLES_v1.yaml` (L28–L33) |

What is not in the catalog yet, and why, is in `SURFACE.md`; which rows a scenario drives is
printed by `uv run python -m poarta_contabila.coverage`.
