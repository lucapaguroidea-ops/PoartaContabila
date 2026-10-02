"""Deployable shell: the app refuses to start on a broken catalog and reports readiness."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from poarta_contabila.app import create_app
from poarta_contabila.catalog import CatalogError

PACK = Path(__file__).resolve().parents[1] / "catalog"


def test_health_without_database():
    with TestClient(create_app(database_url=None)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        ready = client.get("/ready")
        assert ready.status_code == 503
        assert ready.json()["checks"]["catalog"] == "ok"
        assert ready.json()["checks"]["database"] == "not configured"


def test_broken_catalog_refuses_to_start(tmp_path, monkeypatch):
    dst = tmp_path / "catalog"
    shutil.copytree(PACK, dst)
    (dst / "30_cale/ARTICOLE_GRAPH_v1.yaml").write_text("graphs: [\n")
    monkeypatch.setenv("POARTA_CATALOG_DIR", str(dst))
    with pytest.raises(CatalogError):
        with TestClient(create_app(database_url=None)):
            pass


@pytest.mark.skipif(not os.environ.get("POARTA_TEST_DSN"), reason="needs POARTA_TEST_DSN")
def test_ready_with_database_applies_schema():
    with TestClient(create_app(database_url=os.environ["POARTA_TEST_DSN"])) as client:
        body = client.get("/ready").json()
        assert (body["checks"]["catalog"], body["checks"]["database"]) == ("ok", "ok")
        assert "S3_" in body["checks"]["runtime"]  # not wired here: reported, not fatal
        assert client.get("/ready").status_code == 200


# ----- WP-34: request-size cap and token report -----


def test_tokens_are_reported_never_shown():
    from poarta_contabila.app import token_check

    weak, strong = "short-token", "s" * 40
    app = create_app(database_url=None, operator_token=weak, agent_token=strong, runtime=None)
    with TestClient(app) as client:
        resp = client.get("/ready")
        checks = resp.json()["checks"]
        assert checks["operator_token"] == "shorter than 32 characters"
        assert checks["agent_token"] == "ok"
        assert weak not in resp.text and strong not in resp.text
    assert token_check(None) == "unset"
    assert token_check(strong, strong) == "same as the other token"


def test_a_body_over_the_cap_is_refused_with_413(monkeypatch):
    from tests.test_runtime import Ops, _runtime

    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    from poarta_contabila.catalog import load_catalog

    o = Ops(_runtime(load_catalog()))
    o.tenant()
    big = b"x" * (1024 * 1024 + 1)
    resp = o.ingest(big, "big.xml")
    assert resp.status_code == 413 and "MAX_UPLOAD_MB" in resp.json()["detail"]

    def chunks():  # no Content-Length: counted as it streams in
        for _ in range(3):
            yield b"y" * (512 * 1024)

    streamed = o.http.post(
        "/ingest",
        params={"cui": "1000009", "filename": "s.xml"},
        content=chunks(),
        headers={**o.op, "Content-Type": "application/octet-stream"},
    )
    assert streamed.status_code == 413
    assert o.ingest(b"%PDF-1.4", "f.pdf").status_code == 422  # small bodies go through
    assert o.rt.jobs.jobs == {}
