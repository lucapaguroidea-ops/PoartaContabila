# Loops — proving the surface in SAGA C

One folder per loop (`BUILD.md` Part B). Invented data only; never a client's firm.

```
loop-NN/
  loop.yaml        the slice, its target rows, its exit criteria, its runs (status: proposed → approved)
  prepared/        written by `uv run python -m poarta_contabila.loops prepare NN`
    STEPS.md       the owner's steps
    <cui>-<firm>/  firm.md (SAGA settings), keying.csv (what has no mouth),
                   import/run-NN/ (our packages, SAGA's file names), simulated/ (what we expect SAGA to show)
  exports/         SAGA's real exports, sent back by the owner: <cui>-<firm>/rj.xls, balanta-YYYY-MM.xlsx,
                   cumparari-YYYY-MM.xls, vanzari-YYYY-MM.xls
  read/            written by `… loops read NN`: REPORT.md (three comparisons, gap list, ledger) and one
                   evidence draft per firm, approved by the owner into surface/evidence/
```

The kit: `poarta_contabila/loops.py`.
