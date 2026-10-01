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
        assert body["checks"] == {"catalog": "ok", "database": "ok"}
        assert client.get("/ready").status_code == 200
