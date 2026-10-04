# Surface — the articol map: possible, synthetic, saga, out

The surface is everything the system has, plans, or will need: articole de cale, source
documents, mouths (writes into SAGA), eyes (reads from SAGA), controls, filings, HITL kinds and
workflows. Each row has one state (`BUILD.md` B2):

| State | Means |
|---|---|
| **possible** | named, not yet on a path we run |
| **synthetic** | a passing scenario drives it (`python -m poarta_contabila.coverage`) |
| **saga** | it went round-trip through a SAGA C test firm and matched (a loop's evidence) |
| **out** | will not be built; the reason is written |

Rows **in the catalog** get their state from `python -m poarta_contabila.coverage` (today:
synthetic, or out of reach with a reason). Until the loop kit generates this file (`BUILD.md` B6, item 1),
this file lists the rows **not yet in the catalog**: all **possible**. They come from the
practice's harvest (kept on branch `pre-tidy`, `docs/harvest/`; the `from` column names the
item there: `C-…`, `D-…`, `G-…` are its catalogue ids, `hWP-…` its own work packages, not ours). Two rules carry over from it:

- **This system keeps no books** (LAW). A harvest item about posting, a journal or a trial
  balance enters only as an eye (what SAGA's exports must show) or a control (a check on them).
- **A legal value is research, not a row.** Rates, thresholds and deadlines below are named,
  never stated: each needs `source`, `as_of`, `certainty` from `RESEARCH_LOG.md` before code
  uses it. The harvest marks many as disputed.

A loop takes rows from here into the catalog as `draft` (owner review, `BUILD.md` B3, step 8); a row
taken is removed from this file. New nuances found during a loop are added here with one
sentence (`BUILD.md` B4, rule 2).

## 1. In the catalog, not yet on a path

Listed by `coverage.py` (`OUT_OF_REACH`), summarised here (2026-10-04):

| Rows | Why not on a path |
|---|---|
| `bon_cu_cui`, `bon_fara_cui`, `recon_pre_bon`, `recon_post_bon`, `job_bon`, `bon_fiscal`, `articol_bon`, `pre_bon_date_gross`, `post_bon_how`, `bon_via_nota` | bonuri parked; receipts in an expense report are evidence only (Loop 5) |
| `nota_nc_dbf` | DBF note mouth: decided after Loop 5 (`BUILD.md` Q7); accounts wait on WP-D3 |
| `parteneri_xml`, `articole_xml`, `storno_intrare_xml`, `storno_iesire_xml` | mouths wait on the copy-firm import (Loop 0 §3) |
| `triage_place`, `triage_pair_efactura`, `triage_bon_fork`, `triage_extras` | `folder_triage` gates on source docs and binds no articol of its own |
| `stat_salarii`, `instructions`, `recon_vendor` | no upload route (payroll is an explained rule today; Loop 8) |
| `M1_9_4424_watched`, `C2_waiting_for_xml` | advisory, not computed |
| `extras`, `extras_pdf`, `foreign_invoice`, `unknown`, `job_extras`, `define_class`, `define_articol`, `stmt_no_identity`, `bon_cui_unclear` | superseded by another row, or refused rather than asked: candidates for **out** |
| `recon_review_contest` | reached only with live model calls (MODEL_CALLS not dry) |
| `which_cui`, `name_ambiguous`, `xml_pdf_pair`, `no_counterparty`, `request_devalidare`, `define_module`, `codit_combo`, `codit_premise`, `decision_menu`, `control_disposition`, `patch_maps` | no graph node asks them yet |

## 2. Possible — VAT regimes and VAT ties

| Id | Kind | What | from |
|---|---|---|---|
| S-VAT-01 | control | non-payer reverse charge seen in SAGA booked with payer mechanics (VAT deducted or netted) | D-07, I-01, G-13 |
| S-VAT-02 | control | one VAT regime per firm-period, read from one place; a regime flip inside an open period held | hWP-01, I-02, CO.DiT `A_FLIP` |
| S-VAT-03 | control | D300 tie: balance 4426/4427/4423/4424 × purchase and sales journals × filed D300 | D-09, hWP-20 |
| S-VAT-04 | control | 4428 at period end without open TVA-la-încasare invoices | G-12, hWP-20 |
| S-VAT-05 | control | 4424 recoverable VAT by origin year, with the prescription horizon (research) | D-08, hWP-18, G-11 |
| S-VAT-06 | control | old-rate invoice after a rate change, its credit note and reissue net to zero | G-23 |
| S-VAT-07 | articol | VAT-registration threshold crossed mid-year (regime change event) | E-2 |
| S-VAT-08 | articol | 50 % deductibility (`TipDeducere` N50) and non-deductible (I) purchase lines | R5 |

## 3. Possible — bank, FX and payment platforms

| Id | Kind | What | from |
|---|---|---|---|
| S-BNK-01 | source_doc | bank statement in EUR/USD; lines kept in their currency, never read as RON | D-05, hWP-03/04, G-09, G-18 |
| S-BNK-02 | control | bank reconciled per currency account; an unmapped currency account named | D-05, G-18, I-06 |
| S-BNK-03 | control | month-end FX revaluation seen in SAGA; implied rate far from BNR's held for a person | D-06, hWP-25, G-17 |
| S-BNK-04 | source_doc | payment-platform activity export (card acquirer, PSP) | C-F10, hWP-27 |
| S-BNK-05 | source_doc | statement PDFs of more banks (parser per bank) | C-F9, hWP-27 |
| S-BNK-06 | control | a bank account with no receipts in a month with sales | I-03, D-18 |

## 4. Possible — partners, openings, takeover

| Id | Kind | What | from |
|---|---|---|---|
| S-PRT-01 | control | partner identity: tax-ID normalisation, check digit, blank-ID foreign partners kept apart | D-17, hWP-17, I-10, G-26 |
| S-PRT-02 | control | second tax id of the client (VAT-only id) on an incoming invoice | G-08 |
| S-PRT-03 | control | sub-ledger ties: 401/4111 analytics sum to the synthetic; a partner with both sides at take-on | D-02, hWP-12, G-02, G-27 |
| S-PRT-04 | workflow | takeover of a new client: opening balances, open items, off-balance memo (class 8), cut-off date | D-11, hWP-13, H-03, G-03 |
| S-PRT-05 | mouth | SAGA take-on grid and open-items import | C-F3, hWP-24 |
| S-PRT-06 | mouth | partner import (DBF or `CLI_`/`FUR_` XML) | C-F4, `parteneri_xml` |
| S-PRT-07 | control | e-Factura and filings never re-sent for periods before go-live | I-14 |

## 5. Possible — close, corrections, completeness

| Id | Kind | What | from |
|---|---|---|---|
| S-CLS-01 | control | completeness: expected documents per month (SPV register, recurring suppliers, payroll) vs what arrived | D-18, hWP-14, I-03 |
| S-CLS-02 | control | must-be-zero anomalies: VAT accounts at a non-payer, P&L carried into a new year, stale 473, mirror pairs | hWP-14, G-04, G-24 |
| S-CLS-03 | control | income candidate: a domestic credit with no sales invoice within a window | G-07 |
| S-CLS-04 | close_kind | close order with FX and tax steps; a step declared, not implied | D-12, hWP-15, I-17 |
| S-CLS-05 | workflow | correction routing by filing status: reopen and post in the month if not filed, storno dated today if filed | D-14, hWP-10, H-06, G-19 |
| S-CLS-06 | control | a closed month is sealed: a later change shows as a superseded close, never silently | B-04, hWP-11 |
| S-CLS-07 | control | cut-off: an invoice for services of a closed prior period | G-20 |
| S-CLS-08 | workflow | year end: December close → financial statements → annual returns | H-10, G-28 |
| S-CLS-09 | control | balance rules at close (accounts that must not carry a balance, or a sign) | D-15 |

## 6. Possible — filings and obligations

| Id | Kind | What | from |
|---|---|---|---|
| S-FIL-01 | filing | D398 (OSS), D101 (annual profit tax), annual financial statements, D205, D207, F4109, D700, D100 non-resident WHT | E-1 |
| S-FIL-02 | workflow | filings calendar per client: deadlines with the non-working-day roll, zero-filing rules, "only months with operations" | E-1, hWP-09, I-15 |
| S-FIL-03 | control | obligation state per filing: must file × filed (receipt) × books ready; a filing closes by its receipt | E-3, B-09, H-11 |
| S-FIL-04 | source_doc | ANAF receipt PDF (recipisă) read into its filing | C-F8, `filing_receipt` |
| S-FIL-05 | eye | D406 / SAF-T as filed: read, readiness, validate | C-F6, C-F7, hWP-26 |
| S-FIL-06 | control | profit tax quarterly step; micro rate by quarter of crossing (research) | D-13, hWP-19, G-16 |
| S-FIL-07 | control | dividend paid without withholding record | G-22 |

## 7. Possible — cross-border and marketplaces

| Id | Kind | What | from |
|---|---|---|---|
| S-XB-01 | control | OSS: the B2C EU threshold as a switch with its crossing date; later invoices need destination VAT | D-10, hWP-35, G-15 |
| S-XB-02 | control | VIES classification of EU partners; D390 rows | hWP-35 |
| S-XB-03 | articol | marketplace clearing: payouts net of fees, gross sales recognised, clearing accounts at zero | D-16, hWP-31, G-05, G-06 |

## 8. Possible — payroll and income

| Id | Kind | What | from |
|---|---|---|---|
| S-PAY-01 | source_doc | payroll statement (`stat_salarii`) on a route, against D112 | E-1, Loop 8 |
| S-PAY-02 | control | 421/431/444 tie to D112 | E-1 |

## 9. Possible — workflows for one accountant with many clients

These feed `BUILD.md` Part D (adjustments) as much as Part B.

| Id | Kind | What | from |
|---|---|---|---|
| S-WF-01 | workflow | engagement backlog per client: one list of what is open, who it waits on | B-01, hWP-29 |
| S-WF-02 | workflow | request and chase loop: missing documents → a drafted request to the client, grouped by addressee | H-02, P-1, P-3 |
| S-WF-03 | workflow | status digest with two audiences (the accountant, the client) | P-6 |
| S-WF-04 | hitl | decision menu with options and a recorded decision (not only approve/edit/reject) | H-05, hWP-32, B-08 |
| S-WF-05 | workflow | review campaign: report before correction, then arbitration | H-07, I-M07 |
| S-WF-06 | workflow | onboarding against a golden reference; external trial-balance compare | B-12, hWP-30, H-08 |
| S-WF-07 | workflow | rules and workflow version stamped on every run and report | hWP-34, B-05 |
| S-WF-08 | control | no client's data in another client's run or projection (PII zoning) | I-05, I-16, B-11, hWP-28 |

## 10. Scenario specs not yet in `fixtures/scenarios/`

The harvest's synthetic specs G-01 … G-28 (invented numbers; on branch `pre-tidy`,
`docs/harvest/CATALOGUES.md` §G) are the first source for each slice's scenarios. None is
taken yet. Each loop translates the specs of its slice into
scenario YAML as eye + control checks, not postings.
