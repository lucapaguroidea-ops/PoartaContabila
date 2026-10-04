"""the synthetic smoke run — one invented firm through the whole flow over HTTP.

Drives the operator API the way a person would, with scripted answers, then shows what every
model role was given at its place in the flow (``GET /model-calls``, ``MODEL_CALLS=dry``):

1. ``GET /model-roles`` — the mode, and which key variables are set (never their values);
2. ``PUT /tenants/1000009`` — ``FIRMA TEST SRL``, ``data_class: synthetic``, one bank account;
3. the registru jurnal (``fixtures/sink/saga_rj_smoke.xls``): a clean August, then September;
4. an SPV invoice (``fixtures/ubl``, number ``AB 0099``) → ``v3_approve`` → approve;
5. a bank statement (header + tables, no Document AI) → the receipt's ``v3_approve`` → bound
   to its partner and invoice;
6. an expense report → ``decont_split`` → one workings part (evidence, no Job);
7. ``reconcile_sink`` — ``need_rj_export`` is answered with the uploaded journal; any other
   question is left for a person;
8. the clean month: August's SPV invoice (``AB 0070``) and statement, every document
   already in the books, so each job ends ``already_in_sink``;
9. ``monthly_close`` for September, then August → ``v2_close`` → ``hold`` (nothing is filed).
   September stays material (its packages wait for an agent; its books hold invoices never
   uploaded here); August should show no blocker. On a lock mismatch (the month's jobs
   changed since it was locked) the run answers ``reopen`` first and closes again;
10. a September invoice (``AB 0102``) left at ``v3_approve``: its explanation, before
    the closes;
11. ``GET /model-calls`` for this firm, grouped by graph and node.

``--ocr`` adds one step: a second statement, a real one-page PDF generated here
(invented firm, invented movement), uploaded **without** its tables, so the server's reader
reads it. With ``MODEL_CALLS=live`` and ``GOOGLE_AI_STUDIO_DIRECT_SYNTHETIC`` set, that is
Gemini through Google AI Studio; ``/model-calls`` then shows ``ocr_extract`` as ``sent``.

Every answer is given only when the expected question is the one waiting, so a second run
changes nothing and reports what is already there. The firm, partner and documents are
invented (LAW: no client data); the run refuses a server whose ``MODEL_CALLS`` is not
``off``, ``dry`` or ``live``.

    uv run python -m poarta_contabila.smoke --local                    # in memory, dry
    GRAPHUSERTOKEN_OPERATOR=… uv run python -m poarta_contabila.smoke --base-url https://…
    GRAPHUSERTOKEN_OPERATOR=… uv run python -m poarta_contabila.smoke --base-url https://… --ocr

The build agent runs it with ``GRAPHUSERTOKEN_CLAUDE_SYSBUILDER`` instead (synthetic only).

Packaged documents wait on ``/agent/pull`` for an agent; with no agent connected they stay.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from poarta_contabila.key_usage import describe

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"

CUI, FOLDER, PERIOD = "1000009", "0001", "2026-09"  # invented, valid check digit
CLEAN = "2026-08"  # the month whose books hold exactly what is uploaded here
PARTNER = "20000005"  # invented, valid check digit
IBAN = "RO49AAAA1B31007593840000"  # the textbook example IBAN
TENANT = {
    "cui": CUI,
    "name": "FIRMA TEST SRL",
    "saga_firm_folder": FOLDER,
    "data_class": "synthetic",
    "bank_accounts": {IBAN: "5121.01"},
}
STATEMENT = {
    "meta": {
        "iban": IBAN,
        "holder_cui": f"RO{CUI}",
        "currency": "RON",
        "opening": "5000.00",
        "closing": "4290.00",
        "statement_date": "2026-09-30",
    },
    "tables": [
        {"headers": ["Extras de cont", "", ""], "rows": [["Sold initial", "", "5.000,00"]]},
        {
            "headers": ["Data", "Descriere", "Referinta", "Debit", "Credit"],
            "rows": [
                ["15.09.2026", "Plata FURNIZOR TEST SRL fact 1427", "OP-77", "1.210,00", ""],
                ["20.09.2026", "Incasare CLIENT TEST SRL FX-101", "", "", "500,00"],
                ["", "Total rulaje", "", "1.210,00", "500,00"],
            ],
        },
    ],
    "pdf_b64": base64.b64encode(b"%PDF-1.4 synthetic statement (smoke)").decode(),
}
CLEAN_STATEMENT = {  # both lines are already in saga_rj_smoke.xls; closing = Sept's opening
    "meta": {
        "iban": IBAN,
        "holder_cui": f"RO{CUI}",
        "currency": "RON",
        "opening": "5307.81",
        "closing": "5000.00",
        "statement_date": "2026-08-31",
    },
    "tables": [
        {"headers": ["Extras de cont", "", ""], "rows": [["Sold initial", "", "5.307,81"]]},
        {
            "headers": ["Data", "Descriere", "Referinta", "Debit", "Credit"],
            "rows": [
                ["20.08.2026", "Plata ALT FURNIZOR SRL fact AB 0070", "OP-81", "807,81", ""],
                ["25.08.2026", "Incasare CLIENT TEST SRL FX-090", "IN-25", "", "500,00"],
                ["", "Total rulaje", "", "807,81", "500,00"],
            ],
        },
    ],
    "pdf_b64": base64.b64encode(b"%PDF-1.4 synthetic statement, August (smoke)").decode(),
}
RECEIPT_BINDING = {
    "partner": {"cui": PARTNER, "name": "CLIENT TEST SRL", "role": "customer"},
    "maps": {"factura_numar": "FX-101"},
}
REPORT = b"%PDF-1.4 synthetic expense report (smoke)"
WORKINGS = b"synthetic workings (smoke)"
SAFE_MODES = ("off", "dry", "live")
# who runs the smoke / evaluation against a server: a person with the operator token, or the
# build agent with its synthetic-only token; the old name last
CALLER_ENV = ("GRAPHUSERTOKEN_OPERATOR", "GRAPHUSERTOKEN_CLAUDE_SYSBUILDER", "OPERATOR_TOKEN")


def caller_token() -> str | None:
    """The bearer token for --base-url: the first of ``CALLER_ENV`` that is set."""
    for name in CALLER_ENV:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None  # live: only synthetic document reading sends


OCR_LINES = [
    "BANCA TEST SA - EXTRAS DE CONT",
    "Titular: FIRMA TEST SRL   CUI: RO1000009",
    "IBAN: RO49 AAAA 1B31 0075 9384 0000   Moneda: RON",
    "Data extras: 30.09.2026",
    "Sold initial: 4.290,00",
    "",
    "Data        Descriere                          Referinta   Debit      Credit",
    "25.09.2026  Incasare CLIENT TEST SRL FX-102    OP-91                  300,00",
    "",
    "Total rulaje                                               0,00       300,00",
    "Sold final: 4.590,00",
]
OCR_META = {
    "iban": IBAN,
    "holder_cui": f"RO{CUI}",
    "currency": "RON",
    "opening": "4290.00",
    "closing": "4590.00",
    "statement_date": "2026-09-30",
}


class Client(Protocol):
    """``httpx.Client`` or FastAPI's ``TestClient``, with the operator header set."""

    def get(self, url: str, **kw: Any) -> Any: ...
    def post(self, url: str, **kw: Any) -> Any: ...
    def put(self, url: str, **kw: Any) -> Any: ...


class SmokeRefused(RuntimeError):
    """The server is not one the smoke run may write to."""


@dataclass
class Step:
    name: str
    status: int
    outcome: str
    ok: bool = True


@dataclass
class Report:
    mode: str = "?"
    steps: list[Step] = field(default_factory=list)
    calls: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)


def spv_invoice(
    number: str = "AB 0099",
    *,
    issued: str = "2026-09-10",
    due: str = "2026-10-10",
    spv_id: str = "4100000001",
) -> bytes:
    """The fixture invoice as an SPV zip (XML + signature), numbered ``AB 0099`` (or as
    given: the clean month's ``AB 0070`` of 12.08)."""
    xml = (FIXTURES / "ubl/invoice_inbound.xml").read_bytes()
    xml = xml.replace(b"<cbc:ID>AB 0058</cbc:ID>", f"<cbc:ID>{number}</cbc:ID>".encode())
    xml = xml.replace(b"<cbc:IssueDate>2026-09-10<", f"<cbc:IssueDate>{issued}<".encode())
    xml = xml.replace(b"<cbc:DueDate>2026-10-10<", f"<cbc:DueDate>{due}<".encode())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in (
            (f"{spv_id}.xml", xml),
            (f"semnatura_{spv_id}.xml", (FIXTURES / "ubl/semnatura.xml").read_bytes()),
        ):
            # a fixed timestamp: the same bytes on every run, so a rerun finds the same Job
            zf.writestr(zipfile.ZipInfo(name, date_time=(2026, 10, 1, 0, 0, 0)), data)
    return buf.getvalue()


def _json(resp: Any) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {"detail": resp.text[:200]}


def _kind(view: dict[str, Any]) -> str | None:
    q = view.get("question") if isinstance(view, dict) else None
    return q.get("kind") if isinstance(q, dict) else None


def _outcome(view: dict[str, Any]) -> str:
    if not isinstance(view, dict):
        return str(view)[:120]
    if "detail" in view:
        return f"refused: {view['detail']}"
    if view.get("status") == "waiting":  # parked, read again from not_before
        return f"waiting for model quota until {view.get('not_before')}: {view.get('reason')}"[:300]
    job = view.get("job") or {}
    parts = [f"job {job['status']}" if job.get("status") else None]
    if job.get("error"):
        parts.append(f"({job['error']})")
    if _kind(view):
        parts.append(f"asks {_kind(view)}")
    return " ".join(p for p in parts if p) or "done"


def _octet(c: Client, url: str, data: bytes, params: dict[str, str]) -> Any:
    return c.post(
        url, params=params, content=data, headers={"Content-Type": "application/octet-stream"}
    )


def _answer_job(
    c: Client, report: Report, name: str, view: dict[str, Any], kind: str, body: Any
) -> dict[str, Any]:
    """Answer the job's question only when *kind* is the one waiting."""
    if _kind(view) != kind:
        report.steps.append(Step(name, 200, f"nothing to answer: {_outcome(view)}"))
        return view
    resp = c.post(f"/jobs/{view['job']['job_id']}/resume", json=body)
    after = _json(resp)
    report.steps.append(Step(name, resp.status_code, _outcome(after), resp.status_code < 400))
    return after


def synthetic_statement_pdf(lines: list[str] = OCR_LINES) -> bytes:
    """A real one-page PDF of the invented statement (``synthetic_docs.text_pdf``): the same
    bytes on every run, so a rerun reuses the stored extract instead of reading again."""
    from poarta_contabila.synthetic_docs import text_pdf

    return text_pdf([lines])


def _ocr_step(c: Client, report: Report) -> None:
    """--ocr: the server's reader reads a synthetic statement PDF (no tables are sent)."""
    resp = c.post(
        f"/extras/{CUI}",
        json={"meta": OCR_META, "pdf_b64": base64.b64encode(synthetic_statement_pdf()).decode()},
    )
    out = _json(resp)
    outcome = "; ".join(_outcome(j) for j in out.get("jobs", [])) or _outcome(out)
    report.steps.append(
        Step("statement PDF read", resp.status_code, outcome, resp.status_code in (200, 201))
    )


def _close(c: Client, report: Report, period: str) -> None:
    """``monthly_close`` for *period*, answered ``hold`` (nothing is filed). A lock mismatch
    means the month's jobs changed since it was locked: ``reopen`` first (what a person
    does), then close again."""
    note = ""
    for _ in range(2):
        resp = c.post(f"/close/{CUI}/{period}", params={"tva": "tva_platitor"})
        close = _json(resp)
        if _kind(close) != "v2_close":
            outcome = f"run {(close.get('run') or {}).get('status')}; asks {_kind(close)}"
            report.steps.append(
                Step(f"monthly_close {period}", resp.status_code, outcome, resp.status_code < 400)
            )
            return
        material = close["question"].get("material")
        blockers = close["question"].get("blockers") or []
        if not note and any(b.startswith("lock mismatch") for b in blockers):
            resp = c.post(
                f"/close/{CUI}/{period}/resume", json={"action": "reopen", "explained_rule": None}
            )
            if resp.status_code >= 400:
                break
            note = "reopened after a lock mismatch; "
            continue
        resp = c.post(
            f"/close/{CUI}/{period}/resume", json={"action": "hold", "explained_rule": None}
        )
        close = _json(resp)
        outcome = f"{note}material={material}; held ({(close.get('run') or {}).get('status')})"
        outcome += "".join(f"\n{'':27}blocker: {b}" for b in blockers)
        report.steps.append(
            Step(f"monthly_close {period}", resp.status_code, outcome, resp.status_code < 400)
        )
        return
    report.steps.append(
        Step(f"monthly_close {period}", resp.status_code, _outcome(_json(resp)), False)
    )


def _approval_explanation(c: Client, report: Report) -> None:
    """a September invoice (``AB 0102``) is left at its ``v3_approve``, never answered,
    so every run shows the approval question's System Two explanation (sent once, then found
    again). September is already held as material; this adds one waiting job to it."""
    invoice = spv_invoice("AB 0102", issued="2026-09-25", due="2026-10-25", spv_id="4100000003")
    resp = _octet(c, "/ingest", invoice, {"cui": CUI, "filename": "spv-ab0102.zip"})
    view = _json(resp)
    if _kind(view) != "v3_approve":
        outcome = f"no approval question: {_outcome(view)}"
    elif view.get("explanation"):
        e = view["explanation"]
        outcome = f"{e.get('served_by')}: {e.get('explanation')}"
    else:
        job_calls = c.get("/model-calls", params={"role": "sys2_explain_approve", "limit": 1})
        last = (_json(job_calls) or [{}])[0] if job_calls.status_code < 400 else {}
        outcome = f"none: {last.get('status')} ({last.get('reason')})"
    report.steps.append(
        Step("approval explanation", resp.status_code, outcome[:400], resp.status_code < 400)
    )


def run(
    c: Client,
    *,
    allow_mode: Callable[[str], bool] = SAFE_MODES.__contains__,
    ocr: bool = False,
) -> Report:
    """The smoke run against *c*; see the module docstring for the steps."""
    report = Report()

    resp = c.get("/model-roles")
    if resp.status_code >= 400:
        raise SmokeRefused(f"GET /model-roles answered {resp.status_code}: {_json(resp)}")
    roles = {r["role_id"]: r for r in resp.json()}
    modes = {r["mode"] for r in roles.values()}
    report.mode = ",".join(sorted(modes))
    if not all(allow_mode(m) for m in modes):
        raise SmokeRefused(f"MODEL_CALLS is {report.mode}: the smoke run needs off, dry or live")
    keys = sorted({f"{r['key_env']}={'set' if r['key_set'] else 'unset'}" for r in roles.values()})
    pins = [r.get("pin") or {} for r in roles.values()]
    moved = sorted(
        {
            f"{rid}: {p['reason']}"
            for rid, p in zip(roles, pins, strict=True)
            if p.get("on") not in (None, "main")
        }
    )
    keys.append(f"{sum(1 for p in pins if p.get('on') == 'main')} on their main pin")
    report.steps.append(Step("model roles", 200, f"mode {report.mode}; " + ", ".join(keys)))
    for line in moved:  # an alternate, an operator choice, or no passing model
        report.steps.append(Step("model pin", 200, line[:300]))
    resp = c.get("/model-keys")  # OpenRouter's own spend per key (never a key value)
    if resp.status_code < 400:
        for line in describe(resp.json()):
            report.steps.append(Step("openrouter key", 200, line[:300]))
    eu = [r for r in roles.values() if r.get("eu_route_set")]
    report.steps.append(
        Step(
            "eu route",
            200,
            f"set on {len(eu)} of {len(roles)} roles; a client firm is refused by the others",
        )
    )

    resp = c.put(f"/tenants/{CUI}", json=TENANT)
    report.steps.append(Step("tenant", resp.status_code, "synthetic", resp.status_code < 400))

    resp = _octet(
        c,
        f"/tenants/{CUI}/exports/rj",
        (FIXTURES / "sink/saga_rj_smoke.xls").read_bytes(),
        {"filename": "rj.xls", "product": "saga"},
    )
    rj = _json(resp)
    export_id = rj.get("export_id")
    report.steps.append(
        Step("registru jurnal", resp.status_code, f"covers {rj.get('periods')}", bool(export_id))
    )

    resp = _octet(c, "/ingest", spv_invoice(), {"cui": CUI, "filename": "spv.zip"})
    view = _json(resp)
    report.steps.append(
        Step("invoice upload", resp.status_code, _outcome(view), resp.status_code < 400)
    )
    if resp.status_code < 400:
        _answer_job(
            c,
            report,
            "invoice v3_approve",
            view,
            "v3_approve",
            {"decision": "approve", "edit": None},
        )

    resp = c.post(f"/extras/{CUI}", json=STATEMENT)
    out = _json(resp)
    report.steps.append(
        Step(
            "statement upload",
            resp.status_code,
            "; ".join(_outcome(j) for j in out.get("jobs", [])) or _outcome(out),
            resp.status_code < 400,
        )
    )
    for i, j in enumerate(out.get("jobs", []), 1):
        if _kind(j) is None:
            continue  # already in the books, or already answered
        _answer_job(
            c,
            report,
            f"line {i} v3_approve",
            j,
            "v3_approve",
            {"decision": "edit", "edit": RECEIPT_BINDING},
        )

    if ocr:
        _ocr_step(c, report)

    resp = c.post(
        f"/decont/{CUI}",
        json={
            "filename": "decont.pdf",
            "period": PERIOD,
            "file_b64": base64.b64encode(REPORT).decode(),
            "tenant_on_doc": True,
        },
    )
    batch = _json(resp)
    report.steps.append(
        Step(
            "expense report",
            resp.status_code,
            f"asks {_kind(batch)}" if _kind(batch) else _outcome(batch),
            resp.status_code < 400,
        )
    )
    if _kind(batch) == "decont_split":
        part = {
            "part_hash": hashlib.sha256(WORKINGS).hexdigest(),
            "source_doc_id": "workings",
            "kinds": ["pdf"],
            "bon_our_cui_on_doc": None,
            "counterparty_cui": None,
        }
        resp = c.post(f"/triage/{batch['batch_id']}/resume", json={"parts": [part]})
        after = _json(resp)
        kids = ", ".join(
            f"{k['source_doc_id']} emit={k['emit']}" for k in after.get("children", [])
        )
        report.steps.append(
            Step("decont_split", resp.status_code, kids or _outcome(after), resp.status_code < 400)
        )

    resp = c.post(f"/recon/{CUI}/{PERIOD}")
    recon = _json(resp)
    for _ in range(5):
        if _kind(recon) != "need_rj_export" or not export_id:
            break
        resp = c.post(f"/recon/{CUI}/{PERIOD}/resume", json={"export_id": export_id})
        recon = _json(resp)
    left = f"; left for a person: {_kind(recon)}" if _kind(recon) else ""
    report.steps.append(
        Step(
            "reconcile_sink",
            resp.status_code,
            f"settled {len(recon.get('settled', []))}{left}",
            resp.status_code < 400,
        )
    )

    # the clean month: every document is already in the books, so no question waits
    invoice = spv_invoice("AB 0070", issued="2026-08-12", due="2026-09-11", spv_id="4100000002")
    resp = _octet(c, "/ingest", invoice, {"cui": CUI, "filename": "spv-august.zip"})
    report.steps.append(
        Step("august invoice", resp.status_code, _outcome(_json(resp)), resp.status_code < 400)
    )
    resp = c.post(f"/extras/{CUI}", json=CLEAN_STATEMENT)
    out = _json(resp)
    report.steps.append(
        Step(
            "august statement",
            resp.status_code,
            "; ".join(_outcome(j) for j in out.get("jobs", [])) or _outcome(out),
            resp.status_code < 400,
        )
    )

    _approval_explanation(c, report)
    _close(c, report, PERIOD)
    _close(c, report, CLEAN)

    resp = c.get("/model-calls", params={"limit": 500})
    for call in _json(resp) if resp.status_code < 400 else []:
        if call.get("tenant_cui") not in (CUI, None):
            continue
        role = roles.get(call["role_id"], {})
        place = f"{role.get('graph_id', '?')}.{role.get('node', '?')}"
        report.calls.setdefault(place, []).append(
            {
                "role_id": call["role_id"],
                "status": call["status"],
                "model": call["model"],
                "card_hash": call["card_hash"][:12],
                "input_keys": sorted(call["input"]),
                "reason": call["reason"],
            }
        )
    return report


def render(report: Report) -> str:
    lines = [f"MODEL_CALLS={report.mode}", ""]
    for s in report.steps:
        mark = "ok " if s.ok else "ERR"
        lines.append(f"[{mark}] {s.name:<20} {s.status}  {s.outcome}")
    reasons = sorted({c["reason"] for cs in report.calls.values() for c in cs})
    lines += ["", "model calls by place (newest first):"]
    if not report.calls:
        lines.append("  none recorded (MODEL_CALLS=off records nothing)")
    for place in sorted(report.calls):
        lines.append(f"  {place}")
        for call in report.calls[place]:
            lines.append(
                f"    {call['role_id']:<22} {call['status']:<9} model={call['model']} "
                f"card={call['card_hash']} input={','.join(call['input_keys'])}"
            )
    if reasons:
        lines += ["", "reasons:"] + [f"  - {r}" for r in reasons]
    return "\n".join(lines)


def _local_client(rt: Any = None) -> Client:
    """An in-memory runtime (dry) behind the real app: the smoke run without a server."""
    from fastapi.testclient import TestClient
    from langgraph.checkpoint.memory import MemorySaver

    from poarta_contabila.agent import InMemoryAgentStore
    from poarta_contabila.app import create_app
    from poarta_contabila.catalog import load_catalog
    from poarta_contabila.jobs import InMemoryJobStore
    from poarta_contabila.packages import InMemoryBlobStore, InMemoryPackageStore
    from poarta_contabila.recon.pre import InMemoryReconStore
    from poarta_contabila.registry import InMemoryRegistry
    from poarta_contabila.runtime import build_runtime

    rt = rt or build_runtime(
        catalog=load_catalog(),
        jobs=InMemoryJobStore(),
        packages=InMemoryPackageStore(),
        blobs=InMemoryBlobStore(),
        registry=InMemoryRegistry(),
        recon=InMemoryReconStore(),
        agent_store=InMemoryAgentStore(),
        checkpointer=MemorySaver(),
        model_mode="dry",
    )
    app = create_app(None, runtime=rt, operator_token="smoke-op", agent_token="smoke-agent")
    return TestClient(app, headers={"Authorization": "Bearer smoke-op"})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="poarta_contabila.smoke", description=__doc__.split("\n")[0])
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--base-url", help="the operator API, e.g. https://….up.railway.app")
    where.add_argument("--local", action="store_true", help="in-memory runtime, MODEL_CALLS=dry")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument(
        "--ocr", action="store_true", help="also upload a synthetic statement PDF to be read"
    )
    args = ap.parse_args(argv)

    if args.local:
        client = _local_client()
    else:
        import httpx

        token = caller_token()
        if not token:
            print(f"set {' or '.join(CALLER_ENV[:2])} in the environment")
            return 2
        client = httpx.Client(
            base_url=args.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
    try:
        report = run(client, ocr=args.ocr)
    except SmokeRefused as exc:
        print(f"refused: {exc}")
        return 2
    if args.json:
        print(json.dumps({"mode": report.mode, **_asdict(report)}, indent=2, ensure_ascii=False))
    else:
        print(render(report))
    return 0 if report.ok else 1


def _asdict(report: Report) -> dict[str, Any]:
    return {"ok": report.ok, "steps": [vars(s) for s in report.steps], "calls": report.calls}


if __name__ == "__main__":
    sys.exit(main())
