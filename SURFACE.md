# Surface — the articol map: possible, synthetic, saga, out

**Generated** by `uv run python -m poarta_contabila.surface --write` from the catalog, the
scenario runs and `surface/` (`possible.yaml`, `out.yaml`, `evidence/`). Do not edit by hand:
edit those files, then regenerate; `tests/test_scenarios.py` fails while this file is stale.

The surface is everything the system has, plans, or will need: articole de cale, source
documents, job kinds, HITL kinds, controls (each as PASS and as FAIL), recon profiles, SAGA
mouths, filings, close kinds, and the rows not yet in the catalog (eyes, workflows, …). Each row
has one state (`BUILD.md` B2):

| State | Means | Set by |
|---|---|---|
| **possible** | named, not yet on a path we run | default; the reason is shown |
| **synthetic** | a passing scenario drives it | `fixtures/scenarios/` through the coverage map |
| **saga** | round-trip through a SAGA C test firm, matched | `surface/evidence/` (owner-approved) |
| **out** | will not be built | `surface/out.yaml` (the owner's decision and reason) |

The program ends when every row is **saga** or **out** (`BUILD.md` B1). A catalog row becomes
`active` only once it is **saga** and the owner approves (LAW L42).

Two rules for the rows not yet in the catalog (§3): **this system keeps no books** (L7), so an
item about posting, a journal or a trial balance enters only as an eye or a control; and **a
legal value is research, not a row** (L40): named, never stated. Their `source` names the item in
the practice harvest (branch `pre-tidy`, `docs/harvest/`; `hWP-…` are its work packages, not
ours). A loop takes rows into the catalog as `draft` (`BUILD.md` B3, step 8) and removes them
from `surface/possible.yaml`; a nuance found during a loop is added there (B4, rule 2).

## 1. Summary

| Rows | possible | synthetic | saga | out | total |
|---|---:|---:|---:|---:|---:|
| articole de cale | 8 | 15 | 0 | 0 | 23 |
| source documents | 8 | 12 | 0 | 0 | 20 |
| job kinds | 2 | 4 | 0 | 0 | 6 |
| HITL kinds | 17 | 10 | 0 | 0 | 27 |
| controls (PASS and FAIL) | 6 | 22 | 0 | 0 | 28 |
| recon profiles | 2 | 4 | 0 | 0 | 6 |
| write modules | 6 | 4 | 0 | 0 | 10 |
| filings | 0 | 8 | 0 | 0 | 8 |
| close kinds | 0 | 2 | 0 | 0 | 2 |
| not in the catalog yet | 50 | 0 | 0 | 0 | 50 |
| **all** | **99** | **81** | **0** | **0** | **180** |

## 2. In the catalog

### articole de cale

| Row | Status | State | Where / why |
|---|---|---|---|
| `close_standard` | draft | synthetic | 20 scenarios: abroad_month, bonuri_decont, live_sample and 17 more |
| `close_tva_incasare` | draft | synthetic | 3 scenarios: incasare_clean, incasare_partial_payment, incasare_vat_differs |
| `extras_statement` | draft | synthetic | 24 scenarios: abroad_month, bonuri_decont, incasare_clean and 21 more |
| `foreign_invoice_inbound` | draft | synthetic | 2 scenarios: abroad_month, live_sample |
| `foreign_invoice_outbound` | draft | synthetic | 1 scenario: abroad_month |
| `foreign_rc_neplatitor` | draft | synthetic | 1 scenario: neplatitor_month |
| `recon_post_standard` | draft | synthetic | 17 scenarios: abroad_month, bonuri_decont, neplatitor_month and 14 more |
| `recon_post_tva_incasare` | draft | synthetic | 3 scenarios: incasare_clean, incasare_partial_payment, incasare_vat_differs |
| `recon_pre_extras` | draft | synthetic | 23 scenarios: abroad_month, bonuri_decont, incasare_clean and 20 more |
| `recon_pre_standard` | draft | synthetic | 22 scenarios: abroad_month, bonuri_decont, incasare_clean and 19 more |
| `recon_pre_storno` | draft | synthetic | 1 scenario: platitor_storno |
| `ro_efactura_inbound` | draft | synthetic | 24 scenarios: abroad_month, bonuri_decont, incasare_clean and 21 more |
| `ro_efactura_outbound` | draft | synthetic | 22 scenarios: abroad_month, bonuri_decont, incasare_clean and 19 more |
| `storno_iesire` | draft | synthetic | 1 scenario: platitor_storno |
| `storno_intrare` | draft | synthetic | 1 scenario: platitor_storno |
| `bon_cu_cui` | draft | possible | parked WP-14: bonuri walk through ArticolBon / bon_via_nota, parked in v1 |
| `bon_fara_cui` | draft | possible | parked WP-14: bonuri walk through ArticolBon / bon_via_nota, parked in v1 |
| `recon_post_bon` | draft | possible | parked WP-14: bonuri walk through ArticolBon / bon_via_nota, parked in v1 |
| `recon_pre_bon` | draft | possible | parked WP-14: bonuri walk through ArticolBon / bon_via_nota, parked in v1 |
| `triage_bon_fork` | draft | possible | no_code_path: folder_triage gates on ArticoleSourceDoc and never binds a folder_triage articol |
| `triage_extras` | draft | possible | no_code_path: folder_triage gates on ArticoleSourceDoc and never binds a folder_triage articol |
| `triage_pair_efactura` | draft | possible | no_code_path: folder_triage gates on ArticoleSourceDoc and never binds a folder_triage articol |
| `triage_place` | draft | possible | no_code_path: folder_triage gates on ArticoleSourceDoc and never binds a folder_triage articol |

### source documents

| Row | Status | State | Where / why |
|---|---|---|---|
| `decont_cheltuieli` | draft | synthetic | 2 scenarios: abroad_month, bonuri_decont |
| `decont_part_evidence` | draft | synthetic | 2 scenarios: abroad_month, bonuri_decont |
| `extras_statement_pdf` | draft | synthetic | 23 scenarios: abroad_month, bonuri_decont, incasare_clean and 20 more |
| `foreign_invoice_xml` | draft | synthetic | 3 scenarios: abroad_month, live_sample, neplatitor_month |
| `ro_efactura_pdf` | draft | synthetic | 1 scenario: abroad_month |
| `ro_efactura_ubl` | draft | synthetic | 23 scenarios: abroad_month, bonuri_decont, incasare_clean and 20 more |
| `sink_balanta_nextup` | draft | synthetic | 2 scenarios: platitor_nextup, platitor_nextup_no_prefile |
| `sink_balanta_saga` | draft | synthetic | 26 scenarios: abroad_month, bonuri_decont, incasare_clean and 23 more |
| `sink_rj` | draft | synthetic | 26 scenarios: abroad_month, bonuri_decont, incasare_clean and 23 more |
| `sink_rj_nextup` | draft | synthetic | 2 scenarios: platitor_nextup, platitor_nextup_no_prefile |
| `spv_register` | draft | synthetic | 28 scenarios: abroad_month, bonuri_decont, incasare_clean and 25 more |
| `workings` | draft | synthetic | 2 scenarios: abroad_month, bonuri_decont |
| `bon_fiscal` | draft | possible | parked WP-14: no route mints a bon since an expense report's receipts are evidence |
| `extras` | draft | possible | no_code_path: statements arrive as PDF only (extras_statement_pdf) |
| `extras_pdf` | draft | possible | no_code_path: superseded by extras_statement_pdf; no route mints it |
| `foreign_invoice` | draft | possible | no_code_path: an invoice from abroad is read only as XML (foreign_invoice_xml); a scan or PDF has no extract, and in an expense report it is evidence |
| `instructions` | draft | possible | no_code_path: no upload route |
| `recon_vendor` | draft | possible | no_code_path: no upload route |
| `stat_salarii` | draft | possible | no_code_path: no upload route; payroll is explained_sink_only (POST /rules) |
| `unknown` | draft | possible | no_code_path: every route names its source doc; none mints 'unknown' |

### job kinds

| Row | Status | State | Where / why |
|---|---|---|---|
| `job_extras_line` | draft | synthetic | 22 scenarios: abroad_month, bonuri_decont, incasare_clean and 19 more |
| `job_foreign_invoice` | draft | synthetic | 3 scenarios: abroad_month, live_sample, neplatitor_month |
| `job_ro_efactura` | draft | synthetic | 22 scenarios: abroad_month, bonuri_decont, incasare_clean and 19 more |
| `job_storno` | draft | synthetic | 1 scenario: platitor_storno |
| `job_bon` | draft | possible | parked WP-14: no route mints a bon |
| `job_extras` | draft | possible | no_code_path: statement packs are line jobs (job_extras_line) |

### HITL kinds

| Row | Status | State | Where / why |
|---|---|---|---|
| `decont_split` | - | synthetic | 2 scenarios: abroad_month, bonuri_decont |
| `explained_rule` | - | synthetic | 1 scenario: platitor_explained_rule |
| `filing_receipt` | - | synthetic | 1 scenario: platitor_clean |
| `need_rj_export` | - | synthetic | 1 scenario: platitor_books_late |
| `recon_ambiguous` | - | synthetic | 1 scenario: platitor_amount_differs |
| `recon_how_mismatch` | - | synthetic | 1 scenario: platitor_other_accounts |
| `v2_close` | - | synthetic | 23 scenarios: abroad_month, bonuri_decont, incasare_clean and 20 more |
| `v3_approve` | - | synthetic | 21 scenarios: abroad_month, bonuri_decont, incasare_clean and 18 more |
| `v4_codit` | - | synthetic | 2 scenarios: platitor_clean, platitor_explained_rule |
| `wait_validare` | - | synthetic | 20 scenarios: abroad_month, bonuri_decont, incasare_clean and 17 more |
| `articol_bon` | - | possible | parked WP-14: bonuri walk through ArticolBon / bon_via_nota, parked in v1 |
| `bon_cui_unclear` | - | possible | no_code_path: decont_split must say whether our CUI is on a receipt part |
| `codit_combo` | - | possible | no_code_path: a CO.DiT soft flag names it; no node asks it |
| `codit_premise` | - | possible | no_code_path: a CO.DiT soft flag names it; no node asks it |
| `control_disposition` | - | possible | no_code_path: the answer's checker exists; no node asks it |
| `decision_menu` | - | possible | no_code_path: no graph node asks it |
| `define_articol` | - | possible | no_code_path: every route's source doc binds exactly one articol de cale |
| `define_class` | - | possible | no_code_path: asked only for source doc 'unknown', which no route mints |
| `define_module` | - | possible | no_code_path: no graph node asks it |
| `name_ambiguous` | - | possible | no_code_path: no graph node asks it |
| `no_counterparty` | - | possible | no_code_path: no graph node asks it |
| `patch_maps` | - | possible | no_code_path: v2_close's patch_maps action holds the month; Lane A maps not built |
| `recon_review_contest` | - | possible | live_only: MODEL_CALLS=dry: llm_review abstains, so nothing is contested |
| `request_devalidare` | - | possible | no_code_path: no graph node asks it |
| `stmt_no_identity` | - | possible | no_code_path: a statement without the tenant's CUI is refused, not asked |
| `which_cui` | - | possible | no_code_path: no graph node asks it |
| `xml_pdf_pair` | - | possible | no_code_path: no graph node asks it |

### controls (PASS and FAIL)

| Row | Status | State | Where / why |
|---|---|---|---|
| `C0_synthetic_parity:FAIL` | draft | synthetic | 11 scenarios: abroad_month, bonuri_decont, incasare_vat_differs and 8 more |
| `C0_synthetic_parity:PASS` | draft | synthetic | 13 scenarios: incasare_clean, incasare_partial_payment, platitor_books_late and 10 more |
| `C1_outbound_complete:FAIL` | draft | synthetic | 6 scenarios: abroad_month, incasare_vat_differs, neplatitor_month and 3 more |
| `C1_outbound_complete:PASS` | draft | synthetic | 18 scenarios: bonuri_decont, incasare_clean, incasare_partial_payment and 15 more |
| `C2_unexplained_empty:FAIL` | draft | synthetic | 8 scenarios: abroad_month, incasare_vat_differs, neplatitor_month and 5 more |
| `C2_unexplained_empty:PASS` | draft | synthetic | 16 scenarios: bonuri_decont, incasare_clean, incasare_partial_payment and 13 more |
| `M1_1_payables_tie:FAIL` | draft | synthetic | 1 scenario: platitor_payables_skew |
| `M1_1_payables_tie:PASS` | draft | synthetic | 21 scenarios: abroad_month, bonuri_decont, incasare_clean and 18 more |
| `M1_1_trade_ext:FAIL` | draft | synthetic | 1 scenario: platitor_trade_accounts_skew |
| `M1_1_trade_ext:PASS` | draft | synthetic | 2 scenarios: platitor_other_accounts, platitor_trade_accounts |
| `M1_2_receivables_tie:FAIL` | draft | synthetic | 1 scenario: platitor_receivables_skew |
| `M1_2_receivables_tie:PASS` | draft | synthetic | 21 scenarios: abroad_month, bonuri_decont, incasare_clean and 18 more |
| `M1_2_trade_ext:FAIL` | draft | synthetic | 1 scenario: platitor_trade_accounts_skew |
| `M1_2_trade_ext:PASS` | draft | synthetic | 1 scenario: platitor_trade_accounts |
| `M1_8_4428_open:FAIL` | draft | synthetic | 1 scenario: incasare_vat_differs |
| `M1_8_4428_open:PASS` | draft | synthetic | 2 scenarios: incasare_clean, incasare_partial_payment |
| `P_prefile_duplicate:PASS` | draft | synthetic | 21 scenarios: abroad_month, bonuri_decont, incasare_clean and 18 more |
| `P_prefile_hard_failures:PASS` | draft | synthetic | 21 scenarios: abroad_month, bonuri_decont, incasare_clean and 18 more |
| `T_regime_4428:FAIL` | draft | synthetic | 1 scenario: neplatitor_vat_on_4428 |
| `T_regime_4428:PASS` | draft | synthetic | 21 scenarios: abroad_month, bonuri_decont, incasare_clean and 18 more |
| `T_regime_442x:FAIL` | draft | synthetic | 1 scenario: neplatitor_vat_on_4423 |
| `T_regime_442x:PASS` | draft | synthetic | 21 scenarios: abroad_month, bonuri_decont, incasare_clean and 18 more |
| `C2_waiting_for_xml:FAIL` | draft | possible | not_computed: a decont_split part carries no number or date to match (owner) |
| `C2_waiting_for_xml:PASS` | draft | possible | not_computed: a decont_split part carries no number or date to match (owner) |
| `M1_9_4424_watched:FAIL` | draft | possible | not_computed: advisory, not computed in v1: INFO only |
| `M1_9_4424_watched:PASS` | draft | possible | not_computed: advisory, not computed in v1: INFO only |
| `P_prefile_duplicate:FAIL` | draft | possible | no_code_path: package runs only after an absent PRE verdict: defence in depth no path reaches |
| `P_prefile_hard_failures:FAIL` | draft | possible | no_code_path: package runs only after an absent PRE verdict: defence in depth no path reaches |

### recon profiles

| Row | Status | State | Where / why |
|---|---|---|---|
| `post_doc_how` | draft | synthetic | 17 scenarios: abroad_month, bonuri_decont, neplatitor_month and 14 more |
| `post_how_4428` | draft | synthetic | 3 scenarios: incasare_clean, incasare_partial_payment, incasare_vat_differs |
| `pre_doc_nr_date` | draft | synthetic | 22 scenarios: abroad_month, bonuri_decont, incasare_clean and 19 more |
| `pre_extras_date_gross` | draft | synthetic | 23 scenarios: abroad_month, bonuri_decont, incasare_clean and 20 more |
| `post_bon_how` | draft | possible | parked WP-14: bonuri walk through ArticolBon / bon_via_nota, parked in v1 |
| `pre_bon_date_gross` | draft | possible | parked WP-14: bonuri walk through ArticolBon / bon_via_nota, parked in v1 |

### write modules

| Row | Status | State | Where / why |
|---|---|---|---|
| `iesire_factura_xml` | draft | synthetic | 19 scenarios: abroad_month, bonuri_decont, incasare_clean and 16 more |
| `incasare_xml` | draft | synthetic | 19 scenarios: abroad_month, bonuri_decont, incasare_clean and 16 more |
| `intrare_factura_xml` | draft | synthetic | 20 scenarios: abroad_month, bonuri_decont, incasare_clean and 17 more |
| `plata_xml` | draft | synthetic | 20 scenarios: abroad_month, bonuri_decont, incasare_clean and 17 more |
| `articole_xml` | draft | possible | no_code_path: no rendered SAGA mouth: tags only from a successful copy-firm import (AGENTS) |
| `bon_via_nota` | draft | possible | parked WP-14: bonuri walk through ArticolBon / bon_via_nota, parked in v1 |
| `nota_nc_dbf` | draft | possible | decision WP-D3: its accounts wait on WP-D3; no DBF renderer |
| `parteneri_xml` | draft | possible | no_code_path: no rendered SAGA mouth: tags only from a successful copy-firm import (AGENTS) |
| `storno_iesire_xml` | draft | possible | no_code_path: no rendered SAGA mouth: tags only from a successful copy-firm import (AGENTS) |
| `storno_intrare_xml` | draft | possible | no_code_path: no rendered SAGA mouth: tags only from a successful copy-firm import (AGENTS) |

### filings

| Row | Status | State | Where / why |
|---|---|---|---|
| `d100_micro` | - | synthetic | 7 scenarios: bonuri_decont, incasare_clean, incasare_partial_payment and 4 more |
| `d100_profit` | - | synthetic | 15 scenarios: abroad_month, platitor_amount_differs, platitor_amount_differs_agent and 12 more |
| `d112_payroll` | - | synthetic | 16 scenarios: abroad_month, bonuri_decont, platitor_amount_differs and 13 more |
| `d300_platitor` | - | synthetic | 19 scenarios: abroad_month, bonuri_decont, incasare_clean and 16 more |
| `d301_neplatitor_rc` | - | synthetic | 3 scenarios: neplatitor_month, neplatitor_vat_on_4423, neplatitor_vat_on_4428 |
| `d390_rc` | - | synthetic | 4 scenarios: abroad_month, neplatitor_month, neplatitor_vat_on_4423 and 1 more |
| `d394_platitor` | - | synthetic | 19 scenarios: abroad_month, bonuri_decont, incasare_clean and 16 more |
| `d406_saft` | - | synthetic | 22 scenarios: abroad_month, bonuri_decont, incasare_clean and 19 more |

### close kinds

| Row | Status | State | Where / why |
|---|---|---|---|
| `close_standard` | draft | synthetic | 20 scenarios: abroad_month, bonuri_decont, live_sample and 17 more |
| `close_tva_incasare` | draft | synthetic | 3 scenarios: incasare_clean, incasare_partial_payment, incasare_vat_differs |

## 3. Not in the catalog yet

### VAT regimes and VAT ties

| Id | Kind | What | State | Source |
|---|---|---|---|---|
| S-VAT-01 | control | non-payer reverse charge seen in SAGA booked with payer mechanics (VAT deducted or netted) | possible | D-07, I-01, G-13 |
| S-VAT-02 | control | one VAT regime per firm-period, read from one place; a regime flip inside an open period held | possible | hWP-01, I-02, CO.DiT `A_FLIP` |
| S-VAT-03 | control | D300 tie: balance 4426/4427/4423/4424 × purchase and sales journals × filed D300 | possible | D-09, hWP-20 |
| S-VAT-04 | control | 4428 at period end without open TVA-la-încasare invoices | possible | G-12, hWP-20 |
| S-VAT-05 | control | 4424 recoverable VAT by origin year, with the prescription horizon (research) | possible | D-08, hWP-18, G-11 |
| S-VAT-06 | control | old-rate invoice after a rate change, its credit note and reissue net to zero | possible | G-23 |
| S-VAT-07 | articol | VAT-registration threshold crossed mid-year (regime change event) | possible | E-2 |
| S-VAT-08 | articol | 50 % deductibility (`TipDeducere` N50) and non-deductible (I) purchase lines | possible | R5 |

### Bank, FX and payment platforms

| Id | Kind | What | State | Source |
|---|---|---|---|---|
| S-BNK-01 | source_doc | bank statement in EUR/USD; lines kept in their currency, never read as RON | possible | D-05, hWP-03/04, G-09, G-18 |
| S-BNK-02 | control | bank reconciled per currency account; an unmapped currency account named | possible | D-05, G-18, I-06 |
| S-BNK-03 | control | month-end FX revaluation seen in SAGA; implied rate far from BNR's held for a person | possible | D-06, hWP-25, G-17 |
| S-BNK-04 | source_doc | payment-platform activity export (card acquirer, PSP) | possible | C-F10, hWP-27 |
| S-BNK-05 | source_doc | statement PDFs of more banks (parser per bank) | possible | C-F9, hWP-27 |
| S-BNK-06 | control | a bank account with no receipts in a month with sales | possible | I-03, D-18 |

### Partners, openings, takeover

| Id | Kind | What | State | Source |
|---|---|---|---|---|
| S-PRT-01 | control | partner identity: tax-ID normalisation, check digit, blank-ID foreign partners kept apart | possible | D-17, hWP-17, I-10, G-26 |
| S-PRT-02 | control | second tax id of the client (VAT-only id) on an incoming invoice | possible | G-08 |
| S-PRT-03 | control | sub-ledger ties: 401/4111 analytics sum to the synthetic; a partner with both sides at take-on | possible | D-02, hWP-12, G-02, G-27 |
| S-PRT-04 | workflow | takeover of a new client: opening balances, open items, off-balance memo (class 8), cut-off date | possible | D-11, hWP-13, H-03, G-03 |
| S-PRT-05 | mouth | SAGA take-on grid and open-items import | possible | C-F3, hWP-24 |
| S-PRT-06 | mouth | partner import (DBF or `CLI_`/`FUR_` XML) | possible | C-F4, `parteneri_xml` |
| S-PRT-07 | control | e-Factura and filings never re-sent for periods before go-live | possible | I-14 |

### Close, corrections, completeness

| Id | Kind | What | State | Source |
|---|---|---|---|---|
| S-CLS-01 | control | completeness: expected documents per month (SPV register, recurring suppliers, payroll) vs what arrived | possible | D-18, hWP-14, I-03 |
| S-CLS-02 | control | must-be-zero anomalies: VAT accounts at a non-payer, P&L carried into a new year, stale 473, mirror pairs | possible | hWP-14, G-04, G-24 |
| S-CLS-03 | control | income candidate: a domestic credit with no sales invoice within a window | possible | G-07 |
| S-CLS-04 | close_kind | close order with FX and tax steps; a step declared, not implied | possible | D-12, hWP-15, I-17 |
| S-CLS-05 | workflow | correction routing by filing status: reopen and post in the month if not filed, storno dated today if filed | possible | D-14, hWP-10, H-06, G-19 |
| S-CLS-06 | control | a closed month is sealed: a later change shows as a superseded close, never silently | possible | B-04, hWP-11 |
| S-CLS-07 | control | cut-off: an invoice for services of a closed prior period | possible | G-20 |
| S-CLS-08 | workflow | year end: December close → financial statements → annual returns | possible | H-10, G-28 |
| S-CLS-09 | control | balance rules at close (accounts that must not carry a balance, or a sign) | possible | D-15 |

### Filings and obligations

| Id | Kind | What | State | Source |
|---|---|---|---|---|
| S-FIL-01 | filing | D398 (OSS), D101 (annual profit tax), annual financial statements, D205, D207, F4109, D700, D100 non-resident WHT | possible | E-1 |
| S-FIL-02 | workflow | filings calendar per client: deadlines with the non-working-day roll, zero-filing rules, "only months with operations" | possible | E-1, hWP-09, I-15 |
| S-FIL-03 | control | obligation state per filing: must file × filed (receipt) × books ready; a filing closes by its receipt | possible | E-3, B-09, H-11 |
| S-FIL-04 | source_doc | ANAF receipt PDF (recipisă) read into its filing | possible | C-F8, `filing_receipt` |
| S-FIL-05 | eye | D406 / SAF-T as filed: read, readiness, validate | possible | C-F6, C-F7, hWP-26 |
| S-FIL-06 | control | profit tax quarterly step; micro rate by quarter of crossing (research) | possible | D-13, hWP-19, G-16 |
| S-FIL-07 | control | dividend paid without withholding record | possible | G-22 |

### Cross-border and marketplaces

| Id | Kind | What | State | Source |
|---|---|---|---|---|
| S-XB-01 | control | OSS: the B2C EU threshold as a switch with its crossing date; later invoices need destination VAT | possible | D-10, hWP-35, G-15 |
| S-XB-02 | control | VIES classification of EU partners; D390 rows | possible | hWP-35 |
| S-XB-03 | articol | marketplace clearing: payouts net of fees, gross sales recognised, clearing accounts at zero | possible | D-16, hWP-31, G-05, G-06 |

### Payroll and income

| Id | Kind | What | State | Source |
|---|---|---|---|---|
| S-PAY-01 | source_doc | payroll statement (`stat_salarii`) on a route, against D112 | possible | E-1, Loop 8 |
| S-PAY-02 | control | 421/431/444 tie to D112 | possible | E-1 |

### Workflows for one accountant with many clients

| Id | Kind | What | State | Source |
|---|---|---|---|---|
| S-WF-01 | workflow | engagement backlog per client: one list of what is open, who it waits on | possible | B-01, hWP-29 |
| S-WF-02 | workflow | request and chase loop: missing documents → a drafted request to the client, grouped by addressee | possible | H-02, P-1, P-3 |
| S-WF-03 | workflow | status digest with two audiences (the accountant, the client) | possible | P-6 |
| S-WF-04 | hitl | decision menu with options and a recorded decision (not only approve/edit/reject) | possible | H-05, hWP-32, B-08 |
| S-WF-05 | workflow | review campaign: report before correction, then arbitration | possible | H-07, I-M07 |
| S-WF-06 | workflow | onboarding against a golden reference; external trial-balance compare | possible | B-12, hWP-30, H-08 |
| S-WF-07 | workflow | rules and workflow version stamped on every run and report | possible | hWP-34, B-05 |
| S-WF-08 | control | no client's data in another client's run or projection (PII zoning) | possible | I-05, I-16, B-11, hWP-28 |

## 4. Scenario specs not yet in `fixtures/scenarios/`

The harvest's synthetic specs G-01 … G-28 (invented numbers; branch `pre-tidy`,
`docs/harvest/CATALOGUES.md` §G) are the first source for each slice's scenarios. Each loop
translates the specs of its slice into scenario YAML as eye and control checks, not postings.
