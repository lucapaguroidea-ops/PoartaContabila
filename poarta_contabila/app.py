"""HTTP entry point (ARCHITECTURE §10): health, readiness, schema on boot, agent routes.

The catalog is law: if it does not load, the process does not start.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from poarta_contabila.agent import AgentService
from poarta_contabila.agent_api import agent_router
from poarta_contabila.catalog import load_catalog
from poarta_contabila.db import schema_sql


def _database_url_from_env() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def create_app(
    database_url: str | None | object = ...,
    *,
    agent: AgentService | None = None,
    agent_token: str | None | object = ...,
) -> FastAPI:
    """Build the app. *database_url* defaults to ``$DATABASE_URL``; ``None`` disables the DB.

    *agent* is the wired agent runtime (stores, bucket, ingest graph). Until the
    production runtime is wired, the agent routes answer 503. *agent_token* defaults
    to ``$AGENT_SHARED_TOKEN``.
    """
    token = os.environ.get("AGENT_SHARED_TOKEN") if agent_token is ... else agent_token
    dsn = _database_url_from_env() if database_url is ... else database_url

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.catalog = load_catalog()
        if dsn:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(schema_sql())
        yield

    app = FastAPI(title="Poarta Primară", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        checks = {"catalog": "ok" if getattr(app.state, "catalog", None) else "not loaded"}
        if not dsn:
            checks["database"] = "not configured"
        else:
            try:
                import psycopg

                with psycopg.connect(dsn, connect_timeout=5) as conn:
                    conn.execute("SELECT 1 FROM domain.jobs LIMIT 1")
                checks["database"] = "ok"
            except Exception as exc:  # report, do not crash the probe
                checks["database"] = f"error: {type(exc).__name__}"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"checks": checks}, status_code=200 if ok else 503)

    app.include_router(agent_router(lambda: agent, lambda: token or None))
    return app


app = create_app()
