"""Synthetic firms, documents and books: seeded, invented, the same bytes every run.

- :mod:`.firms` — five invented firms whose CO.DiT differs where the paths differ (TVA
  plătitor; TVA la încasare; neplătitor micro buying EU services; one trading abroad; one
  with bonuri and expense reports), their partners, bank account and opening balances.
- :mod:`.docs` — the documents a path reads: SPV zips (invoice + semnătură) in and out,
  credit notes, foreign invoices (XML and PDF), bonuri fiscale (with and without our CUI),
  bank statements (PDF + tables, both directions), expense reports with parts, a payroll
  statement (evidence).
- :mod:`.books` — what those documents leave in SAGA, posted the way SAGA posts them (not the
  way this system expects): registru jurnal, balanță, jurnal de cumpărări / vânzări, NextUp's
  journal and balance, the SPV register; and named defects (missing from the books, in the
  books with no document, amount or VAT differs, posted another way, …).

Rules (BUILD.md, the synthetic-data program): every CUI passes ``cui_is_valid`` and is
invented (``1001…`` firms, ``2001…`` partners; never smoke's ``1000009``); IBANs use the
non-existent bank code ``AAAA``; names say SINTETIC / FURNIZOR / CLIENT; amounts are drawn
from a seed. The same seed gives the same bytes: zip and workbook timestamps are fixed.
Shapes are only those ``fixtures/`` already holds (no SAGA XML tag or export column beyond).
"""

from poarta_contabila.synthetic.books import Book, Entry
from poarta_contabila.synthetic.docs import (
    BankLine,
    Bon,
    ExpenseReport,
    Invoice,
    Payroll,
    Statement,
    Workings,
)
from poarta_contabila.synthetic.firms import FIRMS, Firm, Party, firm

__all__ = [
    "FIRMS",
    "BankLine",
    "Bon",
    "Book",
    "Entry",
    "ExpenseReport",
    "Firm",
    "Invoice",
    "Party",
    "Payroll",
    "Statement",
    "Workings",
    "firm",
]
