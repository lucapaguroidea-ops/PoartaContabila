"""Windows agent — pull, backup label, import as AGENT, snapshot → acked."""

from __future__ import annotations

import base64
import os

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from poarta_contabila.agent import AgentService, InMemoryAgentStore, Snapshot
from poarta_contabila.app import create_app
from poarta_contabila.catalog import load_catalog
from poarta_contabila.ingest import IngestDeps, build_ingest_graph, start_payload
from poarta_contabila.jobs import InMemoryJobStore
from poarta_contabila.packages import InMemoryBlobStore, InMemoryPackageStore
from poarta_contabila.recon.pre import PreResult
from poarta_contabila.sinks.saga_xml import fixture_documents
from poarta_contabila.triage import EmitDecision, Pack
from poarta_contabila.types import CanonicalDocument

TOKEN = "agent-test-token"
CUI, FOLDER = "1000009", "0001"
LABEL = f"{CUI}:{FOLDER}:20260930T180000Z"


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


class World:
    def __init__(self, cat, *, agent_store=None):
        self.jobs = InMemoryJobStore()
        self.blobs = InMemoryBlobStore()
        self.packages = InMemoryPackageStore()
        self.deps = IngestDeps(
            catalog=cat,
            jobs=self.jobs,
            packages=self.packages,
            blobs=self.blobs,
            pre_check=lambda job, doc, **kw: PreResult(
                verdict="absent", reason="test", profile_id=None, snapshot_id="t"
            ),
            judge=lambda doc, articol: {"accounts_ok": True, "risk": "low", "needs_human": False},
            tenant_name=lambda cui: "FIRMA TEST SRL",
        )
        self.graph = build_ingest_graph(self.deps, checkpointer=MemorySaver())
        self.agent = AgentService(
            catalog=cat,
            jobs=self.jobs,
            packages=self.packages,
            blobs=self.blobs,
            store=agent_store or InMemoryAgentStore(),
            resume=lambda job_id, payload: self.graph.invoke(
                Command(resume=payload), self.cfg(job_id)
            ),
            canonical=lambda job_id: CanonicalDocument.model_validate(
                self.graph.get_state(self.cfg(job_id)).values["canonical"]
            ),
        )
        self.deps.snapshot_validated = self.agent.snapshot_validated
        self.deps.posted_doc = self.agent.posted_doc
        self.http = TestClient(create_app(None, agent=self.agent, agent_token=TOKEN))
        self.auth = {"Authorization": f"Bearer {TOKEN}"}

    @staticmethod
    def cfg(job_id):
        return {"configurable": {"thread_id": f"job:{job_id}"}}

    def packaged(self, kind="iesire", source_hash=None, period=None):
        doc = fixture_documents()[kind]
        if period:
            doc = doc.model_copy(update={"period": period})
        pack = Pack(
            tenant_cui=CUI,
            saga_firm_folder=FOLDER,
            period=doc.period,
            source_hash=source_hash or doc.source.source_hash,
            source_doc_id="ro_efactura_ubl",
            kinds=["ubl_spv"],
            our_role="outbound" if kind == "iesire" else "inbound",
            counterparty_cui=doc.partner.cui,
        )
        job = self.jobs.emit(
            pack, EmitDecision(emit=True, job_kind="job_ro_efactura", aisle="x")
        ).job
        doc = doc.model_copy(update={"job_id": job.job_id})
        self.graph.invoke(
            start_payload(job, doc, source_doc_id="ro_efactura_ubl"), self.cfg(job.job_id)
        )
        out = self.graph.invoke(
            Command(resume={"decision": "approve", "edit": None}), self.cfg(job.job_id)
        )
        assert out["status"] == "packaged"
        return job.job_id, doc

    def question(self, job_id):
        tasks = self.graph.get_state(self.cfg(job_id)).tasks
        return tasks[0].interrupts[0].value if tasks and tasks[0].interrupts else None

    def status(self, job_id):
        return self.jobs.get(job_id).status

    def post(self, path, body):
        return self.http.post(path, json=body, headers=self.auth)

    def import_all(self, label=LABEL):
        keys = [
            i["export_key"]
            for b in self.http.get("/agent/pull", headers=self.auth).json()["batches"]
            for i in b["items"]
        ]
        return self.post(
            "/agent/imported",
            {
                "cui": CUI,
                "folder": FOLDER,
                "backup_label": label,
                "results": [{"export_key": k, "ok": True} for k in keys],
            },
        ).json()

    def snapshot(self, docs, closed=(), taken_at="2026-10-01T09:00:00Z"):
        return self.post(
            "/agent/snapshot",
            {
                "cui": CUI,
                "folder": FOLDER,
                "taken_at": taken_at,
                "closed_periods": list(closed),
                "documents": docs,
            },
        ).json()


def _sdoc(doc, key="SAGA-IES-1", validated=True, **over):
    return {
        "saga_doc_key": key,
        "doc_class": doc.doc_class,
        "number": doc.number,
        "date": doc.date,
        "gross": doc.totals.gross,
        "validated": validated,
        **over,
    }


# ----- auth -----


def test_agent_routes_need_the_agent_token(cat):
    w = World(cat)
    assert w.http.get("/agent/pull").status_code == 401
    assert w.http.get("/agent/pull", headers={"Authorization": "Bearer grok"}).status_code == 401
    shut = TestClient(create_app(None, agent=w.agent, agent_token=None))
    assert shut.get("/agent/pull", headers=w.auth).status_code == 503
    unwired = TestClient(create_app(None, agent=None, agent_token=TOKEN))
    assert unwired.get("/agent/pull", headers=w.auth).status_code == 503


# ----- pull / backup / import -----


def test_pull_hands_out_the_package_with_its_backup_rule(cat):
    w = World(cat)
    job_id, _ = w.packaged()
    batches = w.http.get("/agent/pull", headers=w.auth).json()["batches"]
    assert len(batches) == 1 and batches[0]["backup"] == "before_batch"
    item = batches[0]["items"][0]
    assert item["job_id"] == job_id and item["saga_path"] == "import_xml"
    assert b"<FacturaNumar>FX-101</FacturaNumar>" in base64.b64decode(item["content_b64"])


def test_import_without_an_acknowledged_backup_is_refused(cat):
    w = World(cat)
    job_id, _ = w.packaged()
    out = w.import_all()
    assert out[0]["ok"] is False and "backup" in out[0]["message"]
    assert w.status(job_id) == "packaged"


def test_backup_label_must_name_this_firm(cat):
    w = World(cat)
    bad = w.post(
        "/agent/ack-backup",
        {"label": f"20000005:{FOLDER}:20260930T180000Z", "cui": CUI, "folder": FOLDER},
    )
    assert bad.status_code == 422 and "another firm" in bad.json()["detail"]
    assert (
        w.post("/agent/ack-backup", {"label": "nope", "cui": CUI, "folder": FOLDER}).status_code
        == 422
    )
    assert (
        w.post("/agent/ack-backup", {"label": LABEL, "cui": CUI, "folder": FOLDER}).status_code
        == 200
    )


def test_import_moves_to_wait_validare_once(cat):
    w = World(cat)
    job_id, _ = w.packaged()
    w.post("/agent/ack-backup", {"label": LABEL, "cui": CUI, "folder": FOLDER})
    assert w.import_all()[0]["message"] == "wait_validare"
    assert w.status(job_id) == "wait_validare"
    assert w.jobs.get(job_id).saga["backup_label"] == LABEL
    assert w.http.get("/agent/pull", headers=w.auth).json()["batches"] == []
    key = next(iter(w.packages.rows))
    again = w.post(
        "/agent/imported",
        {
            "cui": CUI,
            "folder": FOLDER,
            "backup_label": LABEL,
            "results": [{"export_key": key, "ok": True}],
        },
    ).json()
    assert again[0] == {"export_key": key, "ok": True, "message": "wait_validare"}


def test_failed_import_goes_to_a_person(cat):
    w = World(cat)
    job_id, _ = w.packaged()
    w.post("/agent/ack-backup", {"label": LABEL, "cui": CUI, "folder": FOLDER})
    key = next(iter(w.packages.rows))
    w.post(
        "/agent/imported",
        {
            "cui": CUI,
            "folder": FOLDER,
            "backup_label": LABEL,
            "results": [{"export_key": key, "ok": False, "message": "CIF lipsa"}],
        },
    )
    assert w.status(job_id) == "needs_human" and "CIF lipsa" in w.jobs.get(job_id).error


def test_import_for_another_firm_folder_is_refused(cat):
    w = World(cat)
    job_id, _ = w.packaged()
    key = next(iter(w.packages.rows))
    out = w.post(
        "/agent/imported",
        {
            "cui": CUI,
            "folder": "0002",
            "backup_label": LABEL,
            "results": [{"export_key": key, "ok": True}],
        },
    ).json()
    assert out[0]["ok"] is False and w.status(job_id) == "packaged"


def test_closed_month_gets_nothing(cat):
    w = World(cat)
    job_id, _ = w.packaged()
    w.snapshot([], closed=["2026-09"])
    pulled = w.http.get("/agent/pull", headers=w.auth).json()
    assert pulled["batches"] == [] and pulled["held"][0]["job_id"] == job_id


def test_run_size_follows_the_module(cat):
    small = load_catalog()
    small.write_modules["iesire_factura_xml"] = small.write_modules[
        "iesire_factura_xml"
    ].model_copy(update={"max_docs_per_run": 1})
    w = World(small)
    w.packaged(source_hash="1" * 64)
    w.packaged(source_hash="2" * 64)
    pulled = w.http.get("/agent/pull", headers=w.auth).json()
    assert len(pulled["batches"][0]["items"]) == 1 and "run is full" in pulled["held"][0]["reason"]


# ----- wait_validare / snapshot -----


def _imported(cat):
    w = World(cat)
    job_id, doc = w.packaged()
    w.post("/agent/ack-backup", {"label": LABEL, "cui": CUI, "folder": FOLDER})
    w.import_all()
    return w, job_id, doc


def test_wait_validare_without_snapshot_is_not_acked(cat):
    w, job_id, _ = _imported(cat)
    w.graph.invoke(Command(resume={"validated": True, "saga_doc_key": "SAGA-IES-1"}), w.cfg(job_id))
    q = w.question(job_id)
    assert q["kind"] == "wait_validare" and "no SAGA snapshot" in q["error"]
    assert w.status(job_id) == "wait_validare"


def test_ack_needs_the_saga_key(cat):
    w, job_id, doc = _imported(cat)
    w.snapshot([_sdoc(doc)])
    w2, job2, _ = _imported(cat)  # a fresh thread: answer without a key
    w2.graph.invoke(Command(resume={"validated": True, "saga_doc_key": None}), w2.cfg(job2))
    assert "saga_doc_key" in w2.question(job2)["error"]


def test_snapshot_not_yet_validated_keeps_waiting(cat):
    w, job_id, doc = _imported(cat)
    out = w.snapshot([_sdoc(doc, validated=False)])
    assert out["waiting"] == [job_id] and w.status(job_id) == "wait_validare"


def test_validated_snapshot_acks_the_job(cat):
    w, job_id, doc = _imported(cat)
    out = w.snapshot([_sdoc(doc, number="fx 101")])  # typed differently in SAGA
    assert out["acked"] == [job_id]
    assert w.status(job_id) == "acked" and w.jobs.get(job_id).saga["saga_doc_key"] == "SAGA-IES-1"


def test_snapshot_with_other_amount_does_not_ack(cat):
    w, job_id, doc = _imported(cat)
    out = w.snapshot([_sdoc(doc, gross="182.12")])
    assert out["unmatched"] == [job_id] and w.status(job_id) == "wait_validare"


def test_agent_cannot_devalidate(cat):
    w, job_id, doc = _imported(cat)
    w.snapshot([_sdoc(doc)])
    later = w.snapshot([_sdoc(doc, key="OTHER", number="X-1")], taken_at="2026-10-02T09:00:00Z")
    assert later["acked_not_shown"] == [job_id]  # reported only
    assert w.status(job_id) == "acked"
    paths = {p for p in w.http.get("/openapi.json").json()["paths"] if p.startswith("/agent")}
    assert paths == {"/agent/pull", "/agent/ack-backup", "/agent/imported", "/agent/snapshot"}


def test_cancelled_import_reopens(cat):
    w, job_id, _ = _imported(cat)
    w.graph.invoke(Command(resume={"validated": False, "saga_doc_key": None}), w.cfg(job_id))
    assert w.status(job_id) == "reopened"


def test_postgres_agent_store(cat):
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    from datetime import UTC, datetime

    from poarta_contabila.agent import PostgresAgentStore
    from poarta_contabila.jobs import PostgresJobStore

    PostgresJobStore(dsn, reset=True)  # applies the schema
    store = PostgresAgentStore(dsn)
    store.ack_backup(LABEL, CUI, FOLDER, datetime(2026, 9, 30, 18, tzinfo=UTC))
    store.ack_backup(LABEL, CUI, FOLDER, datetime(2026, 9, 30, 18, tzinfo=UTC))
    assert store.has_backup(LABEL, CUI, FOLDER) and not store.has_backup(LABEL, CUI, "0002")
    old = Snapshot(cui=CUI, folder=FOLDER, taken_at="2026-10-01T09:00:00Z")
    new = old.model_copy(update={"taken_at": "2026-10-02T09:00:00Z", "closed_periods": ["2026-08"]})
    store.add_snapshot("b", new)
    store.add_snapshot("a", old)
    assert store.latest_snapshot(CUI).closed_periods == ["2026-08"]
    assert store.latest_snapshot("20000005") is None


def test_a_bank_line_matches_saga_under_the_reference_it_was_imported_with():
    """The scenario runner found it: a bank line goes into SAGA numbered with the bank's reference
    (render_bank_line's Numar), so the snapshot shows that number, not EXT-…."""
    from poarta_contabila.agent import SnapshotDoc, _matches
    from poarta_contabila.types import Line, PartnerRef, SourceRef, TenantRef, Totals

    line = CanonicalDocument(
        job_id="j",
        tenant=TenantRef(cui="1001012", saga_firm_folder="0001"),
        period="2026-05",
        doc_class="plata",
        number="EXT-abcdef12-1",
        date="2026-05-20",
        partner=PartnerRef(cui="20010114", name="FURNIZOR ALFA SRL", role="supplier"),
        totals=Totals(net="121.00", vat="0.00", gross="121.00"),
        lines=[Line(desc="Plata", net="121.00", vat_rate="0", vat="0.00", gross="121.00")],
        source=SourceRef(
            kind="pdf", bucket_key="k", content_type="application/pdf", source_hash="0" * 64
        ),
        maps={"iban": "RO00AAAA", "referinta": "OP260504"},
    )
    shown = SnapshotDoc(
        saga_doc_key="saga:Banca:OP260504:2026-05-20:plata",
        doc_class="plata",
        number="OP260504",
        date="2026-05-20",
        gross="121.00",
        validated=True,
    )
    assert _matches(line, shown)
    assert not _matches(line, shown.model_copy(update={"number": "OP260505"}))
    no_ref = line.model_copy(update={"maps": {"iban": "RO00AAAA"}})
    assert _matches(no_ref, shown.model_copy(update={"number": "EXT-abcdef12-1"}))
