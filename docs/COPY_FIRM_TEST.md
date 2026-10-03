# Copy-firm test — what the owner runs in SAGA C, and what to send back

Proves the four `draft` mouths (WP-03, WP-19) and settles the `[de confirmat]` formats in
`RESEARCH_LOG.md` R1. Everything here is invented data in a **new, empty test firm**: no
client's database, no real CUI, nothing from it ever comes back into this repo except the
files and answers listed in §4.

Use the fixtures from this repo's current head: `fixtures/saga/iesire.xml`, `intrare.xml`,
`incasare.xml`, `plata.xml`. Do not edit them; if SAGA refuses one, the refusal is the
answer.

## 1. Set up the test firm (once)

1. Administrare → Configurare societăți → add a firm:
   - Denumire `Firma Test SRL`; **Cod fiscal `1000009`** (no `RO`; invented, valid check digit:
     the fixtures route on it); Nr. Reg. Com. any (`J40/1/2026`).
   - plătitor de TVA, lunar, **TVA la plată** (not la încasare); Romanian VAT 21% available.
   - Preluare date contabile: firm without activity, start month **09/2026** → Validare.
2. Plan de conturi: add the analytic **`5121.01`** (bancă test).
3. Do **not** add any partner: whether the invoice import creates `Client Test SRL` /
   `Furnizor Test SRL` (CUI `20000005`) by itself is one of the questions.
4. Do not close September.

## 2. Import the four files, in this order

For **each** file:

1. Administrare → Întreținere BD → Salvare → Start. Note the archive name
   (`ZZ-LL-AAAA_N.ZIP`).
2. Copy **only that file** into an empty folder (e.g. `C:\poarta\run1\`).
3. Diverse → Import date → that folder → sync **"Nr.+data"** → import.
4. Write down exactly what SAGA said (message text, or a screenshot).

| # | File | Expected screen | Then |
|---|---|---|---|
| 1 | `iesire.xml` | Ieșiri, invoice `FX-101` of 15.09.2026, client `Client Test SRL`, 2 lines, 182.11 | Validare (by you) |
| 2 | `intrare.xml` | Intrări, invoice `A-77` of 20.09.2026, supplier `Furnizor Test SRL`, 1 line, 242.00 | Validare |
| 3 | `incasare.xml` | Jurnal de bancă on `5121.01`, 20.09.2026, 182.11, against FX-101 | — |
| 4 | `plata.xml` | Jurnal de bancă on `5121.01`, 25.09.2026, 242.00, against A-77 | — |

Then two guard tests:

5. Import `iesire.xml` **again** with "Nr.+data": expected — nothing new imported.
6. Import `intrare.xml` once more **without** sync, then "Anulează importul" on it: expected —
   the second copy disappears, the validated first one stays.

## 3. SAGA's own sample XML (settles formats)

In the test firm, Ieșiri → add an invoice **by hand**:

- client: a new client `Client Format SRL`, CUI typed as **`RO20000005`**;
- number `FMT-1`, date 30.09.2026, scadență 30.10.2026;
- line 1: `Serviciu A`, UM `buc`, cantitate **1.5**, preț **12.3456**, TVA **21%**;
- line 2: `Serviciu B`, UM `ora`, cantitate **2**, preț **10**, TVA **11%**;
- Validare → Tipărire → in the list at the top choose **"Formular PDF"** → print.
  SAGA copies the PDF **and its XML** to `TEMP\Facturi` (the temp folder is set in
  Administrare → Întreținere BD → General; default `C:\TEMP\`).

Then **Stornare** on `FMT-1` (gives `FMT-1s`, negative), Validare, and print it with
"Formular PDF" the same way. This second XML shows how SAGA writes a storno, which the
storno mouths need before they are built.

Then one more invoice by hand in Ieșiri, `FMT-2` of 30.09.2026, to a new **foreign** client
`Client Extern BV`, country `NL`, VAT id typed as **`NL000099998B57`** (invented), one line
100.00 with the VAT SAGA proposes for an EU service; Validare, print with "Formular PDF". Its XML
shows how SAGA writes a foreign VAT id in `ClientCIF` and the country tag (OWNER_CHECKLIST,
foreign VAT id on the mouth).

## 4. Send back

1. The three XML files from `TEMP\Facturi` (`FMT-1`, `FMT-1s`, `FMT-2`); the PDFs are optional.
2. For each of the four imports and the two guard tests: SAGA's message, and whether the
   result matches the table (screenshot of the document is enough).
3. After steps 1–2 (invoices validated): the **notă contabilă** of each invoice (screenshot of
   "Notă contabilă"), and the partners SAGA now has — code, name, cod fiscal (with or without
   `RO`), analytic (`4111.000xx` / `401.000xx`).
4. After steps 3–4: the bank note (accounts on each side), and Situație clienți / furnizori:
   are FX-101 and A-77 shown as paid (neachitat 0)? — i.e. did `FacturaID` / `FacturaNumar`
   link them.
5. The rights the import needed: which user ran it (Admin?), and, if you try, whether an
   "Operare" user with validare/devalidare/modificare/ștergere off can run Import date.

## 5. Optional — TVA la încasare (settles the 4428 bookings)

In a **second** test firm (cod fiscal `2000007`, invented, valid check digit) set up as in §1
but **TVA la încasare**:

1. Ieșiri: invoice `INC-1`, client `Client Test SRL` (`20000005`), one line 100.00 + 21% TVA,
   validate.
2. Intrări: invoice `INC-2` from `Furnizor Test SRL` (`20000005`), one line 50.00 + 21%,
   validate.
3. Jurnal de bancă: collect **half** of `INC-1` (60.50) and pay all of `INC-2` (60.50), each
   associated to its invoice.
4. Send the notes of all four (accounts on each side, analytics as shown: `4428.TI` / `4428.TP`
   or otherwise), the balance of 4426 / 4427 / 4428 and their analytics, and the purchase and
   sales journals exported the way you export them for clients (Excel), with their column
   headers.

This tells the code where SAGA books VAT at invoice and at payment under TVA la încasare, and
which columns carry the neexigible VAT (control `M1_8_4428_open`).

Each green answer goes on the module row (`fixture`, `approved_at`) in
`catalog/30_cale/ARTICOLE_WRITE_MODULE_v1.yaml`; a module becomes `active` only then.

## 6. The agent's user (settles ARCHITECTURE §13)

§4.5 asks which user ran the import. Here it is tested on purpose:

1. Administrare → Configurare utilizatori: add a user `AGENT`, type **Operare**, with
   validare, devalidare, modificare and ștergere **off**, access to `Firma Test SRL` only.
2. Logged in as `AGENT`: Diverse → Import date on a copy of `iesire.xml` with its number changed
   by hand to `FX-102` (so sync "Nr.+data" lets it in).
3. Still as `AGENT`: try to validate it, and to devalidate `FX-101`. Both must be refused.
4. As Admin: close September. As `AGENT`: import a file dated in September again.

Send back: whether step 2 worked (if not, SAGA's message: the agent then needs another type
of user, and ARCHITECTURE §13 changes), the messages of steps 3 and 4.

## 7. Reading back: the report pack

The eye reads SAGA's exports, so it needs SAGA's real files, not our renderer's.

After §2 (FX-101 and A-77 validated, both bank lines in), for September, export **the way you
export them for a client**, in Excel:

- Registru jurnal (RJ);
- Balanța de verificare;
- Jurnal de cumpărări and Jurnal de vânzări.

Send the four files. They are invented data, so they can become fixtures in this repo. The code
then parses them with `sinks/exports.py` and `ReportPackEye` on a synthetic tenant: passes when
every column is read without a guess and the snapshot shows FX-101 and A-77 validated.

## 8. Backup and restore

1. Before an import, Salvare → note the archive name.
2. Import `incasare.xml` a second time **without** sync (a duplicate bank line appears).
3. Administrare → Întreținere BD → restore that archive.

Send back: the archive name and folder, and whether the duplicate is gone after the restore
(the agent logs label → archive; restore stays a person's step).

## 9. Optional — a read-only copy of the database (prepares WP-15)

Only on `Firma Test SRL`, never on a client's folder.

1. Close SAGA. Copy the firm's folder (e.g. `C:\SAGA C.3.0\0001`) to `D:\saga-sandbox\0001`.
2. Make the copy read-only for the engine: `gfix -mode read_only D:\saga-sandbox\0001\CONT_BAZA.FDB`
   (with the `gfix` of SAGA's Firebird). A write then fails in the engine, whatever runs the
   query.
3. Read it with `firebird-driver` (not `fdb`, which is for Firebird 2.5):

   ```python
   import os
   from firebird.driver import connect, driver_config

   driver_config.fb_client_library.value = r"C:\Program Files\Firebird\Firebird30_Saga\fbclient.dll"
   con = connect(
       r"D:\saga-sandbox\0001\CONT_BAZA.FDB",
       user="SYSDBA",
       password=os.environ["SAGA_FB_PASSWORD"],
       charset="UTF8",
   )
   ```

   The password stays in a local environment variable: never in a file, this repo or Railway
   (00_LAW §3.2). The folder of the client library may be named differently on your machine.

Send back: SAGA C's version (Help → Despre), the Firebird version, the list of tables, and the
query that finds FX-101 and A-77 with number, date, total and validated flag. Claude Code may
help map the tables here, because the data is invented. Passes when the query's totals and
flags equal §7's exports.

## 10. Optional — Import date without a person

The agent must press Import date; SAGA's help documents only the screen. On the test firm only:
can a script drive Diverse → Import date (folder, sync "Nr.+data", Import) at a fixed window
size, twice in a row, with no manual rescue? If not, v1 stays: the agent prepares the folder and
a person presses Import. Exploring the screen with a model (computer use, Windows-MCP) is
allowed here only, never on a client's firm.

## Then SAGA WEB

The same fixtures and §2–§7 again through SAGA WEB's `Import` and its finish screen
(`RESEARCH_LOG.md` R5). Passes when the result equals SAGA C's: same notes, partners,
analytics, exports. Only once a client is on SAGA WEB.
