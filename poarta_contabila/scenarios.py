"""Scenario runner (WP-71): synthetic months driven over HTTP, expected path against actual.

A scenario is YAML in ``fixtures/scenarios/``: a firm (:mod:`poarta_contabila.synthetic`), a
month, a seed and at most one named defect; how the books stand when documents arrive; the
answers a person gives (scripted per question kind); and what must happen — per document
its source doc, job kind, articol de cale, the questions it asks in order, its final status,
its SAGA mouth and its recon profiles; per month the close kind, ``material``, the blockers
(by control id or their own head), the control outcomes and the filings due.

The run drives the operator API like the smoke run (an in-memory runtime by default):

1. the tenant, its CO.DiT for each month, any explained rules;
2. the books as SAGA holds them before our packages (``books: agent``), or already holding
   every document (``in_books``), or none (``none``);
3. the uploads in order (SPV zips, statements, expense reports and their split), then the
   person's answers (``v3_approve``: approve invoices; bind a bank line to the partner and
   invoice it settles);
4. a **simulated SAGA agent** (labelled so in every report): it pulls the packages, imports
   them, the books are uploaded again as SAGA would hold them after the import, and a
   snapshot shows those documents validated (a person's Validare, simulated);
5. ``reconcile_sink``, ``monthly_close`` (hold, or file when asked), the filings due.

Each expectation is compared with what happened; any difference fails the scenario. A run's
outcome feeds the coverage map (:mod:`poarta_contabila.coverage`): what its expected path
names, and what actually happened (for data → catalog).

    uv run python -m poarta_contabila.scenarios [--local | --base-url URL] [names] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from poarta_contabila.coverage import (
    DocActual,
    MonthActual,
    ScenarioOutcome,
    Table,
    control_key,
)
from poarta_contabila.synthetic.docs import BankLine, ExpenseReport, Invoice, Statement
from poarta_contabila.synthetic.firms import firm as get_firm
from poarta_contabila.synthetic.months import Month, month, realistic
from poarta_contabila.types import Closed, Period

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = ROOT / "fixtures" / "scenarios"
AGENT_LABEL = "simulated SAGA agent (not a copy-firm import)"
TAKEN_AT = "2026-10-01T00:00:00Z"
_PROFILE_ARTICOL: dict[str, str] = {}  # recon profile → its reconcile_sink articol (lazy)

# ----- the scenario file -----


class DocExpect(Closed):
    source_doc: str | None = None
    job_kind: str | None = None
    articol: str | None = None
    asks: list[str] | None = None
    status: str | None = None
    module: str | None = None
    pre: str | None = None  # the PRE profile its check used
    post: str | None = None  # the POST profile its posting was checked with
    post_verdict: str | None = None
    refused: str | None = None  # a part of the reason an upload is refused
    error: str | None = None  # a part of the job's error


class MonthExpect(Closed):
    close: str | None = None  # the close kind
    material: bool | None = None
    blockers: list[str] | None = None  # heads: a control id, or the text before ':'
    controls: dict[str, Literal["PASS", "FAIL", "INFO"]] = Field(default_factory=dict)
    filings: list[str] | None = None
    receipts: list[str] | None = None  # filings closed by a receipt
    recon_asks: list[str] | None = None
    close_asks: list[str] | None = None
    v2: str | None = None  # the v2_close action that took effect


class Expect(Closed):
    documents: dict[str, DocExpect] = Field(default_factory=dict)
    months: dict[Period, MonthExpect] = Field(default_factory=dict)


class Answers(Closed):
    v3_approve: Literal["truth", "approve", "leave"] = "truth"
    by_ref: dict[str, dict[str, Any]] = Field(default_factory=dict)  # explicit answers
    decont_split: Literal["truth", "leave"] = "truth"
    upload_parts: bool = True  # an XML part's SPV zip is uploaded after the split
    recon_ambiguous: Literal["leave", "override_absent", "already_posted"] = "leave"
    recon_how_mismatch: Literal["leave", "ack_mismatch", "open_storno"] = "leave"
    v2_close: Literal["hold", "file", "reopen"] = "hold"
    explained_rule: str | None = None  # cited on v2_close
    v4_codit: Literal["skip", "accept"] = "skip"
    filing_receipts: list[str] = Field(default_factory=list)


class RuleSpec(Closed):
    rule_id: str
    body: dict[str, Any]


class Scenario(Closed):
    name: str
    note: str = ""
    firm: str
    book_of_record: Literal["saga", "nextup"] = "saga"
    period: Period
    seed: int = 0
    defect: str | None = None
    generator: Literal["standard", "realistic"] = "standard"
    months: list[Period] | None = None  # realistic: consecutive months (default: period)
    books: Literal["agent", "late", "in_books", "none"] = "agent"
    report_pack: bool = False  # also upload SAGA's purchase / sales journals
    upload: list[str] | None = None  # refs to upload, in order (default: the month's)
    agent: bool = True
    rules: list[RuleSpec] = Field(default_factory=list)
    answers: Answers = Field(default_factory=Answers)
    expect: Expect = Field(default_factory=Expect)


def load(path: str | Path) -> Scenario:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    sc = Scenario.model_validate(data)
    if sc.name != Path(path).stem:
        raise ValueError(f"{path}: name {sc.name!r} differs from the file name")
    return sc


def scenarios(names: Iterable[str] = (), directory: Path = SCENARIOS_DIR) -> list[Scenario]:
    want = set(names)
    out = [load(p) for p in sorted(directory.glob("*.yaml"))]
    missing = want - {s.name for s in out}
    if missing:
        raise KeyError(f"no scenario named {sorted(missing)}")
    return [s for s in out if not want or s.name in want]


# ----- what happened -----


@dataclass
class DocState:
    ref: str
    source_doc: str
    job_id: str | None = None
    asked: list[str] = field(default_factory=list)
    refused: str | None = None
    view: dict[str, Any] = field(default_factory=dict)
    post: dict[str, Any] = field(default_factory=dict)

    def see(self, view: dict[str, Any]) -> None:
        self.view = view
        kind = (view.get("question") or {}).get("kind")
        if kind and (not self.asked or self.asked[-1] != kind):
            self.asked.append(kind)

    @property
    def job(self) -> dict[str, Any]:
        return self.view.get("job") or {}

    def actual(self) -> dict[str, Any]:
        job = self.job
        return {
            "source_doc": self.source_doc,
            "job_kind": job.get("job_kind"),
            "articol": job.get("articol_id"),
            "asks": list(self.asked),
            "status": job.get("status"),
            "module": job.get("module_id"),
            "pre": (self.view.get("pre") or {}).get("profile_id"),
            "post": self.post.get("profile_id"),
            "post_verdict": self.post.get("verdict"),
            "refused": self.refused,
            "error": job.get("error"),
        }


@dataclass
class MonthState:
    period: str
    recon_asks: list[str] = field(default_factory=list)
    close_asks: list[str] = field(default_factory=list)
    run: dict[str, Any] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    controls: dict[str, str] = field(default_factory=dict)
    filings: list[str] = field(default_factory=list)
    receipts: list[str] = field(default_factory=list)
    v2: str | None = None

    def actual(self) -> dict[str, Any]:
        return {
            "close": self.run.get("close_kind"),
            "material": self.run.get("material"),
            "blockers": sorted({head(b) for b in self.blockers}),
            "controls": dict(self.controls),
            "filings": sorted(self.filings),
            "receipts": sorted(self.receipts),
            "recon_asks": list(self.recon_asks),
            "close_asks": list(self.close_asks),
            "v2": self.v2,
        }


def head(blocker: str) -> str:
    """A blocker's head: its control id, or the words before its first ':'."""
    text = blocker.split(":", 1)[0].strip()
    return text.removesuffix(" (advisory)").strip()


@dataclass
class Result:
    scenario: Scenario
    steps: list[str] = field(default_factory=list)
    diffs: list[str] = field(default_factory=list)
    docs: dict[str, DocState] = field(default_factory=dict)
    months: dict[str, MonthState] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.diffs

    def outcome(self) -> ScenarioOutcome:
        return ScenarioOutcome(
            name=self.scenario.name,
            passed=self.passed,
            names=frozenset(names(self.scenario)),
            documents=tuple(
                DocActual(
                    ref=d.ref,
                    status=None if d.refused else d.job.get("status"),
                    articol_id=d.job.get("articol_id"),
                    asked=tuple(d.asked),
                    error=d.refused or d.job.get("error"),
                )
                for d in self.docs.values()
                if d.refused or d.job_id
            ),
            months=tuple(
                MonthActual(m.period, tuple(m.blockers)) for m in self.months.values() if m.run
            ),
        )


def names(sc: Scenario) -> set[tuple[Table, str]]:
    """The catalog rows a scenario's expected path names (what coverage counts)."""
    out: set[tuple[Table, str]] = set()
    if not _PROFILE_ARTICOL:
        from poarta_contabila.catalog import load_catalog

        for aid, row in load_catalog().articole.items():
            if "profile_id" in row:
                _PROFILE_ARTICOL[row["profile_id"]] = aid
    for d in sc.expect.documents.values():
        if d.refused:
            continue
        if d.source_doc:
            out.add(("source_doc", d.source_doc))
        if d.job_kind:
            out.add(("job_kind", d.job_kind))
        if d.articol:
            out.add(("articol", d.articol))
        for kind in d.asks or []:
            out.add(("hitl", kind))
        if d.module:
            out.add(("write_module", d.module))
            out.add(("control", control_key("P_prefile_duplicate", "PASS")))
            out.add(("control", control_key("P_prefile_hard_failures", "PASS")))
        for profile in (d.pre, d.post):
            if profile:
                out.add(("recon_profile", profile))
                if profile in _PROFILE_ARTICOL:
                    out.add(("articol", _PROFILE_ARTICOL[profile]))
    for m in sc.expect.months.values():
        if m.close:
            out.add(("close_kind", m.close))
            out.add(("articol", m.close))  # each close kind names its articol of the same id
        for kind in [*(m.recon_asks or []), *(m.close_asks or [])]:
            out.add(("hitl", kind))
        for cid, status in m.controls.items():
            if status in ("PASS", "FAIL"):
                out.add(("control", control_key(cid, status)))
        for fid in m.filings or []:
            out.add(("filing", fid))
        if m.receipts:
            out.add(("hitl", "filing_receipt"))
        if m.v2 and sc.answers.explained_rule:
            out.add(("hitl", "explained_rule"))
    if sc.books != "none":
        rj, bal = (
            ("sink_rj", "sink_balanta_saga")
            if sc.book_of_record == "saga"
            else ("sink_rj_nextup", "sink_balanta_nextup")
        )
        out |= {("source_doc", rj), ("source_doc", bal), ("source_doc", "spv_register")}
    return out


# ----- the run -----


def line_ref(ln: BankLine) -> str:
    """A bank line's name in a scenario: ``pay:p1`` / ``get:s1`` / ``fee`` / ``salary``."""
    if ln.kind == "invoice" and ln.settles:
        return f"{'pay' if ln.side == 'debit' else 'get'}:{ln.settles[0][0]}"
    return ln.kind if ln.kind in ("fee", "salary") else (ln.reference or ln.description)


class Runner:
    def __init__(self, client: Any, agent: Any | None, sc: Scenario) -> None:
        self.c, self.agent, self.sc = client, agent, sc
        f = get_firm(sc.firm, book_of_record=sc.book_of_record)
        if sc.generator == "realistic":
            if sc.defect is not None:
                raise ValueError(f"{sc.name}: a realistic month draws its own noise, no defect")
            self.m: Month = realistic(f, sc.months or [sc.period], seed=sc.seed)
        else:
            self.m = month(f, sc.period, seed=sc.seed, defect=sc.defect)
        self.f = f
        self.r = Result(sc)
        self.rj_export: str | None = None
        self.periods = self.m.book.periods() or [sc.period]
        if sc.period not in self.periods:
            self.periods = sorted({*self.periods, sc.period})

    # -- helpers --

    def step(self, text: str) -> None:
        self.r.steps.append(text)

    def _ok(self, resp: Any, what: str) -> Any:
        try:
            body = resp.json()
        except ValueError:
            body = {"detail": resp.text[:200]}
        if resp.status_code >= 400:
            self.step(f"{what}: {resp.status_code} {body.get('detail', body)}")
        return body

    def _view(self, d: DocState) -> None:
        if d.job_id:
            resp = self.c.get(f"/jobs/{d.job_id}")
            if resp.status_code < 400:
                d.see(resp.json())

    # -- 1. tenant, CO.DiT, rules --

    def setup(self) -> None:
        f = self.f
        self._ok(self.c.put(f"/tenants/{f.cui}", json=f.tenant()), "tenant")
        for p in self.periods:
            self._ok(self.c.put(f"/codit/{f.cui}/{p}", json=f.codit()), f"codit {p}")
        for rule in self.sc.rules:
            body = {"cui": f.cui, "rule_id": rule.rule_id, **rule.body}
            self._ok(self.c.post("/rules", json=body), f"rule {rule.rule_id}")
        self.step(f"tenant {f.cui} ({f.key}, {f.book_of_record}); CO.DiT {self.periods}")

    # -- 2. books --

    def our_refs(self) -> set[str]:
        """Documents this run packages: their entries are absent before the agent imports."""
        refs = {ref for ref, doc in self.uploads() if isinstance(doc, Invoice)}
        refs |= {ln.reference for ln in self.m.bank if ln.kind == "invoice" and ln.reference}
        report = next((d for _, d in self.uploads() if isinstance(d, ExpenseReport)), None)
        if report is not None and self.sc.answers.upload_parts:
            refs |= {d.ref for d, fmt in report.parts if isinstance(d, Invoice) and fmt == "xml"}
        return refs

    def books(self, book: Any, when: str) -> None:
        m = Month(self.f, self.m.period, self.m.gen, book, self.m.docs, self.m.uploads)
        for kind, (filename, data, product) in m.exports().items():
            if kind.startswith("jurnal_") and not self.sc.report_pack:
                continue
            params = {"filename": filename, "periods": ",".join(self.periods)}
            if product:
                params["product"] = product
            resp = self.c.post(
                f"/tenants/{self.f.cui}/exports/{kind}",
                params=params,
                content=data,
                headers={"Content-Type": "application/octet-stream"},
            )
            body = self._ok(resp, f"export {kind} ({when})")
            if kind == "rj" and resp.status_code < 400:
                self.rj_export = body.get("export_id")
        self.step(f"books {when}: {len(book.entries)} journal lines")

    # -- 3. uploads and a person's answers --

    def uploads(self) -> list[tuple[str, Any]]:
        if self.sc.upload is None:
            return [(u.ref, u.doc) for u in self.m.uploads]
        return [(ref, self.m.docs[ref]) for ref in self.sc.upload]

    def upload_all(self) -> None:
        for ref, doc in self.uploads():
            if isinstance(doc, Invoice):
                self.ingest(ref, doc)
            elif isinstance(doc, Statement):
                self.statement(doc)
            elif isinstance(doc, ExpenseReport):
                self.decont(doc)
        self.step(f"uploaded {len(self.r.docs)} documents")

    def ingest(self, ref: str, inv: Invoice) -> None:
        data, name = (
            (inv.xml(self.f), f"{ref}.xml")
            if inv.foreign
            else (
                inv.spv_zip(self.f),
                f"{ref}.zip",
            )
        )
        d = self.r.docs.setdefault(ref, DocState(ref, "ro_efactura_ubl"))
        resp = self.c.post(
            "/ingest",
            params={"cui": self.f.cui, "filename": name},
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        body = self._ok(resp, f"ingest {ref}")
        if resp.status_code >= 400:
            d.refused = str(body.get("detail"))
            return
        d.job_id = body["job"]["job_id"]
        d.see(body)

    def statement(self, st: Statement) -> None:
        resp = self.c.post(f"/extras/{self.f.cui}", json=st.upload())
        body = self._ok(resp, f"statement {st.ref}")
        refs = [line_ref(ln) for ln in st.lines]
        if resp.status_code >= 400:
            for ref in refs:
                self.r.docs[ref] = DocState(ref, "extras_statement_pdf", refused=str(body))
            return
        for job in body.get("jobs", []):
            ref = refs[job["seq"] - 1]
            if ref in self.r.docs and self.r.docs[ref].job_id != job["job"]["job_id"]:
                ref = f"{ref}@{st.day[:7]}"  # a fee or salary line of another month
            d = self.r.docs.setdefault(ref, DocState(ref, "extras_statement_pdf"))
            d.job_id = job["job"]["job_id"]
            d.see(job)

    def decont(self, report: ExpenseReport) -> None:
        resp = self.c.post(f"/decont/{self.f.cui}", json=report.upload(self.f))
        batch = self._ok(resp, f"expense report {report.ref}")
        d = self.r.docs.setdefault(report.ref, DocState(report.ref, "decont_cheltuieli"))
        if resp.status_code >= 400:
            d.refused = str(batch.get("detail"))
            return
        kind = (batch.get("question") or {}).get("kind")
        if kind:
            d.asked.append(kind)
        if kind == "decont_split" and self.sc.answers.decont_split == "truth":
            answer = report.split_answer(self.f)
            resp = self.c.post(f"/triage/{batch['batch_id']}/resume", json=answer)
            batch = self._ok(resp, "decont_split")
        by_hash = {p["part_hash"]: i for i, p in enumerate(report.split_answer(self.f)["parts"])}
        for child in batch.get("children", []):
            doc, fmt = report.parts[by_hash[child["part_hash"]]]
            cd = self.r.docs.setdefault(doc.ref, DocState(doc.ref, child["source_doc_id"]))
            cd.job_id = child.get("job_id")
            if cd.job_id is None:  # evidence or a PDF that waits for its XML: no Job
                cd.view = {"job": {"status": None, "error": f"emit: {child['failed']}"}}
            else:
                self._view(cd)
            if isinstance(doc, Invoice) and fmt == "xml" and self.sc.answers.upload_parts:
                self.ingest(doc.ref, doc)

    def answer_jobs(self) -> None:
        for _ in range(3):
            changed = False
            for ref, d in self.r.docs.items():
                self._view(d)
                q = d.view.get("question") or {}
                if q.get("kind") != "v3_approve":
                    continue
                answer = self.v3_answer(ref)
                if answer is None:
                    continue
                resp = self.c.post(f"/jobs/{d.job_id}/resume", json=answer)
                d.see(self._ok(resp, f"v3_approve {ref}"))
                changed = True
            if not changed:
                return

    def v3_answer(self, ref: str) -> dict[str, Any] | None:
        a = self.sc.answers
        if ref in a.by_ref:
            return a.by_ref[ref]
        if a.v3_approve == "leave":
            return None
        line = next((ln for ln in self.m.bank if line_ref(ln) == ref), None)
        if line is None:
            return {"decision": "approve", "edit": None}
        if a.v3_approve == "approve" or line.kind != "invoice" or line.partner is None:
            return None if line.kind != "invoice" else {"decision": "approve", "edit": None}
        inv = self.m.docs[line.settles[0][0]]
        role = "supplier" if line.side == "debit" else "customer"
        return {
            "decision": "edit",
            "edit": {
                "partner": {"cui": line.partner.cui, "name": line.partner.name, "role": role},
                "maps": {"factura_numar": inv.number},
            },
        }

    # -- 4. the simulated SAGA agent --

    def saga_agent(self) -> None:
        if self.agent is None or not self.sc.agent or self.sc.books not in ("agent", "late"):
            self.step("agent: not run")
            return
        n = 0
        for run in range(1, 21):  # one pull is one import folder; the agent pulls until none
            pulled = self.agent.get("/agent/pull").json()
            if not pulled.get("batches"):
                break
            n += self._import(pulled, run)
        self.books(self.m.book, "after the import")
        snap = {
            "cui": self.f.cui,
            "folder": self.f.folder,
            "taken_at": TAKEN_AT,
            "closed_periods": [],
            "documents": self.snapshot_documents(),
        }
        result = self.agent.post("/agent/snapshot", json=snap).json()
        self.step(
            f"{AGENT_LABEL}: imported {n} in {run - 1} run(s); snapshot acked "
            f"{len(result.get('acked', []))}, unmatched {len(result.get('unmatched', []))}, "
            f"intent mismatch {len(result.get('intent_mismatch', []))}"
        )
        for d in self.r.docs.values():
            self._view(d)

    def _import(self, pulled: dict[str, Any], run: int) -> int:
        n = 0
        for batch in pulled.get("batches", []):
            label = None
            if batch["backup"] != "none":
                label = f"{batch['cui']}:{batch['folder']}:20261001T{run:02d}0000Z"
                self.agent.post(
                    "/agent/ack-backup",
                    json={"label": label, "cui": batch["cui"], "folder": batch["folder"]},
                )
            results = [{"export_key": i["export_key"], "ok": True} for i in batch["items"]]
            self.agent.post(
                "/agent/imported",
                json={
                    "cui": batch["cui"],
                    "folder": batch["folder"],
                    "backup_label": label,
                    "results": results,
                },
            )
            n += len(results)
        return n

    def snapshot_documents(self) -> list[dict[str, Any]]:
        """What SAGA shows after the import: the books' documents, validated (a person's
        Validare, simulated), read back through the real export readers; net, VAT and the
        partner's CUI only when the report pack is read (ARCHITECTURE §13)."""
        from poarta_contabila.sinks.exports import (
            ExportEye,
            read_nextup_balanta,
            read_nextup_rj,
            read_saga_balanta,
            read_saga_rj,
        )

        ex = self.m.exports()
        product = self.f.book_of_record
        readers = (
            (read_saga_rj, read_saga_balanta)
            if product == "saga"
            else (read_nextup_rj, read_nextup_balanta)
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = {}
            for kind in ("rj", "balanta"):
                name, data, _ = ex[kind]
                paths[kind] = Path(tmp) / name
                paths[kind].write_bytes(data)
            eye = ExportEye(
                product=product,
                lines=readers[0](paths["rj"]),
                balance=readers[1](paths["balanta"]),
                cui=self.f.cui,
            )
        out = []
        for p in self.periods:
            for d in eye.documents(self.f.cui, p):
                shown = {
                    "saga_doc_key": d.saga_key,
                    "doc_class": d.doc_class,
                    "number": d.number,
                    "date": d.date,
                    "gross": d.gross,
                    "validated": True,
                }
                if self.sc.report_pack:  # net / VAT / partner only from the report pack (§13)
                    shown.update(net=d.net, vat=d.vat, partner_cui=d.partner_cui)
                out.append(shown)
        return out

    # -- 5. reconcile, close, filings --

    def reconcile(self, period: str) -> None:
        ms = self.r.months.setdefault(period, MonthState(period))
        body = self._ok(self.c.post(f"/recon/{self.f.cui}/{period}"), f"recon {period}")
        for _ in range(12):
            q = body.get("question") or {}
            kind = q.get("kind")
            if not kind:
                break
            ms.recon_asks.append(kind)
            answer = self.recon_answer(kind, q)
            if answer is None:
                break
            body = self._ok(
                self.c.post(f"/recon/{self.f.cui}/{period}/resume", json=answer),
                f"recon {kind}",
            )
        for entry in body.get("settled", []):
            if entry.get("stage") == "post":
                for d in self.r.docs.values():
                    if d.job_id == entry["job_id"]:
                        d.post = entry

    def recon_answer(self, kind: str, q: dict[str, Any]) -> dict[str, Any] | None:
        a = self.sc.answers
        if kind == "need_rj_export" and self.rj_export:
            return {"export_id": self.rj_export}
        if kind == "recon_ambiguous" and a.recon_ambiguous != "leave":
            ids = [0] if a.recon_ambiguous == "already_posted" else []
            return {"action": a.recon_ambiguous, "sink_line_ids": ids}
        if kind == "recon_how_mismatch" and a.recon_how_mismatch != "leave":
            return {
                "ack_mismatch": a.recon_how_mismatch == "ack_mismatch",
                "open_storno": a.recon_how_mismatch == "open_storno",
            }
        return None

    def close(self, period: str) -> None:
        ms = self.r.months.setdefault(period, MonthState(period))
        a = self.sc.answers
        reopened = False
        body = self._ok(self.c.post(f"/close/{self.f.cui}/{period}"), f"close {period}")
        for _ in range(6):
            q = body.get("question") or {}
            kind = q.get("kind")
            if not kind:
                break
            if not ms.close_asks or ms.close_asks[-1] != kind or q.get("error"):
                ms.close_asks.append(kind)
            if kind == "v2_close":
                ms.blockers = list(q.get("blockers") or [])
                lock = any(head(b) == "lock mismatch" for b in ms.blockers)
                if lock and not reopened:
                    answer = {"action": "reopen", "explained_rule": None}
                    reopened = True
                elif q.get("error") or a.v2_close == "hold":
                    answer = {"action": "hold", "explained_rule": a.explained_rule}
                else:
                    answer = {"action": a.v2_close, "explained_rule": a.explained_rule}
                path = f"/close/{self.f.cui}/{period}/resume"
                body = self._ok(self.c.post(path, json=answer), f"v2_close {period}")
                if answer["action"] == "reopen":
                    body = self._ok(self.c.post(f"/close/{self.f.cui}/{period}"), "close again")
                    ms.close_asks = []
                    continue
                if not (body.get("question") or {}).get("error"):
                    ms.v2 = answer["action"]
            elif kind == "v4_codit":
                accept = a.v4_codit == "accept"
                answer = {"accept": accept, "skip": not accept, "edit": None, "seed_next": None}
                body = self._ok(
                    self.c.post(f"/close/{self.f.cui}/{period}/resume", json=answer), "v4_codit"
                )
            else:
                break
        ms.run = body.get("run") or {}
        if not ms.blockers:
            ms.blockers = list(ms.run.get("blockers") or [])

    def filings(self, period: str) -> None:
        ms = self.r.months.setdefault(period, MonthState(period))
        items = self._ok(self.c.post(f"/filings/{self.f.cui}/{period}"), f"filings {period}")
        if isinstance(items, list):
            ms.filings = [i["filing_id"] for i in items]
        for fid in self.sc.answers.filing_receipts:
            resp = self.c.post(
                f"/filings/{self.f.cui}/{period}/{fid}/receipt",
                params={"filename": f"{fid}.pdf", "submitted_by": "synthetic"},
                content=b"%PDF-1.4 synthetic receipt",
                headers={"Content-Type": "application/octet-stream"},
            )
            if resp.status_code < 400:
                ms.receipts.append(fid)
            else:
                self._ok(resp, f"receipt {fid}")
        diff = self._ok(self.c.get(f"/periods/{self.f.cui}/{period}/diff"), f"diff {period}")
        ms.controls = {c["control_id"]: c["status"] for c in diff.get("controls", [])}

    # -- all --

    def run(self) -> Result:
        self.setup()
        before = self.m.book.without(self.our_refs())
        if self.sc.books == "agent":
            self.books(before, "before")
        elif self.sc.books == "in_books":
            self.books(self.m.book, "holding every document")
        self.upload_all()
        self.answer_jobs()
        if self.sc.books == "late":  # the books come after the documents: PRE waits on them
            for p in self.periods:
                self.reconcile(p)  # asks for the books (need_rj_export); none to name yet
            self.books(before, "uploaded late")
        for p in self.periods:
            self.reconcile(p)
        self.answer_jobs()
        self.saga_agent()
        for p in self.periods:
            self.reconcile(p)
        for p in self.periods:
            self.close(p)
            self.filings(p)
        for d in self.r.docs.values():
            self._view(d)
        self.compare()
        return self.r

    def compare(self) -> None:
        for ref, want in self.sc.expect.documents.items():
            d = self.r.docs.get(ref)
            if d is None:
                self.r.diffs.append(f"{ref}: expected, never uploaded or seen")
                continue
            got = d.actual()
            for key, value in want.model_dump(exclude_none=True).items():
                if key in ("refused", "error"):
                    if value not in str(got.get(key) or ""):
                        self.r.diffs.append(f"{ref}.{key}: expected …{value}…, got {got[key]!r}")
                elif got.get(key) != value:
                    self.r.diffs.append(f"{ref}.{key}: expected {value!r}, got {got.get(key)!r}")
        for period, want in self.sc.expect.months.items():
            ms = self.r.months.get(period)
            if ms is None:
                self.r.diffs.append(f"{period}: expected, never closed")
                continue
            got = ms.actual()
            for key, value in want.model_dump(exclude_none=True).items():
                if key == "controls":
                    for cid, status in value.items():
                        if got["controls"].get(cid) != status:
                            self.r.diffs.append(
                                f"{period}.{cid}: expected {status}, got {got['controls'].get(cid)}"
                            )
                    continue
                expected = sorted(value) if key in ("blockers", "filings", "receipts") else value
                if got.get(key) != expected:
                    self.r.diffs.append(
                        f"{period}.{key}: expected {expected!r}, got {got.get(key)!r}"
                    )


# ----- clients -----


def local_clients() -> tuple[Any, Any]:
    """An in-memory runtime (``MODEL_CALLS=dry``) behind the real app: operator and agent."""
    from fastapi.testclient import TestClient
    from langgraph.checkpoint.memory import MemorySaver

    from poarta_contabila.agent import InMemoryAgentStore
    from poarta_contabila.app import create_app
    from poarta_contabila.catalog import load_catalog
    from poarta_contabila.close import InMemoryCloseStore
    from poarta_contabila.codit import InMemoryCoditStore
    from poarta_contabila.filings import InMemoryFilingStore
    from poarta_contabila.jobs import InMemoryJobStore
    from poarta_contabila.packages import InMemoryBlobStore, InMemoryPackageStore
    from poarta_contabila.period_diff import InMemoryPeriodStore
    from poarta_contabila.recon.pre import InMemoryReconStore
    from poarta_contabila.registry import InMemoryRegistry
    from poarta_contabila.rules import InMemoryRuleStore
    from poarta_contabila.runtime import build_runtime

    rt = build_runtime(
        catalog=load_catalog(),
        jobs=InMemoryJobStore(),
        packages=InMemoryPackageStore(),
        blobs=InMemoryBlobStore(),
        registry=InMemoryRegistry(),
        recon=InMemoryReconStore(),
        agent_store=InMemoryAgentStore(),
        checkpointer=MemorySaver(),
        periods=InMemoryPeriodStore(),
        rules=InMemoryRuleStore(),
        closes=InMemoryCloseStore(),
        codits=InMemoryCoditStore(),
        filings=InMemoryFilingStore(),
        model_mode="dry",
    )
    app = create_app(None, runtime=rt, operator_token="scenario-op", agent_token="scenario-agent")
    return (
        TestClient(app, headers={"Authorization": "Bearer scenario-op"}),
        TestClient(app, headers={"Authorization": "Bearer scenario-agent"}),
    )


def run_one(sc: Scenario, client: Any = None, agent: Any = None) -> Result:
    """Run *sc*; with no client, on a fresh in-memory runtime of its own."""
    if client is None:
        client, agent = local_clients()
    return Runner(client, agent, sc).run()


def run_all(names: Iterable[str] = ()) -> list[Result]:
    return [run_one(sc) for sc in scenarios(names)]


def actual_expect(r: Result) -> dict[str, Any]:
    """What happened, in the shape of ``expect:``."""
    docs = {}
    for ref, d in r.docs.items():
        a = {k: v for k, v in d.actual().items() if v not in (None, "")}
        a.pop("error", None)
        docs[ref] = a
    months = {}
    for p, ms in r.months.items():
        a = ms.actual()
        a["controls"] = {k: v for k, v in a["controls"].items() if v != "INFO"}
        months[p] = a
    return {"expect": {"documents": docs, "months": months}}


def render(results: list[Result]) -> str:
    lines = [f"scenarios: {len(results)} ({AGENT_LABEL})", ""]
    for r in results:
        sc = r.scenario
        mark = "pass" if r.passed else "FAIL"
        lines.append(
            f"[{mark}] {sc.name}  {sc.firm} {sc.period} seed {sc.seed}"
            + (f" defect {sc.defect}" if sc.defect else "")
        )
        if sc.note:
            lines.append(f"       {sc.note}")
        for s in r.steps:
            lines.append(f"       · {s}")
        for ref, d in r.docs.items():
            a = d.actual()
            lines.append(
                f"       {ref:<12} {a['source_doc']:<22} {a['articol'] or '-':<22} "
                f"{a['status'] or ('refused' if d.refused else '-'):<16} asks {a['asks']}"
            )
        for p, ms in r.months.items():
            a = ms.actual()
            lines.append(
                f"       {p}: {a['close']} material={a['material']} v2={a['v2']} "
                f"blockers={a['blockers']} filings={a['filings']}"
            )
        for diff in r.diffs:
            lines.append(f"       ✗ {diff}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="poarta_contabila.scenarios", description=__doc__.split("\n")[0]
    )
    where = ap.add_mutually_exclusive_group()
    where.add_argument("--local", action="store_true", help="in-memory runtime (the default)")
    where.add_argument("--base-url", help="the operator API (synthetic tenants only)")
    ap.add_argument("names", nargs="*", help="scenario names (default: all)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--actual",
        action="store_true",
        help="print what happened in the shape of a scenario's expect: (to review, not to copy)",
    )
    args = ap.parse_args(argv)
    chosen = scenarios(args.names)
    if args.base_url:
        import os

        import httpx

        from poarta_contabila.smoke import caller_token

        token = caller_token()
        if not token:
            print("set GRAPHUSERTOKEN_OPERATOR or GRAPHUSERTOKEN_CLAUDE_SYSBUILDER")
            return 2
        base = args.base_url.rstrip("/")
        client = httpx.Client(
            base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=120
        )
        agent_token = os.environ.get("GRAPHUSERTOKEN_AGENT_SHARED")
        agent = (
            httpx.Client(
                base_url=base, headers={"Authorization": f"Bearer {agent_token}"}, timeout=120
            )
            if agent_token
            else None
        )
        results = [run_one(sc, client, agent) for sc in chosen]
    else:
        results = [run_one(sc) for sc in chosen]
    if args.actual:
        for r in results:
            print(
                f"# {r.scenario.name}: what happened\n"
                + yaml.safe_dump(actual_expect(r), sort_keys=False, allow_unicode=True)
            )
        return 0 if all(r.passed for r in results) else 1
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "name": r.scenario.name,
                        "passed": r.passed,
                        "diffs": r.diffs,
                        "documents": {k: d.actual() for k, d in r.docs.items()},
                        "months": {k: m.actual() for k, m in r.months.items()},
                    }
                    for r in results
                ],
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )
    else:
        print(render(results))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
