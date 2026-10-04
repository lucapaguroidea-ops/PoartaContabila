"""The loop kit: one SAGA C loop on synthetic data, prepared and read back (BUILD.md B3, B6).

A loop (``loops/loop-NN/loop.yaml``) names its slice, the surface rows it means to prove, its
exit criteria and its runs (a synthetic firm and its months). The kit runs the same pipeline
as the scenario runner (:mod:`poarta_contabila.scenarios`), on a fresh in-memory runtime per
run, with two differences:

``prepare``
    stops where SAGA starts. Per SAGA test firm it writes, under ``prepared/<cui>-<firm>/``:
    the import folders our packages produce (``import/run-NN/``, SAGA's own file names, one
    folder per import), the keying list of what has no mouth (``keying.csv``: the opening
    balances and every journal line no package brings), the exports the generator expects
    SAGA to show (``simulated/``: never imported, they are the baseline the comparisons use),
    and the firm's settings (``firm.md``). ``prepared/STEPS.md`` is the owner's list.

``read``
    takes SAGA's real exports (``exports/<cui>-<firm>/``: ``rj.*``, ``balanta-<p>.*``,
    ``cumparari-<p>.*``, ``vanzari-<p>.*``) as the eye: the agent's imports are taken as done,
    its snapshot is read from the real export, and each month is reconciled and closed
    against the real balance and journals. It writes ``read/REPORT.md`` and
    ``read/<cui>-<firm>.evidence.draft.yaml``, with three comparisons:

    1. **meaning** — generator ↔ SAGA: did SAGA book each document as the generator meant
       (accounts at the synthetic level, amounts)? A difference is semantic.
    2. **reader** — SAGA export ↔ our reader: the files read without error, are of this
       firm, and agree with each other (journal turnover = balance turnover per account;
       the VAT journals hold the journal's invoices). A difference is mechanical.
    3. **model** — our simulated book ↔ SAGA: journal types, documents, analytics, closing
       balances. A difference is the generator's to fix.

    and the proposed gap list (what the run landed on that the catalog does not foresee, the
    documents that never reached ``acked``, every difference with its class), the evidence
    ledger of each month, and an evidence draft: the target rows the run drove, proposed
    **saga** only when nothing differs. The owner approves a draft by filling ``saga_build``
    and ``approved`` and moving it to ``surface/evidence/`` (BUILD.md B3, steps 8–10).

PRE checks run against the generator's books before the import (the test firm holds only
what was keyed); everything after the import reads SAGA's export. A simulated SAGA agent is
never SAGA proof (AGENTS): only ``read`` on the owner's real exports is.

    uv run python -m poarta_contabila.loops prepare N [--out DIR]
    uv run python -m poarta_contabila.loops read N [--exports DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from poarta_contabila.catalog import load_catalog
from poarta_contabila.coverage import findings as coverage_findings
from poarta_contabila.scenarios import (
    TAKEN_AT,
    Answers,
    Expect,
    Runner,
    Scenario,
    actual_expect,
    local_clients,
    names,
)
from poarta_contabila.synthetic.books import Book
from poarta_contabila.types import Closed, Period

ROOT = Path(__file__).resolve().parents[1]
LOOPS_DIR = ROOT / "loops"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TERMINAL = ("acked", "already_in_sink", "rejected")


class LoopError(ValueError):
    """A loop's definition or its files do not hold together."""


# ----- the loop file -----


class LoopRun(Closed):
    firm: str  # a synthetic firm (poarta_contabila/synthetic/firms.py)
    period: Period
    months: list[Period] | None = None  # realistic: consecutive months
    generator: Literal["standard", "realistic"] = "standard"
    seed: int = 0
    answers: Answers = Field(default_factory=Answers)


class LoopDef(Closed):
    loop: int
    slice: str
    note: str = ""
    status: Literal["proposed", "approved"]  # the owner approves the slice (B3, step 1)
    target_rows: list[str]  # "table:key", as the coverage map names them
    exit: list[str]  # the exit criteria, fixed before the loop starts (B4, rule 1)
    runs: list[LoopRun]


def loop_dir(n: int, root: Path = LOOPS_DIR) -> Path:
    return root / f"loop-{n:02d}"


def load_loop(n: int, root: Path = LOOPS_DIR) -> LoopDef:
    path = loop_dir(n, root) / "loop.yaml"
    ld = LoopDef.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if ld.loop != n:
        raise LoopError(f"{path}: loop {ld.loop}, not {n}")
    if not ld.runs or not ld.exit or not ld.target_rows:
        raise LoopError(f"{path}: a loop needs runs, exit criteria and target rows")
    keys = [r.firm for r in ld.runs]
    if len(keys) != len(set(keys)):
        raise LoopError(f"{path}: one run per firm (one SAGA test firm each)")
    return ld


def scenario(ld: LoopDef, run: LoopRun) -> Scenario:
    return Scenario(
        name=f"loop-{ld.loop:02d}-{run.firm}",
        firm=run.firm,
        period=run.period,
        months=run.months,
        generator=run.generator,
        seed=run.seed,
        books="agent",
        report_pack=True,
        answers=run.answers,
    )


def _cents(money: str | Decimal) -> int:
    return int((Decimal(money) * 100).to_integral_value())


def _ron(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    return f"{sign}{abs(cents) // 100}.{abs(cents) % 100:02d}"


def _num(number: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (number or "").upper())


# ----- the run -----


@dataclass
class ReadFiles:
    """One SAGA test firm's real exports, read (or the errors reading them)."""

    rj: list = field(default_factory=list)
    balance: dict[str, list] = field(default_factory=dict)  # period → rows
    journals: dict[str, dict[str, list]] = field(default_factory=dict)  # side → period → docs
    paths: dict[str, Path] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    cuis: dict[str, str | None] = field(default_factory=dict)  # file → the firm it names


class LoopRunner(Runner):
    """A loop run: the scenario runner up to SAGA, then files to and from a SAGA test firm."""

    def __init__(self, client: Any, agent: Any, sc: Scenario) -> None:
        super().__init__(client, agent, sc)
        self.folder_name = f"{self.f.cui}-{self.f.key}"

    def before_import(self) -> Book:
        self.setup()
        before = self.m.book.without(self.our_refs())
        self.books(before, "before (the generator's books less our documents)")
        self.upload_all()
        self.answer_jobs()
        for p in self.periods:
            self.reconcile(p)
        self.answer_jobs()
        return before

    def pull_all(self) -> list[tuple[int, str, bytes]]:
        """Every package, as the agent pulls them: one import folder per run."""
        out: list[tuple[int, str, bytes]] = []
        for run in range(1, 51):
            pulled = self.agent.get("/agent/pull").json()
            batches = pulled.get("batches") or []
            if not batches:
                break
            for batch in batches:
                label = None
                if batch["backup"] != "none":
                    label = f"{batch['cui']}:{batch['folder']}:20261001T{run:02d}0000Z"
                    self.agent.post(
                        "/agent/ack-backup",
                        json={"label": label, "cui": batch["cui"], "folder": batch["folder"]},
                    )
                for item in batch["items"]:
                    out.append((run, item["filename"], base64.b64decode(item["content_b64"])))
                self.agent.post(
                    "/agent/imported",
                    json={
                        "cui": batch["cui"],
                        "folder": batch["folder"],
                        "backup_label": label,
                        "results": [
                            {"export_key": i["export_key"], "ok": True} for i in batch["items"]
                        ],
                    },
                )
        return out

    # -- prepare --

    def prepare(self, out: Path) -> dict[str, Any]:
        before = self.before_import()
        files = self.pull_all()
        base = out / self.folder_name
        for run, name, data in files:
            path = base / "import" / f"run-{run:02d}" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        keyed = keying_rows(self.f, before)
        (base / "keying.csv").write_text(keying_csv(keyed), encoding="utf-8")
        for name, data in simulated_exports(self.m.book, self.periods).items():
            (base / "simulated").mkdir(parents=True, exist_ok=True)
            (base / "simulated" / name).write_bytes(data)
        (base / "firm.md").write_text(firm_md(self.f, self.periods), encoding="utf-8")
        for d in self.r.docs.values():
            self._view(d)
        waiting = {
            ref: d.job.get("status")
            for ref, d in self.r.docs.items()
            if d.job.get("status") not in ("wait_validare", *TERMINAL)
        }
        return {
            "firm": self.folder_name,
            "runs": sorted({r for r, _, _ in files}),
            "files": len(files),
            "keyed": len(keyed),
            "not_packaged": waiting,
            "steps": list(self.r.steps),
        }

    # -- read --

    def read(self, exports: Path, prepared: Path | None = None) -> RunReport:
        self.before_import()
        files = self.pull_all()
        report = RunReport(self.folder_name, self.f.cui, list(self.periods))
        if prepared is not None:
            report.package = package_diff(files, prepared / self.folder_name / "import")
        real = read_exports(exports / self.folder_name, self.periods, self.f.cui)
        report.reader = list(real.errors)
        if real.errors:
            report.steps = list(self.r.steps)
            return report
        self._upload_real(real)
        for p in self.periods:
            for kind in ("balanta", "jurnal_cumparari", "jurnal_vanzari"):
                path = real.paths.get(f"{kind}:{p}")
                if path is not None:
                    self._upload(kind, path, [p])
            self.reconcile(p)
            self.close(p)
            self.filings(p)
        for d in self.r.docs.values():
            self._view(d)
        report.steps = list(self.r.steps)
        report.meaning = meaning_diff(self.m.book, real.rj, self.periods)
        report.reader += reader_check(real, self.periods)
        sim = read_simulated(self.m.book, self.periods, self.f.cui)
        report.model = model_diff(sim, real, self.periods, self.f.cui)
        report.docs = {ref: d.actual() for ref, d in self.r.docs.items()}
        report.months = {p: ms.actual() for p, ms in self.r.months.items()}
        report.findings = [
            f"{f.kind}: {f.subject}: {f.detail}"
            for f in coverage_findings(load_catalog(), [self.r.outcome()])
        ]
        report.driven = sorted(f"{t}:{k}" for t, k in self.driven())
        report.ledgers = {p: self.c.get(f"/evidence/{self.f.cui}/{p}").json() for p in self.periods}
        report.exports = sorted(str(p) for p in real.paths.values())
        return report

    def _upload(self, kind: str, path: Path, periods: list[str]) -> None:
        resp = self.c.post(
            f"/tenants/{self.f.cui}/exports/{kind}",
            params={"filename": path.name, "periods": ",".join(periods), "product": "saga"},
            content=path.read_bytes(),
            headers={"Content-Type": "application/octet-stream"},
        )
        body = self._ok(resp, f"SAGA export {kind} {path.name}")
        if kind == "rj" and resp.status_code < 400:
            self.rj_export = body.get("export_id")

    def _upload_real(self, real: ReadFiles) -> None:
        """SAGA's journal register becomes the eye; the agent's snapshot is read from it."""
        from poarta_contabila.sinks.exports import ExportEye

        self._upload("rj", real.paths["rj"], self.periods)
        last = real.balance.get(self.periods[-1], [])
        eye = ExportEye(product="saga", lines=real.rj, balance=last, cui=self.f.cui)
        docs = [
            {
                "saga_doc_key": d.saga_key,
                "doc_class": d.doc_class,
                "number": d.number,
                "date": d.date,
                "gross": d.gross,
                "validated": True,  # the owner validated every import (B3, step 4)
                "net": d.net,
                "vat": d.vat,
                "partner_cui": d.partner_cui,
            }
            for p in self.periods
            for d in eye.documents(self.f.cui, p)
        ]
        snap = {
            "cui": self.f.cui,
            "folder": self.f.folder,
            "taken_at": TAKEN_AT,
            "closed_periods": [],
            "documents": docs,
        }
        result = self.agent.post("/agent/snapshot", json=snap).json()
        self.step(
            f"SAGA export read: {len(real.rj)} journal lines, {len(docs)} documents; snapshot "
            f"acked {len(result.get('acked', []))}, unmatched {len(result.get('unmatched', []))}"
        )
        for d in self.r.docs.values():
            self._view(d)

    def driven(self) -> set[tuple[str, str]]:
        """The catalog rows this run went through, as the coverage map names them."""
        actual = Expect.model_validate(actual_expect(self.r)["expect"])
        return names(self.sc.model_copy(update={"expect": actual}))


@dataclass
class RunReport:
    firm: str
    cui: str
    periods: list[str]
    steps: list[str] = field(default_factory=list)
    package: list[str] = field(default_factory=list)
    meaning: list[str] = field(default_factory=list)
    reader: list[str] = field(default_factory=list)
    model: list[str] = field(default_factory=list)
    docs: dict[str, dict[str, Any]] = field(default_factory=dict)
    months: dict[str, dict[str, Any]] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    driven: list[str] = field(default_factory=list)
    ledgers: dict[str, dict[str, Any]] = field(default_factory=dict)
    exports: list[str] = field(default_factory=list)

    @property
    def not_acked(self) -> dict[str, str]:
        return {
            ref: f"{a.get('status')}" + (f" ({a['error']})" if a.get("error") else "")
            for ref, a in self.docs.items()
            if a.get("status") not in TERMINAL and not a.get("refused")
        }

    @property
    def clean(self) -> bool:
        return (
            not (self.package or self.meaning or self.reader or self.model or self.findings)
            and not self.not_acked
        )

    def gaps(self) -> list[tuple[str, str]]:
        """The proposed gap list: (class, item)."""
        out = [("mechanical", f"package: {x}") for x in self.package]
        out += [("semantic", f"meaning: {x}") for x in self.meaning]
        out += [("mechanical", f"reader: {x}") for x in self.reader]
        out += [("mechanical", f"model: {x}") for x in self.model]
        out += [("unforeseen", x) for x in self.findings]
        out += [("not acked", f"{ref}: {why}") for ref, why in self.not_acked.items()]
        return out


# ----- files to SAGA -----


KEYING_HEADER = [
    "period",
    "day",
    "journal",
    "number",
    "explanation",
    "debit",
    "credit",
    "amount",
    "partner",
    "partner_cui",
]


def keying_rows(firm: Any, before: Book) -> list[list[str]]:
    """What the owner keys by hand: opening balances, then every line no package brings."""
    rows: list[list[str]] = []
    first = before.periods()[0] if before.periods() else ""
    opening = {**firm.opening, **before.opening_extra}
    for account, cents in sorted(opening.items()):
        debit, credit = (account, "") if cents > 0 else ("", account)
        rows.append(
            [first, "", "sold inițial", "", "sold inițial", debit, credit, _ron(abs(cents)), "", ""]
        )
    for e in before.lines():
        p = e.partner
        rows.append(
            [
                e.day[:7],
                e.day,
                e.tip,
                e.number or "",
                e.expl,
                e.debit,
                e.credit,
                _ron(e.amount),
                p.name if p else "",
                (p.cui or p.vat_id or "") if p else "",
            ]
        )
    return rows


def keying_csv(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(KEYING_HEADER)
    w.writerows(rows)
    return buf.getvalue()


def simulated_exports(book: Book, periods: list[str]) -> dict[str, bytes]:
    """The exports the generator expects SAGA to show, in the names the owner sends back."""
    out = {"rj.xls": book.saga_rj(periods)}
    for p in periods:
        out[f"balanta-{p}.xlsx"] = book.saga_balanta(p)
        out[f"cumparari-{p}.xls"] = book.tva_journal(p, "cumparari")
        out[f"vanzari-{p}.xls"] = book.tva_journal(p, "vanzari")
    return out


def firm_md(firm: Any, periods: list[str]) -> str:
    regime = (
        "neplătitor de TVA"
        if not firm.vat_payer
        else "plătitor de TVA, lunar, "
        + ("TVA la încasare" if firm.la_incasare else "TVA la plată")
    )
    lines = [
        f"# {firm.name}",
        "",
        "Invented firm (synthetic data): set it up once as a SAGA C test firm.",
        "",
        "| Setting | Value |",
        "|---|---|",
        f"| Denumire | {firm.name} |",
        f"| Cod fiscal | `{firm.cui}` (no `RO`) |",
        f"| Regim | {regime} |",
        f"| Start month | {periods[0]} (Preluare date: firmă fără activitate) |",
        f"| Bank | analytic `{firm.bank_account}`, IBAN `{firm.iban}` (invented) |",
        f"| Folder in SAGA | `{firm.folder}` |",
        "",
        "Partners are not added by hand: the invoice imports create them (copy-firm test §4 tells",
        "how). The opening balances are the `sold inițial` rows of `keying.csv`.",
    ]
    return "\n".join(lines) + "\n"


def steps_md(ld: LoopDef, prepared: list[dict[str, Any]]) -> str:
    firms = "\n".join(
        f"- `{p['firm']}/`: {p['files']} files in {len(p['runs'])} import folder(s), "
        f"{p['keyed']} lines to key"
        + (
            f"; not packaged (a question or a hold): {p['not_packaged']}"
            if p["not_packaged"]
            else ""
        )
        for p in prepared
    )
    exit_ = "\n".join(f"- {x}" for x in ld.exit)
    return f"""# Loop {ld.loop} — {ld.slice}

{ld.note}

Invented data only. One SAGA C test firm per folder below; never a client's firm.

{firms}

## Exit criteria (fixed before the loop)

{exit_}

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

Then `uv run python -m poarta_contabila.loops read {ld.loop}` writes the comparisons, the gap
list and an evidence draft for your review.
"""


# ----- files from SAGA -----


def _one(folder: Path, stem: str) -> Path | None:
    found = sorted(p for p in folder.glob(f"{stem}.*") if p.suffix.lower() in (".xls", ".xlsx"))
    return found[0] if found else None


def read_exports(folder: Path, periods: list[str], cui: str) -> ReadFiles:
    """SAGA's real exports of one test firm, read with the same readers the eye uses."""
    from poarta_contabila.sinks.exports import (
        ExportError,
        read_firm_cui,
        read_saga_balanta,
        read_saga_rj,
    )
    from poarta_contabila.sinks.saga_eye import read_saga_tva_journal

    out = ReadFiles()
    wanted = [("rj", "rj", None)]
    for p in periods:
        wanted += [
            (f"balanta:{p}", f"balanta-{p}", p),
            (f"jurnal_cumparari:{p}", f"cumparari-{p}", p),
            (f"jurnal_vanzari:{p}", f"vanzari-{p}", p),
        ]
    for key, stem, p in wanted:
        path = _one(folder, stem)
        if path is None:
            out.errors.append(f"{folder.name}/{stem}.xls(x): missing")
            continue
        out.paths[key] = path
        try:
            if key == "rj":
                out.rj = read_saga_rj(path)
            elif key.startswith("balanta"):
                out.balance[p] = read_saga_balanta(path)
            else:
                side = "cumparari" if "cumparari" in key else "vanzari"
                out.journals.setdefault(side, {})[p] = read_saga_tva_journal(path, side)
            out.cuis[path.name] = read_firm_cui(path)
        except (ExportError, ValueError, KeyError) as exc:
            out.errors.append(f"{path.name}: {exc}")
    for name, found in out.cuis.items():
        if found is not None and found != cui:
            out.errors.append(f"{name}: an export of firm {found}, not {cui}")
    return out


def read_simulated(book: Book, periods: list[str], cui: str) -> ReadFiles:
    with tempfile.TemporaryDirectory() as tmp:
        for name, data in simulated_exports(book, periods).items():
            (Path(tmp) / name).write_bytes(data)
        return read_exports(Path(tmp), periods, cui)


# ----- the three comparisons -----


def _postings(rows: list[tuple[str, str | None, str, str, int]]) -> dict[tuple[str, str], Counter]:
    from poarta_contabila.sinks.exports import synthetic

    out: dict[tuple[str, str], Counter] = {}
    for period, number, debit, credit, cents in rows:
        out.setdefault((period, _num(number)), Counter())[
            (synthetic(debit) if debit else "", synthetic(credit) if credit else "", cents)
        ] += 1
    return out


def _show(c: Counter) -> str:
    return ", ".join(
        f"{d or '—'}={k or '—'} {_ron(cents)}" + (f" ×{n}" if n > 1 else "")
        for (d, k, cents), n in sorted(c.items())
    )


def meaning_diff(book: Book, rj: list, periods: list[str]) -> list[str]:
    """Generator ↔ SAGA, per document: the postings at the synthetic level, and amounts."""
    gen = _postings(
        [(e.day[:7], e.number, e.debit, e.credit, e.amount) for e in book.lines(periods)]
    )
    real = _postings(
        [
            (ln.date[:7], ln.doc_number, ln.debit, ln.credit, _cents(ln.amount))
            for ln in rj
            if ln.date[:7] in periods
        ]
    )
    out = []
    for key in sorted(set(gen) | set(real)):
        period, number = key
        label = f"{period} {number or '(no number)'}"
        g, r = gen.get(key, Counter()), real.get(key, Counter())
        if g == r:
            continue
        if not r:
            out.append(f"{label}: the generator posts {_show(g)}; SAGA holds nothing")
        elif not g:
            out.append(f"{label}: SAGA holds {_show(r)}; the generator posts nothing")
        else:
            out.append(f"{label}: the generator posts {_show(g - r)}; SAGA {_show(r - g)} instead")
    return out


def reader_check(real: ReadFiles, periods: list[str]) -> list[str]:
    """The real exports agree with each other, as our readers read them."""
    from poarta_contabila.sinks.exports import ExportEye

    out = []
    for p in periods:
        balance = real.balance.get(p, [])
        eye = ExportEye(product="saga", lines=real.rj, balance=balance)
        from_rj = eye.turnover("", p)
        from_bal: dict[str, list[int]] = {}
        for row in balance:
            if row.account.isdigit():
                pair = from_bal.setdefault(row.account, [0, 0])
                pair[0] += _cents(row.turnover_debit)
                pair[1] += _cents(row.turnover_credit)
        for account in sorted(set(from_rj) | set(from_bal)):
            rj = from_rj.get(account, {"debit": "0", "credit": "0"})
            a, b = (_cents(rj["debit"]), _cents(rj["credit"])), tuple(from_bal.get(account, (0, 0)))
            if a != b:
                out.append(
                    f"{p} {account}: journal turnover {_ron(a[0])} / {_ron(a[1])}, "
                    f"balance turnover {_ron(b[0])} / {_ron(b[1])}"
                )
        rj_docs = {
            cls: {_num(ln.doc_number) for ln in real.rj if ln.date[:7] == p and ln.journal == jr}
            for cls, jr in (("cumparari", "Intrari"), ("vanzari", "Iesiri"))
        }
        for side, numbers in rj_docs.items():
            read = {_num(d.number) for d in real.journals.get(side, {}).get(p, [])}
            if numbers - read:
                out.append(
                    f"{p} jurnal de {side}: misses {sorted(numbers - read)} the journal holds"
                )
            if read - numbers:
                out.append(
                    f"{p} jurnal de {side}: holds {sorted(read - numbers)} the journal does not"
                )
    return out


def model_diff(sim: ReadFiles, real: ReadFiles, periods: list[str], cui: str) -> list[str]:
    """Our simulated book ↔ SAGA: what the generator's model of SAGA got wrong."""
    from poarta_contabila.sinks.exports import ExportEye, synthetic

    out = []
    tips_s, tips_r = {ln.journal for ln in sim.rj}, {ln.journal for ln in real.rj}
    if tips_s != tips_r:
        out.append(f"journal types: simulated {sorted(tips_s)}, SAGA {sorted(tips_r)}")
    for p in periods:
        es = ExportEye(product="saga", lines=sim.rj, balance=sim.balance.get(p, []), cui=cui)
        er = ExportEye(product="saga", lines=real.rj, balance=real.balance.get(p, []), cui=cui)
        ds = {(d.doc_class, _num(d.number), d.date, d.gross) for d in es.documents(cui, p)}
        dr = {(d.doc_class, _num(d.number), d.date, d.gross) for d in er.documents(cui, p)}
        for d in sorted(ds - dr):
            out.append(f"{p} document {d}: simulated, not in SAGA")
        for d in sorted(dr - ds):
            out.append(f"{p} document {d}: in SAGA, not simulated")
        for root in ("401", "4111"):
            a_s = {
                r.account
                for r in sim.balance.get(p, [])
                if synthetic(r.account) == root and r.account != root
            }
            a_r = {
                r.account
                for r in real.balance.get(p, [])
                if synthetic(r.account) == root and r.account != root
            }
            if a_s != a_r:
                out.append(f"{p} analytics of {root}: simulated {sorted(a_s)}, SAGA {sorted(a_r)}")
        close_s = {
            r.account: (_cents(r.closing_debit), _cents(r.closing_credit))
            for r in sim.balance.get(p, [])
            if r.account.isdigit()
        }
        close_r = {
            r.account: (_cents(r.closing_debit), _cents(r.closing_credit))
            for r in real.balance.get(p, [])
            if r.account.isdigit()
        }
        for account in sorted(set(close_s) | set(close_r)):
            s, r = close_s.get(account, (0, 0)), close_r.get(account, (0, 0))
            if s != r:
                out.append(
                    f"{p} {account} closing: simulated {_ron(s[0])} / {_ron(s[1])}, "
                    f"SAGA {_ron(r[0])} / {_ron(r[1])}"
                )
    return out


def package_diff(files: list[tuple[int, str, bytes]], imported: Path) -> list[str]:
    """The packages regenerated now ↔ the ones the owner imported (job ids masked)."""
    if not imported.is_dir():
        return [f"{imported} is missing: the prepared folders are not in the repo"]
    now = {
        (f"run-{r:02d}", n): UUID_RE.sub("<id>", d.decode("utf-8", "replace")) for r, n, d in files
    }
    then = {
        (p.parent.name, p.name): UUID_RE.sub(
            "<id>", p.read_text(encoding="utf-8", errors="replace")
        )
        for p in imported.glob("run-*/*")
    }
    out = [f"{k[0]}/{k[1]}: prepared, not generated now" for k in sorted(set(then) - set(now))]
    out += [f"{k[0]}/{k[1]}: generated now, not prepared" for k in sorted(set(now) - set(then))]
    out += [
        f"{k[0]}/{k[1]}: differs from what was imported"
        for k in sorted(set(now) & set(then))
        if now[k] != then[k]
    ]
    return out


# ----- the loop -----


def prepare(n: int, out: Path | None = None, root: Path = LOOPS_DIR) -> Path:
    ld = load_loop(n, root)
    if ld.status != "approved":
        raise LoopError(f"loop {n} is {ld.status}: the owner approves the slice first (B3, step 1)")
    out = out or loop_dir(n, root) / "prepared"
    done = []
    for run in ld.runs:
        client, agent = local_clients()
        done.append(LoopRunner(client, agent, scenario(ld, run)).prepare(out))
    (out / "STEPS.md").write_text(steps_md(ld, done), encoding="utf-8")
    return out


def read(
    n: int, exports: Path | None = None, out: Path | None = None, root: Path = LOOPS_DIR
) -> tuple[Path, list[RunReport]]:
    ld = load_loop(n, root)
    base = loop_dir(n, root)
    exports = exports or base / "exports"
    out = out or base / "read"
    out.mkdir(parents=True, exist_ok=True)
    reports = []
    for run in ld.runs:
        client, agent = local_clients()
        reports.append(
            LoopRunner(client, agent, scenario(ld, run)).read(exports, prepared=base / "prepared")
        )
    for r in reports:
        (out / f"{r.firm}.evidence.draft.yaml").write_text(evidence_draft(ld, r), encoding="utf-8")
    (out / "REPORT.md").write_text(report_md(ld, reports), encoding="utf-8")
    return out, reports


def _rel(path: str) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return path


def evidence_draft(ld: LoopDef, r: RunReport) -> str:
    driven = set(r.driven)
    target = set(ld.target_rows)
    proposed = sorted(target & driven) if r.clean else []
    data = {
        "loop": ld.loop,
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "firm_cui": r.cui,
        "saga_build": "FILL IN: SAGA C version (Help → Despre)",
        "approved": "PENDING: write 'owner, YYYY-MM-DD' to approve",
        "rows": proposed,
        "exports": [_rel(p) for p in r.exports],
    }
    why = (
        "every comparison is empty and every document reached a final state"
        if r.clean
        else f"not proposed: {len(r.gaps())} gap(s) in REPORT.md"
    )
    head = (
        f"# Loop {ld.loop} evidence draft for {r.firm}: {why}.\n"
        f"# To approve: fill saga_build and approved, then move this file to surface/evidence/.\n"
        f"# Target rows not driven by this run: {sorted(target - driven)}\n"
        f"# Driven rows not targeted: {sorted(driven - target)}\n"
    )
    return head + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=100)


def report_md(ld: LoopDef, reports: list[RunReport]) -> str:
    from poarta_contabila.evidence import render as render_ledger

    lines = [f"# Loop {ld.loop} — {ld.slice}: what SAGA showed", ""]
    lines += ["Exit criteria:", ""] + [f"- {x}" for x in ld.exit] + [""]
    for r in reports:
        lines += [f"## {r.firm} ({', '.join(r.periods)})", ""]
        lines.append("**Clean**: nothing differs." if r.clean else f"**{len(r.gaps())} gap(s).**")
        lines.append("")
        for title, items in (
            ("Packages: prepared ↔ generated now", r.package),
            ("1. Meaning: generator ↔ SAGA (semantic)", r.meaning),
            ("2. Reader: SAGA export ↔ our reader (mechanical)", r.reader),
            ("3. Model: simulated book ↔ SAGA (the generator's)", r.model),
            ("Unforeseen by the catalog", r.findings),
            ("Not at a final state", [f"{k}: {v}" for k, v in r.not_acked.items()]),
        ):
            lines += [f"### {title}", ""]
            lines += [f"- {x}" for x in items] if items else ["- none"]
            lines.append("")
        lines += ["### Documents", "", "| Ref | Articol | Status | Asked |", "|---|---|---|---|"]
        for ref, a in r.docs.items():
            status = a.get("status") or a.get("refused")
            asked = ", ".join(a.get("asks") or [])
            lines.append(f"| {ref} | {a.get('articol') or '-'} | {status} | {asked} |")
        lines += ["", "### Months", ""]
        for p, m in r.months.items():
            lines.append(
                f"- {p}: close {m.get('close')}, material {m.get('material')},"
                f" v2 {m.get('v2')}, blockers {m.get('blockers')}"
            )
        lines += ["", "### Evidence ledger", ""]
        for _p, led in r.ledgers.items():
            lines += ["```", render_ledger(led), "```", ""]
        lines += ["### Steps", ""] + [f"- {s}" for s in r.steps] + [""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="poarta_contabila.loops", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare", help="write a loop's files for SAGA")
    p.add_argument("loop", type=int)
    p.add_argument("--out", type=Path)
    p.add_argument("--root", type=Path, default=LOOPS_DIR, help=argparse.SUPPRESS)
    r = sub.add_parser("read", help="read SAGA's exports back: comparisons, gaps, evidence draft")
    r.add_argument("loop", type=int)
    r.add_argument("--exports", type=Path)
    r.add_argument("--out", type=Path)
    r.add_argument("--root", type=Path, default=LOOPS_DIR, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "prepare":
            print(f"prepared: {prepare(args.loop, args.out, args.root)}")
        else:
            out, reports = read(args.loop, args.exports, args.out, args.root)
            for rep in reports:
                print(f"{rep.firm}: {'clean' if rep.clean else f'{len(rep.gaps())} gap(s)'}")
            print(f"report: {out / 'REPORT.md'}")
    except LoopError as exc:
        print(exc)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
