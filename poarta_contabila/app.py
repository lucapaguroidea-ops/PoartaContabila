"""HTTP entry point (ARCHITECTURE §10): health, readiness, schema on boot, agent and
operator routes over the wired runtime (``runtime.py``).

The catalog is law: if it does not load, the process does not start.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from poarta_contabila.agent import AgentService
from poarta_contabila.agent_api import agent_router
from poarta_contabila.catalog import load_catalog
from poarta_contabila.db import schema_sql
from poarta_contabila.operator_api import operator_router


def _database_url_from_env() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def create_app(
    database_url: str | None | object = ...,
    *,
    agent: AgentService | None = None,
    agent_token: str | None | object = ...,
    runtime: Any = ...,
    operator_token: str | None | object = ...,
) -> FastAPI:
    """Build the app. *database_url* defaults to ``$DATABASE_URL``; ``None`` disables the DB.

    *runtime* defaults to the production one built at startup from ``DATABASE_URL`` and
    ``S3_*`` (None if either is missing; the agent and operator routes then answer 503).
    *agent* overrides the runtime's agent service (tests). Tokens default to
    ``$AGENT_SHARED_TOKEN`` and ``$OPERATOR_TOKEN``.
    """
    token = os.environ.get("AGENT_SHARED_TOKEN") if agent_token is ... else agent_token
    op_token = os.environ.get("OPERATOR_TOKEN") if operator_token is ... else operator_token
    dsn = _database_url_from_env() if database_url is ... else database_url

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.catalog = load_catalog()
        if dsn:
            import psycopg

            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(schema_sql())
        if runtime is ...:
            from poarta_contabila.runtime import runtime_from_env

            app.state.runtime, app.state.runtime_reason = runtime_from_env(app.state.catalog, dsn)
        yield

    app = FastAPI(title="Poarta Primară", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> JSONResponse:
        checks = {"catalog": "ok" if getattr(app.state, "catalog", None) else "not loaded"}
        checks["runtime"] = (
            "ok" if current_runtime() else getattr(app.state, "runtime_reason", "not wired")
        )
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
        ok = all(v == "ok" for k, v in checks.items() if k != "runtime")
        return JSONResponse({"checks": checks}, status_code=200 if ok else 503)

    def current_runtime():
        return runtime if runtime is not ... else getattr(app.state, "runtime", None)

    def current_agent():
        if agent is not None:
            return agent
        rt = current_runtime()
        return rt.agent if rt is not None else None

    app.include_router(agent_router(current_agent, lambda: token or None))
    app.include_router(
        operator_router(current_runtime, lambda: op_token or None, lambda: token or None)
    )
    return app


app = create_app()
