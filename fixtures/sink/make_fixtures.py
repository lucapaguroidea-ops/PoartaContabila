"""Generate synthetic witness exports in the real SAGA C / NextUp layouts (A2).

Every company, CUI, number and amount here is invented (CUIs carry valid check digits).
The layouts mirror real exports: header rows, column order, Excel date serials, numeric
account cells with display formats, `%` compound entries, day/month total rows and page
footers. Run:  uv run python fixtures/sink/make_fixtures.py
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import openpyxl
import xlwt

HERE = Path(__file__).resolve().parent
FIRM = "FIRMA TEST SRL   c.f. RO1000009   r.c. J00/000/2020"


def _serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days


def saga_rj() -> None:
    wb = xlwt.Workbook()
    ws = wb.add_sheet("Sheet")
    int_fmt = xlwt.easyxf(num_format_str="########0")
    an5 = xlwt.easyxf(num_format_str="########0.00000")
    an6 = xlwt.easyxf(num_format_str="########0.000000")
    money = xlwt.easyxf(num_format_str="###,###,##0.00")
    dfmt = xlwt.easyxf(num_format_str="m/d/yy")
    seqf = xlwt.easyxf(num_format_str="###,###,##0")
    ws.write(0, 0, FIRM)
    ws.write(3, 0, "REGISTRU JURNAL")
    for c, v in enumerate(["Nr.", "", "", "", "Cont", "Cont", "", "", ""]):
        ws.write(6, c, v)
    for c, v in enumerate(
        ["crt.", "Data", "Explicatie", "Nr. doc", "debitor", "creditor", "Debit", "Credit", "Tip"]
    ):
        ws.write(7, c, v)

    row = 8

    def acct(r: int, c: int, code: str) -> None:
        if code in ("", "%"):
            ws.write(r, c, code)
        elif "." in code:
            whole, frac = code.split(".")
            ws.write(r, c, float(code), an5 if len(frac) == 5 else an6)
        else:
            ws.write(r, c, int(code), int_fmt)

    def entry(seq, d, expl, doc, deb, cred, amount, tip, blank_after=True):
        nonlocal row
        if seq is not None:
            ws.write(row, 0, seq, seqf)
        ws.write(row, 1, _serial(d), dfmt)
        ws.write(row, 2, expl)
        if isinstance(doc, int):
            ws.write(row, 3, doc, int_fmt)
        elif doc:
            ws.write(row, 3, doc)
        acct(row, 4, deb)
        acct(row, 5, cred)
        ws.write(row, 6, amount, money)
        ws.write(row, 7, amount, money)
        ws.write(row, 8, tip)
        row += 2 if blank_after else 1

    def total(label, d_or_month, amount):
        nonlocal row
        ws.write(row, 4, label)
        if isinstance(d_or_month, date):
            ws.write(row, 5, _serial(d_or_month), dfmt)
        else:
            ws.write(row, 5, d_or_month, int_fmt)
        ws.write(row, 6, amount, money)
        ws.write(row, 7, amount, money)
        row += 1

    d1, d2, d3, d4 = date(2026, 9, 3), date(2026, 9, 10), date(2026, 9, 15), date(2026, 9, 30)
    # purchase with a numeric document number, analytic 401.00010 (stored as 401.0001)
    entry(1, d1, "Intrare FURNIZOR TEST SRL", 1427, "628", "401.00010", 1000.00, "Intrari")
    entry(2, d1, "TVA 21 FURNIZOR TEST SRL", 1427, "4426", "401.00010", 210.00, "Intrari")
    total("Total pe", d1, 1210.00)
    # purchase with a series number, two expense lines, no blank rows between them
    entry(3, d2, "Intrare ALT FURNIZOR SRL", "AB0058", "605", "401.00002", 100.00, "Intrari",
          blank_after=False)
    entry(4, d2, "Intrare ALT FURNIZOR SRL", "AB0058", "605", "401.00002", 50.50, "Intrari",
          blank_after=False)
    entry(5, d2, "TVA 11 ALT FURNIZOR SRL", "AB0058", "4426", "401.00002", 16.56, "Intrari")
    # sale to a customer
    entry(6, d2, "Iesire CLIENT TEST SRL", "FX-101", "4111.00001", "704", 150.50, "Iesiri")
    entry(7, d2, "TVA 21 CLIENT TEST SRL", "FX-101", "4111.00001", "4427", 31.61, "Iesiri")
    total("Total pe", d2, 348.67)
    # payment through a 6-decimal bank analytic (5121.090110 stored as 5121.09011)
    entry(8, d3, "Achit. FURNIZOR TEST SRL", 1, "401.00010", "5121.090110", 1210.00, "Banca")
    total("Total pe", d3, 1210.00)
    # compound closing entry: 121 = % (two expense accounts), then % = 121
    entry(9, d4, "Inchidere cheltuieli 2026", None, "121", "%", 1150.50, "Inchidere",
          blank_after=False)
    entry(None, d4, "Inchidere cheltuieli 2026", None, "", "628", 1000.00, "Inchidere",
          blank_after=False)
    entry(None, d4, "Inchidere cheltuieli 2026", None, "", "605", 150.50, "Inchidere",
          blank_after=False)
    entry(10, d4, "Inchidere venituri 2026", None, "%", "121", 150.50, "Inchidere",
          blank_after=False)
    entry(None, d4, "Inchidere venituri 2026", None, "704", "", 150.50, "Inchidere")
    total("Total pe", d4, 1301.00)
    total("Total luna", 9, 4069.67)
    row += 3
    ws.write(row, 0, "Pagina 1/1  SAGA C")
    wb.save(str(HERE / "saga_rj.xls"))


def saga_balanta() -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet"
    ws.cell(1, 1, FIRM)
    ws.cell(3, 3, "Balanta de verificare")
    ws.cell(4, 7, datetime(2026, 1, 1))
    ws.cell(4, 8, "--")
    ws.cell(4, 9, datetime(2026, 9, 30))
    groups = ["Solduri initiale an", "Sume precedente", "Rulaje perioada", "Sume totale",
              "Solduri finale"]
    for i, g in enumerate(groups):
        ws.cell(6, 5 + 2 * i, g)
    ws.cell(7, 1, "Cont")
    ws.cell(7, 2, "Denumirea contului")
    for i in range(5):
        ws.cell(8, 5 + 2 * i, "Debitoare")
        ws.cell(8, 6 + 2 * i, "Creditoare")
    rows = [
        # code, name, SI d/c, prec d/c, rulaj d/c, total d/c, final d/c
        ("1012", "CAPITAL SUBSCRIS VARSAT", 0, 200, 0, 200, 0, 0, 0, 200, 0, 200),
        ("1012", "CAPITAL SUBSCRIS VARSAT - ANALITIC", 0, 200, 0, 200, 0, 0, 0, 200, 0, 200),
        ("401", "FURNIZORI", 0, 0, 0, 0, 1210, 1376.06, 1210, 1376.06, 0, 166.06),
        ("401.00002", "ALT FURNIZOR SRL", 0, 0, 0, 0, 0, 166.06, 0, 166.06, 0, 166.06),
        ("401.00010", "FURNIZOR TEST SRL", 0, 0, 0, 0, 1210, 1210, 1210, 1210, 0, 0),
        ("4111", "CLIENTI", 0, 0, 0, 0, 182.11, 0, 182.11, 0, 182.11, 0),
        ("4111.00001", "CLIENT TEST SRL", 0, 0, 0, 0, 182.11, 0, 182.11, 0, 182.11, 0),
        ("5121", "CONTURI LA BANCI IN LEI", 5000, 0, 5000, 0, 0, 1210, 5000, 1210, 3790, 0),
        ("5121.090110", "BANCA TEST LEI", 5000, 0, 5000, 0, 0, 1210, 5000, 1210, 3790, 0),
    ]
    r = 9
    for code, name, *vals in rows:
        c = ws.cell(r, 1)
        if "." in code:
            frac = code.split(".")[1]
            c.value = float(code)
            c.number_format = "########0." + "0" * len(frac)
        else:
            c.value = int(code)
            c.number_format = "########0"
        ws.cell(r, 2, name)
        for i, v in enumerate(vals):
            ws.cell(r, 5 + i, v).number_format = "###,###,##0.00"
        r += 1
    ws.cell(r + 3, 1, "Pagina 1/1")
    wb.save(HERE / "saga_balanta.xlsx")


def nextup_rj() -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet"
    ws.append(["Nr. crt", "Jurnal", "Nr. document", "Data", "Partener", "Explicatii",
               "Cont debitor", "Cont auxiliar debitor", "Cont creditor",
               "Cont auxiliar creditor", "Suma", "Nr. inregistrare"])
    rows = [
        (1, "JC", "AB0058", date(2026, 9, 10), "ALT FURNIZOR SRL", "Factura AB0058",
         "605", None, "401_ALTFURNIZOR", None, 150.5, 371),
        (2, "JC", "AB0058", date(2026, 9, 10), "ALT FURNIZOR SRL", "Factura AB0058",
         "4426", None, "401_ALTFURNIZOR", None, 16.56, 371),
        (3, "JV", "FX-101", date(2026, 9, 10), "CLIENT TEST SRL", "Factura FX-101",
         "4111_CLIENTTEST", None, "704", None, 150.5, 372),
        (4, "JV", "FX-101", date(2026, 9, 10), "CLIENT TEST SRL", "Factura FX-101",
         "4111_CLIENTTEST", None, "4427", None, 31.61, 372),
        (5, "JV", "FX-90", date(2026, 9, 12), "CLIENT TEST SRL", "Storno FX-90",
         "4111_CLIENTTEST", None, "704", None, -20.0, 373),
        (6, "JB", "EXT24", date(2026, 9, 15), None, "COMISION", "627", None, "5121", None,
         2.75, 64),
        (7, "OD", "611", date(2026, 9, 30), None, None, "1171", None, "121", None, 92.07, 612),
    ]
    for r in rows:
        ws.append([*r[:3], datetime.combine(r[3], datetime.min.time()), *r[4:]])
    ws.append([None] * 10 + [sum(r[10] for r in rows), None])
    wb.save(HERE / "nextup_rj.xlsx")


def nextup_balanta() -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet"
    ws.append(["Cont", "Titlu cont", "Cod partener", "Denumire partener", "CIF partener",
               "TVA la incasare", "Rulaj precedent", None, "Rulaj curent", None, "Total", None,
               "Sold final", None])
    ws.append([None] * 6 + ["Debit", "Credit"] * 4)
    rows = [
        ("401", "Furnizori", None, None, None, None, 0, 0, 0, 167.06, 0, 167.06, 0, 167.06),
        ("401_ALTFURNIZOR", "ALT FURNIZOR SRL", "10001", "ALT FURNIZOR SRL", "RO20000005",
         "Nu", 0, 0, 0, 167.06, 0, 167.06, 0, 167.06),
        ("4111", "Clienti", None, None, None, None, 0, 0, 162.11, 0, 162.11, 0, 162.11, 0),
        ("4111_CLIENTTEST", "CLIENT TEST SRL", "10002", "CLIENT TEST SRL", "30000002", "Nu",
         0, 0, 162.11, 0, 162.11, 0, 162.11, 0),
        ("401XVENDOR", "FOREIGN VENDOR LTD", "10003", "FOREIGN VENDOR LTD", "GB123456789",
         "Nu", 0, 0, 0, 0, 0, 0, 0, 0),
    ]
    for r in rows:
        ws.append(list(r))
    ws.append([None] * 6 + [0, 0, 162.11, 167.06, 162.11, 167.06, 162.11, 167.06])
    wb.save(HERE / "nextup_balanta.xlsx")


def spv_register() -> None:
    """SPV invoice register (harvest C-F12): one row per invoice and VAT rate."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Facturi SPV"
    ws.append(["Registru facturi SPV"])
    ws.append([])
    ws.append(["Companie", "Trimestru", "Data facturii", "Numar factura", "Numele furnizorului",
               "Suma net per % de TVA", "Cota TVA", "TVA", "Gross", "Status", "Obs re status",
               "Ordine"])
    rows = [
        # posted, and in the SAGA journal fixture (number stored as a number)
        (date(2026, 9, 3), 1427, "FURNIZOR TEST SRL", 1000.00, 0.21, 210.00, 1210.00,
         "Înregistrat în SAGA", None, 1),
        # still to post; the SAGA journal already has it as AB0058
        (date(2026, 9, 10), "AB 0058", "ALT FURNIZOR SRL", 150.50, 0.11, 16.56, 167.06,
         "De înregistrat", "lipsa NIR", 2),
        # posted per the register, two VAT rates, not in the journal fixture
        (date(2026, 9, 12), "F 77", "AL TREILEA SRL", 100.00, 0.21, 21.00, 121.00,
         "Inregistrat in SAGA", None, 3),
        (date(2026, 9, 12), "F 77", "AL TREILEA SRL", 50.00, 0.11, 5.50, 55.50,
         "Inregistrat in SAGA", None, 3),
    ]
    for d, number, supplier, net, rate, vat, gross, status, obs, order in rows:
        ws.append(["FIRMA TEST SRL", "T3 2026", datetime.combine(d, datetime.min.time()), number,
                   supplier, net, rate, vat, gross, status, obs, order])
        r = ws.max_row
        ws.cell(r, 7).number_format = "0%"
        for c in (6, 8, 9):
            ws.cell(r, c).number_format = "#,##0.00"
    wb.save(HERE / "spv_register.xlsx")


if __name__ == "__main__":
    saga_rj()
    saga_balanta()
    nextup_rj()
    nextup_balanta()
    spv_register()
    print("written:", sorted(p.name for p in HERE.iterdir() if p.suffix in (".xls", ".xlsx")))
