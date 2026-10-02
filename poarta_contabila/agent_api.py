"""Agent routes (ARCHITECTURE §10). Bearer ``GRAPHUSERTOKEN_AGENT_SHARED`` (old name
``AGENT_SHARED_TOKEN``); no other token opens them.

No token configured, or no agent runtime wired → 503: the gate stays shut.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException

from poarta_contabila.agent import (
    AgentError,
    AgentService,
    BackupAck,
    ImportedReport,
    ImportResult,
    PullResponse,
    Snapshot,
    SnapshotResult,
)


def agent_router(
    service: Callable[[], AgentService | None], token: Callable[[], str | None]
) -> APIRouter:
    """Routes for the Windows agent. *service* and *token* are read per request."""

    def agent(authorization: str | None = Header(default=None)) -> AgentService:
        expected = token()
        svc = service()
        if not expected or svc is None:
            raise HTTPException(503, "agent API not configured")
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given.encode(), expected.encode()):
            raise HTTPException(401, "agent token required")
        return svc

    router = APIRouter(prefix="/agent", tags=["agent"])

    @router.get("/pull")
    def pull(svc: AgentService = Depends(agent)) -> PullResponse:
        return svc.pull()

    @router.post("/ack-backup")
    def ack_backup(body: BackupAck, svc: AgentService = Depends(agent)) -> dict[str, str]:
        try:
            svc.ack_backup(body)
        except AgentError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"label": body.label}

    @router.post("/imported")
    def imported(body: ImportedReport, svc: AgentService = Depends(agent)) -> list[ImportResult]:
        return svc.imported(body)

    @router.post("/snapshot")
    def snapshot(body: Snapshot, svc: AgentService = Depends(agent)) -> SnapshotResult:
        return svc.snapshot(body)

    return router
