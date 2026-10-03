# Catalog gaps — data → catalog (WP-73)

Status: **proposed, waiting on the owner.** Nothing below is in the catalog. Each row the owner
accepts enters as `status: draft` (00_LAW §7); a refused row is struck here with the reason.

## How this list was made

Three firms × two months (`2026-06`, `2026-07`), drawn from seed 73 by
`poarta_contabila.synthetic.months.realistic` without choosing any document's path:
`realistic_abroad`, `realistic_neplatitor`, `realistic_bonuri` (`fixtures/scenarios/`). That is
251 documents, 37–51 per month (SPV purchases and sales, credit notes, invoices from abroad as
XML, expense reports with random parts, payroll, statements that pay, collect, part-pay and
pay two invoices at once). The books carry noise as SAGA would: a document missing, one with
no document here, a sale booked at another amount. Everything was run end to end, dry, with
the simulated SAGA agent. The WP-72 scenarios that showed the same gap are named too.

    uv run python -m poarta_contabila.scenarios realistic_abroad realistic_neplatitor realistic_bonuri
    uv run python -m poarta_contabila.coverage          # data → catalog section

Where they ended (267, counting each part an expense report was split into):

| End | Count | |
|---|---|---|
| acked, POST `how_ok` | 215 | statement lines 88, purchases 79, sales 48 |
| `already_in_sink` | 10 | salaries and fees SAGA already held |
| `wait_validare` (never matched in SAGA) | 9 | the noise: a sale booked at another amount, a purchase missing from the books |
| `needs_human` with an articol | 7 | credit notes — **G4**, **G5** |
| refused at the door | 5 | XML invoices from abroad — **G1** |
| a Job minted, never bound | 8 | bon and foreign parts of expense reports — **G2** |
| a part with no Job | 13 | report containers and workings (by design), PDF-only RO parts — **G3** |

Every month ended material: C0, C1 and C2 failed in all six. The noise accounts for part of
that, as it should. The rest comes from G1, G2, G3, G4–G5 and G6.

No document asked `define_articol`, `define_class` or `define_module`, and no close blocker
fell outside a control.

---

## Proposed catalog rows (owner: accept / refuse each)

### G1 · XML invoices from abroad are refused at the door

- **What happened.** A UBL invoice from an EU supplier (VAT id `DE…`, `ES…`, country ≠ RO) is
  read as `ro_efactura_ubl`. That row's identity gate needs a RO counterparty CUI, so the
  upload is refused (`emit gates failed: ['identity_gate']`). SAGA holds the invoice anyway, so
  it is unexplained at the close (C2) and its 401 / 4426 / 4427 are off parity (C0).
- **Shown by.** `realistic_abroad` (2606-x2, 2607-x1, 2607-x2), `realistic_neplatitor`
  (2606-x1, 2607-x1), `neplatitor_month`, `abroad_month`.
- **Proposed.** A source doc for e-invoices from abroad that arrive as XML (A2 §1 already says
  the XML is the primary), bound to the existing foreign articole. The upload route sends a
  UBL whose counterparty has no RO CUI there instead of to `ro_efactura_ubl` (a code change
  that follows the row).

```yaml
# catalog/60_harvest/ARTICOLE_SOURCE_DOC_ADD_v1.yaml (additive)
  - source_doc_id: foreign_invoice_xml
    schema_version: "1"
    status: draft
    fiscal_class: foreign_invoice
    aisle: "20_foreign_invoice/{inbound|outbound}/{id}/"
    our_role_default: either
    posting_eligible: true
    emit_on_incomplete: false
    primary:
      required_kinds: [xml]
      companions_are: additional
      missing_aisle: null
    pairing: {with: [foreign_invoice], key: [number, date]}
    extract: {backend: ubl, skip_if: []}
    identity:
      needs_tenant_on_doc: false
      needs_counterparty_cui: false   # a foreign VAT id, not a RO CUI
      bon_cui_fork: false
    flux_candidates: [foreign_invoice_inbound, foreign_invoice_outbound, foreign_rc_neplatitor]
    note: "A2 §1: an e-invoice from abroad as UBL XML is the primary; its PDF is a companion."

# catalog/20_document/ARTICOLE_JOBS_v1.yaml — job_foreign_invoice
    source_doc_ids: [foreign_invoice, foreign_invoice_xml]
```

- **Will not be enough alone.**
  - `intrare_factura_xml` refuses a non-RON document (the FX engine is parked, WP-18). A
    payer's EUR invoice would bind `foreign_invoice_inbound` and then stop at the package.
  - `foreign_rc_neplatitor` stays always-HITL until WP-D3.
  - `no_counterparty` would become reachable.

### G2 · Bon and foreign parts of an expense report mint Jobs that never start

- **What happened.** `decont_split` makes a `bon_fiscal` part a `job_bon` and a
  `foreign_invoice` part a `job_foreign_invoice`. Neither has a route that starts its thread:
  bonuri are parked (WP-14), and foreign invoices have no extract. The jobs sit at `ingested`
  forever. The close never counts them (the expected set only holds jobs with a document on
  their thread), while SAGA posts them through 542. Their VAT (4426) and supplier lines are
  then off parity (C0).
- **Shown by.** `realistic_bonuri` (2606-b1, 2607-b0/b1/b2), `realistic_abroad` (2606-dx0,
  2606-dx1, 2607-dx1, 2607-b2), `bonuri_decont`, `abroad_month`.
- **Proposed.** Until WP-14, a receipt or foreign invoice inside an expense report is evidence
  for the report's 542 settlement, not a posting source (SAGA posts the report). The report's
  children name evidence rows, so no Job is minted.

```yaml
# catalog/60_harvest/ARTICOLE_SOURCE_DOC_ADD_v1.yaml (additive)
  - source_doc_id: decont_part_evidence
    schema_version: "1"
    status: draft
    fiscal_class: decont
    aisle: "50_decont/{period}/parts/"
    our_role_default: inbound
    posting_eligible: false
    emit_on_incomplete: false
    primary: {required_kinds: [pdf, jpeg, png], companions_are: additional, missing_aisle: null}
    pairing: {with: [decont_cheltuieli], key: []}
    extract: {backend: none, skip_if: []}
    identity: {needs_tenant_on_doc: false, needs_counterparty_cui: false, bon_cui_fork: true}
    flux_candidates: []
    note: "A receipt or a foreign invoice inside an expense report: evidence of its 542
      settlement, posted in SAGA with the report (A2 §5, [de confirmat]). Until WP-14."

# decont_cheltuieli.split.children: bon_fiscal and foreign_invoice → decont_part_evidence
    split:
      children: [decont_part_evidence, ro_efactura_ubl, ro_efactura_pdf, workings]
      hitl: decont_split
```

- **And, whatever is decided.** C1 should count every Job of the month, including one minted
  with no thread (a code change). Today such a Job is invisible to the close.
- **The 542 settlement itself** (A2 §5, "not built in v1") stays open. Its turnover is not
  watched.

### G3 · An expense report's RO invoice that came as PDF only: SAGA holds it, the close calls it unexplained

- **What happened.** By A2 a PDF-only part of a company-to-company invoice waits in
  `_incomplete_spv` for its SPV XML, with no Job. The accountant posts it in SAGA meanwhile,
  so the close lists it as unexplained (C2) with no link to the waiting part.
- **Shown by.** `realistic_neplatitor` 2607 (FA 260723, FA 260725), `realistic_abroad`,
  `abroad_month` (dec_pdf).
- **Proposed.** An advisory control that names such a document as a part waiting for its
  XML. C2 stays blocking, but the person sees why, and that uploading the SPV zip clears it.

```yaml
# catalog/60_harvest/ARTICOLE_CONTROLS_v1.yaml
  - control_id: C2_waiting_for_xml
    schema_version: "1"
    status: draft
    layer: v2
    severity: advisory
    check: "an unexplained sink document whose supplier CUI, number and date match a part
      waiting in _incomplete_spv is named as waiting for its SPV XML"
    watched: []
    epsilon: "0.00"
    on_fail: [hitl]
    note: "Does not clear C2. The SPV zip of the part settles it (A2 §5)."
```

### G4 · No PRE articol takes a credit note

- **What happened.** Every `reconcile_sink` PRE row has `is_storno: false`. A credit note's PRE
  check therefore finds "no single PRE articol" and waits on `recon_ambiguous`, every time,
  even when the books hold it exactly.
- **Shown by.** `realistic_*` (7 credit notes), `platitor_storno`.
- **Proposed.** A PRE row for credit notes, on the same number / date profile. It is a new
  articol inside existing enums, so not an amendment (§7). It must also be listed in
  `ArticoleGraph.reconcile_sink.allowed_flux`; that list changes no node or edge.

```yaml
# catalog/40_sink/ARTICOLE_RECONCILE_v1.yaml — flux
  - articol_id: recon_pre_storno
    graph_id: reconcile_sink
    schema_version: "1"
    status: draft
    stage: pre
    filters: {}
    extra_filters: {is_storno: true}
    require: {}
    forbid: {}
    profile_id: pre_doc_nr_date
    hitl: on_contest_or_ambiguous
    write_modules: []

# catalog/30_cale/ARTICOLE_GRAPH_v1.yaml — reconcile_sink.allowed_flux: + recon_pre_storno
```

### G6 · C0's implied turnover ignores the firm's TVA regime

- **What happened.** Layer 1 implies 401 / 4426 for every purchase and 4111 / 4427 for every
  sale. SAGA posts otherwise for three regimes, so C0 fails on correct books:
  - **TVA la încasare:** 4428 at the invoice, moved to 4426 / 4427 as it is paid
    (`incasare_clean`).
  - **Neplătitor:** VAT carried in the cost, no 4426 (`neplatitor_month`,
    `realistic_neplatitor`: 4426 short by 4 650.09 and 7 248.26).
  - **Payer buying with reverse charge:** 4426 = 4427 on the base (`abroad_month`,
    `realistic_abroad`).
- **Proposed.** C0's rule says how each regime implies VAT. The check stays blocking and the
  watched list is unchanged. The accounts are what the synthetic books assume; an accountant
  must confirm them (`[de confirmat]`).

```yaml
# catalog/60_harvest/ARTICOLE_CONTROLS_v1.yaml — C0_synthetic_parity
    note: "… Implied VAT by CO.DiT (draft, [de confirmat]): tva_platitor + tva_exig_livrare →
      purchase 4426 Dr, sale 4427 Cr; tva_la_incasare → 4428 at the invoice, and on a bound
      bank line its VAT share 4428 → 4426 (payment) / 4428 → 4427 (receipt); tva_neplatitor /
      tva_scutire_mici → purchase VAT in the cost (nothing on 4426); reverse charge for a payer
      → 4426 Dr = 4427 Cr on the base at the standard rate; for a neplătitor → WP-D3."
```

---

## Not catalog rows: code or owner decisions found on the way

| # | What | Shown by | Needs |
|---|---|---|---|
| G5 | Storno SAGA mouths (`storno_intrare_xml`, `storno_iesire_xml`) are not rendered: an approved credit note stops at `needs_human` ("no single rendered mouth"). | `platitor_storno`, realistic (7) | SAGA's import format for a storno, from a copy-firm import (AGENTS: no invented tags). Owner. |
| G7 | `M1_8_4428_open` is not computed, so it fails closed: every TVA la încasare month is material. | `incasare_clean` | Code: Σ 4428 still open on unpaid la-încasare documents (from bound bank lines) vs bal(4428). |
| G8 | With SAGA's report pack (purchase / sales journals) uploaded, the eye reads only those, which hold no bank documents. A statement line SAGA already holds is not found and is asked to be approved as new; approved, it would be packaged twice (SAGA's Nr.+data sync is the only guard left). | `platitor_report_pack` | Code: take bank documents from the registru jurnal even when the report pack is read. |
| G9 | A NextUp firm's document uploaded before it is posted in NextUp stops at `needs_human` (no PreFile, A2 §3; fixed in this program). Nothing settles it later, so the month stays material (C1). | `platitor_nextup_no_prefile` | Owner: e.g. wait until NextUp's journal shows it, then `already_in_sink`. |
| G2b | The close does not count a Job minted without a thread (see G2). | `bonuri_decont` | Code. |

## Fixed during the program (own commits, not catalog)

- A packaged bank line was never acked and POST never found its posting: SAGA holds it under
  the bank's reference, in `Banca` (`0f21329`).
- A NextUp firm's documents were packaged for SAGA against A2 §3 (`6b5cb3a`).

## Not gaps

- The noise in the books: a missing purchase, one with no document here, a sale booked at
  another amount. These end at `wait_validare`, unexplained, or off parity, and the month is
  material. That is the gate working.
- Report containers and workings make no Job (A2: evidence). A PDF-only RO part waiting for
  its XML is by design (A2 §5); G3 is only about what the close says meanwhile.
