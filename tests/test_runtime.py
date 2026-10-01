"""Runtime wiring: operator → ingest (XML first) → PRE → approve → package → agent → acked."""

from __future__ import annotations

import base64
import io
import os
import zipfile
from pathlib import Path

import pytest
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
from poarta_contabila.storage import S3BlobStore, S3Config

ROOT = Path(__file__).resolve().parents[1]
INVOICE = (ROOT / "fixtures/ubl/invoice_inbound.xml").read_bytes()
SIGNATURE = (ROOT / "fixtures/ubl/semnatura.xml").read_bytes()
SAGA_RJ = (ROOT / "fixtures/sink/saga_rj.xls").read_bytes()
CUI, FOLDER = "1000009", "0001"
OP, AG = "operator-token", "agent-token"


def _spv_zip(xml: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("4100000001.xml", xml)
        zf.writestr("semnatura_4100000001.xml", SIGNATURE)
    return buf.getvalue()


NEW_INVOICE = _spv_zip(INVOICE.replace(b"<cbc:ID>AB 0058</cbc:ID>", b"<cbc:ID>AB 0099</cbc:ID>"))


@pytest.fixture(scope="module")
def cat():
    return load_catalog()


def _runtime(cat, **over):
    parts = dict(
        catalog=cat,
        jobs=InMemoryJobStore(),
        packages=InMemoryPackageStore(),
        blobs=InMemoryBlobStore(),
        registry=InMemoryRegistry(),
        recon=InMemoryReconStore(),
        agent_store=InMemoryAgentStore(),
        checkpointer=MemorySaver(),
    )
    parts.update(over)
    return build_runtime(**parts)


class Ops:
    def __init__(self, rt, op=OP, ag=AG):
        self.rt = rt
        self.http = TestClient(create_app(None, runtime=rt, operator_token=op, agent_token=ag))
        self.op = {"Authorization": f"Bearer {OP}"}
        self.ag = {"Authorization": f"Bearer {AG}"}

    def tenant(self):
        body = {"cui": CUI, "name": "FIRMA TEST SRL", "saga_firm_folder": FOLDER}
        return self.http.put(f"/tenants/{CUI}", json=body, headers=self.op)

    def upload_rj(self, data=SAGA_RJ, cui=CUI):
        return self.http.post(
            f"/tenants/{cui}/exports/rj",
            params={"filename": "rj.xls", "product": "saga"},
            content=data,
            headers={**self.op, "Content-Type": "application/octet-stream"},
        )

    def ingest(self, data=NEW_INVOICE, filename="spv.zip"):
        return self.http.post(
            "/ingest",
            params={"cui": CUI, "filename": filename},
            content=data,
            headers={**self.op, "Content-Type": "application/octet-stream"},
        )

    def resume(self, job_id, body):
        return self.http.post(f"/jobs/{job_id}/resume", json=body, headers=self.op).json()


def test_tokens_are_separate_and_required(cat):
    o = Ops(_runtime(cat))
    assert o.http.get("/jobs/x", headers=o.ag).status_code == 401  # agent token: no
    same = Ops(_runtime(cat), op=AG, ag=AG)
    assert same.http.get("/jobs/x", headers=same.ag).status_code == 503
    unwired = TestClient(create_app(None, runtime=None, operator_token=OP, agent_token=AG))
    assert unwired.get("/jobs/x", headers=o.op).status_code == 503
    assert unwired.get("/agent/pull", headers=o.ag).status_code == 503


def test_export_of_another_firm_is_refused(cat):
    o = Ops(_runtime(cat))
    assert o.upload_rj().status_code == 422  # tenant not registered yet
    o.tenant()
    assert (
        o.http.put(
            "/tenants/20000005",
            json={"cui": CUI, "name": "x", "saga_firm_folder": "1"},
            headers=o.op,
        ).status_code
        == 422
    )
    o.http.put(
        "/tenants/20000005",
        json={"cui": "20000005", "name": "ALTA", "saga_firm_folder": "2"},
        headers=o.op,
    )
    bad = o.upload_rj(cui="20000005")
    assert bad.status_code == 422 and "names firm 1000009" in bad.json()["detail"]
    good = o.upload_rj().json()
    assert good["periods"] == ["2026-09"] and good["kind"] == "rj"


def test_ingest_refuses_what_is_not_xml_or_not_ours(cat):
    o = Ops(_runtime(cat))
    assert o.ingest().status_code == 422  # unknown tenant
    o.tenant()
    assert "XML first" in o.ingest(b"%PDF-1.4", "f.pdf").json()["detail"]
    other = INVOICE.replace(b"RO1000009", b"RO40000000")
    assert "neither" in o.ingest(other, "f.xml").json()["detail"]


def test_without_books_the_job_waits_for_an_export(cat):
    o = Ops(_runtime(cat))
    o.tenant()
    out = o.ingest().json()
    assert out["created"] and out["job"]["status"] == "needs_human"
    assert "need_rj_export" in out["job"]["error"]


def test_already_in_the_books_is_not_packaged(cat):
    o = Ops(_runtime(cat))
    o.tenant()
    o.upload_rj()
    # same number as the journal fixture (AB0058, 2026-09-10) but another gross → a person looks
    out = o.ingest(_spv_zip(INVOICE)).json()
    assert out["job"]["status"] == "needs_human" and "close" in out["job"]["error"]
    assert o.rt.blobs.puts == 2  # export + source; no package


def test_full_loop_to_acked(cat):
    rt = _runtime(cat)
    o = Ops(rt)
    o.tenant()
    o.upload_rj()
    out = o.ingest().json()
    job_id = out["job"]["job_id"]
    assert out["question"]["kind"] == "v3_approve"  # no judge wired: always asked
    assert out["question"]["judge"]["judge"] == "not wired"
    again = o.ingest().json()
    assert again["created"] is False and again["job"]["job_id"] == job_id

    view = o.resume(job_id, {"decision": "approve", "edit": None})
    assert view["job"]["status"] == "packaged" and view["question"]["kind"] == "wait_validare"

    batch = o.http.get("/agent/pull", headers=o.ag).json()["batches"][0]
    xml = base64.b64decode(batch["items"][0]["content_b64"])
    assert b"<ClientNume>FIRMA TEST SRL</ClientNume>" in xml  # tenant name from the registry
    label = f"{CUI}:{FOLDER}:20261001T080000Z"
    o.http.post(
        "/agent/ack-backup", json={"label": label, "cui": CUI, "folder": FOLDER}, headers=o.ag
    )
    o.http.post(
        "/agent/imported",
        headers=o.ag,
        json={
            "cui": CUI,
            "folder": FOLDER,
            "backup_label": label,
            "results": [{"export_key": batch["items"][0]["export_key"], "ok": True}],
        },
    )
    snap = o.http.post(
        "/agent/snapshot",
        headers=o.ag,
        json={
            "cui": CUI,
            "folder": FOLDER,
            "taken_at": "2026-10-01T09:00:00Z",
            "documents": [
                {
                    "saga_doc_key": "INT-77",
                    "doc_class": "intrare",
                    "number": "AB0099",
                    "date": "2026-09-10",
                    "gross": "807.81",
                    "validated": True,
                }
            ],
        },
    ).json()
    assert snap["acked"] == [job_id]
    final = o.http.get(f"/jobs/{job_id}", headers=o.op).json()
    assert final["job"]["status"] == "acked" and final["question"] is None


def test_s3_blob_store_uses_the_bucket():
    class Client:
        def __init__(self):
            self.objects = {}

        def put_object(self, Bucket, Key, Body):  # noqa: N803
            self.objects[(Bucket, Key)] = Body

        def get_object(self, Bucket, Key):  # noqa: N803
            return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}

    store = S3BlobStore(S3Config("https://s3.test", "k", "s", "poarta"), client=Client())
    store.put("tenants/1000009/x.xml", b"<x/>")
    assert store.get("tenants/1000009/x.xml") == b"<x/>"


def test_s3_config_needs_every_variable(monkeypatch):
    for k in ("S3_ENDPOINT", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_BUCKET"):
        monkeypatch.setenv(k, "v")
    assert S3Config.from_env() is not None
    monkeypatch.delenv("S3_BUCKET")
    assert S3Config.from_env() is None


def test_postgres_runtime_survives_a_restart(cat):
    dsn = os.environ.get("POARTA_TEST_DSN")
    if not dsn:
        pytest.skip("set POARTA_TEST_DSN to a scratch Postgres")
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    from poarta_contabila.agent import PostgresAgentStore
    from poarta_contabila.jobs import PostgresJobStore
    from poarta_contabila.packages import PostgresPackageStore
    from poarta_contabila.recon.pre import PostgresReconStore
    from poarta_contabila.registry import PostgresRegistry

    PostgresJobStore(dsn, reset=True)
    blobs = InMemoryBlobStore()  # the bucket outlives the process too

    def boot():
        pool = ConnectionPool(
            dsn,
            kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            open=True,
        )
        saver = PostgresSaver(pool)
        saver.setup()
        rt = build_runtime(
            catalog=cat,
            jobs=PostgresJobStore(dsn),
            packages=PostgresPackageStore(dsn),
            blobs=blobs,
            registry=PostgresRegistry(dsn),
            recon=PostgresReconStore(dsn),
            agent_store=PostgresAgentStore(dsn),
            checkpointer=saver,
        )
        return rt, pool

    first, pool = boot()
    o = Ops(first)
    o.tenant()
    o.upload_rj()
    job_id = o.ingest().json()["job"]["job_id"]
    pool.close()

    second, pool = boot()  # a new process: same database, same bucket
    o2 = Ops(second)
    assert o2.http.get(f"/jobs/{job_id}", headers=o2.op).json()["question"]["kind"] == "v3_approve"
    view = o2.resume(job_id, {"decision": "approve", "edit": None})
    assert view["job"]["status"] == "packaged"
    pool.close()
