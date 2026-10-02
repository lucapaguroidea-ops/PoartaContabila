"""HTTP entry point (ARCHITECTURE §10): health, readiness, schema on boot, agent and
operator routes over the wired runtime (``runtime.py``).

The catalog is law: if it does not load, the process does not start.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from poarta_contabila.agent import AgentService
from poarta_contabila.agent_api import agent_router
from poarta_contabila.catalog import load_catalog
from poarta_contabila.db import schema_sql
from poarta_contabila.operator_api import operator_router


def _database_url_from_env() -> str | None:
    return os.environ.get("DATABASE_URL") or None


MAX_UPLOAD_MB = 32  # default request-body cap (WP-34); base64 adds a third, so ~24 MB files
TOKEN_MIN_CHARS = 32


def _max_upload_bytes() -> int:
    try:
        mb = int(os.environ.get("MAX_UPLOAD_MB", MAX_UPLOAD_MB))
    except ValueError:
        mb = MAX_UPLOAD_MB
    return max(1, mb) * 1024 * 1024


class BodyLimit:
    """Refuse a request body over *max_bytes* with 413 before any route runs (WP-34).

    A declared Content-Length over the cap is refused at once. Otherwise the body is read in
    full first (routes read it whole anyway) and refused as soon as it passes the cap, so no
    route ever sees part of a body.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope.get("headers") or []).get(b"content-length", b"")
        if length.isdigit() and int(length) > self.max_bytes:
            await self._refuse(scope, receive, send)
            return
        chunks: list[bytes] = []
        seen = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":  # the client went away
                return
            chunk = message.get("body", b"")
            seen += len(chunk)
            if seen > self.max_bytes:
                await self._refuse(scope, receive, send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        body = b"".join(chunks)
        sent = False

        async def replay() -> dict:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()  # after the body: wait for a disconnect, as usual

        await self.app(scope, replay, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        mb = self.max_bytes // (1024 * 1024)
        body = JSONResponse({"detail": f"request body over {mb} MB (MAX_UPLOAD_MB)"}, 413)
        await body(scope, receive, send)


# WP-38: the owner's variable names (2026-10-02); the old names are read only when the new
# one is unset, so a service still on the old names keeps working.
OPERATOR_ENV = ("GRAPHUSERTOKEN_OPERATOR", "OPERATOR_TOKEN")
AGENT_ENV = ("GRAPHUSERTOKEN_AGENT_SHARED", "AGENT_SHARED_TOKEN")
SYSBUILDER_ENV = ("GRAPHUSERTOKEN_CLAUDE_SYSBUILDER",)


def env_token(names: tuple[str, ...]) -> str | None:
    """The first of *names* that is set and not blank."""
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def token_check(value: str | None, *others: str | None) -> str:
    """How a bearer token looks, never what it is."""
    if not value:
        return "unset"
    if any(other and value == other for other in others):
        return "same as another token"
    if len(value) < TOKEN_MIN_CHARS:
        return f"shorter than {TOKEN_MIN_CHARS} characters"
    return "ok"


log = logging.getLogger(__name__)


async def _retry_parked_reads(runtime: Callable[[], Any]) -> None:
    """WP-42: every ``READING_RETRY_SECONDS`` (default 60; 0 = off), read again the parked
    statements whose time has come, so a statement waiting for model quota never stalls."""
    every = float(os.environ.get("READING_RETRY_SECONDS", "60") or 0)
    if every <= 0:
        return
    while True:
        await asyncio.sleep(every)
        rt = runtime()
        if rt is None or rt.gemini_reader is None:
            continue
        try:
            await asyncio.to_thread(rt.retry_waiting)
        except Exception:  # a failed round is logged; the next one tries again
            log.exception("retrying parked statement reads failed")


def create_app(
    database_url: str | None | object = ...,
    *,
    agent: AgentService | None = None,
    agent_token: str | None | object = ...,
    runtime: Any = ...,
    operator_token: str | None | object = ...,
    sysbuilder_token: str | None | object = ...,
) -> FastAPI:
    """Build the app. *database_url* defaults to ``$DATABASE_URL``; ``None`` disables the DB.

    *runtime* defaults to the production one built at startup from ``DATABASE_URL`` and
    ``S3_*`` (None if either is missing; the agent and operator routes then answer 503).
    *agent* overrides the runtime's agent service (tests). Tokens default to
    ``$GRAPHUSERTOKEN_AGENT_SHARED``, ``$GRAPHUSERTOKEN_OPERATOR`` (each falling back to its
    old name) and ``$GRAPHUSERTOKEN_CLAUDE_SYSBUILDER`` (the build agent: synthetic tenants
    only, WP-38).
    """
    token = env_token(AGENT_ENV) if agent_token is ... else agent_token
    op_token = env_token(OPERATOR_ENV) if operator_token is ... else operator_token
    builder = env_token(SYSBUILDER_ENV) if sysbuilder_token is ... else sysbuilder_token
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
        retry = asyncio.create_task(_retry_parked_reads(current_runtime))
        yield
        retry.cancel()

    app = FastAPI(title="Poarta Primară", version="0.1.0", lifespan=lifespan)
    app.add_middleware(BodyLimit, max_bytes=_max_upload_bytes())

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
        # reported, not gating: a weak token is the owner's to rotate (WP-34)
        checks["operator_token"] = token_check(op_token, token, builder)
        checks["agent_token"] = token_check(token, op_token, builder)
        checks["sysbuilder_token"] = token_check(builder, op_token, token)
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
        operator_router(
            current_runtime,
            lambda: op_token or None,
            lambda: token or None,
            lambda: builder or None,
        )
    )
    return app


app = create_app()
