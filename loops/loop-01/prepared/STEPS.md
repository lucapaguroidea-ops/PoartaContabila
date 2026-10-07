# Loop 1 — RO e-Factura sales and purchases, settled through the bank (plătitor TVA lunar)

The first SAGA C loop after Loop 0 (the copy-firm test). One small standard month of the plătitor firm: three purchase invoices and two sales invoices from SPV, one bank statement that pays one purchase and collects one sale (our incasare / plata mouths), a salary and a bank fee (keyed by hand: no mouth). Small on purpose (BUILD.md B4, rule 4): volume is Loop 10.

Invented data only. One SAGA C test firm per folder below; never a client's firm.

- `1001012-platitor/`: 7 files in 1 import folder(s), 10 lines to key

## Exit criteria (fixed before the loop)

- every target row is driven by the run and proposed saga in the evidence draft
- meaning, reader and model comparisons are empty, or each difference is in the gap list with its class and the owner's decision
- every document reaches acked or already_in_sink
- the month closes not material

## Your steps, per firm folder

1. **Set up the firm** in SAGA C as `firm.md` says (once per firm).
2. **Key `keying.csv`** — the opening balances (`sold inițial`), then every line, in date order:
   these are what SAGA must hold besides our imports (no mouth brings them). Journal types as
   given (`Diverse` = notă contabilă; `Banca` = Jurnal de bancă; `Casa`, `Salarii`).
3. **Import the folders in order**: `import/run-01/`, then `run-02/`, … For each:
   Administrare → Întreținere BD → Salvare (note the archive name); Diverse → Import date →
   that folder → sync **"Nr.+data"** → import. Write down SAGA's message if it is not a
   success.
4. **Validate** the imported invoices (Intrări, Ieșiri) yourself.
5. **Export**, for the whole loop and per month, the way you export for a client, into
   `exports/<the same folder name>/`:
   - `rj.xls` — Registru jurnal, all the loop's months;
   - `balanta-YYYY-MM.xlsx` — Balanța de verificare, one per month;
   - `cumparari-YYYY-MM.xls`, `vanzari-YYYY-MM.xls` — Jurnal de cumpărări / vânzări, one per
     month.
   `.xls` or `.xlsx` both read. `simulated/` holds what we expect each file to show: do not
   import it.
6. **Send back** the `exports/` folder, SAGA's messages, and SAGA C's version (Help → Despre).

Then `uv run python -m poarta_contabila.loops read 1` writes the comparisons, the gap
list and an evidence draft for your review.
