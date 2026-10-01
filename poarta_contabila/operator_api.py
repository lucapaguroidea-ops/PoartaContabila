"""Operator routes (ARCHITECTURE §10): register tenants, upload witnesses, ingest, answer.

Bearer ``OPERATOR_TOKEN``. It must differ from the agent token: the agent imports, a
person answers questions. Unset, equal to the agent token, or no runtime → 503.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query

from poarta_contabila.registry import ExportKind, Product, Tenant
from poarta_contabila.runtime import IngestRefused, Runtime
from poarta_contabila.sinks.exports import ExportError

_RAW = Body(..., media_type="application/octet-stream")


def operator_router(
    runtime: Callable[[], Runtime | None],
    token: Callable[[], str | None],
    agent_token: Callable[[], str | None],
) -> APIRouter:
    def operator(authorization: str | None = Header(default=None)) -> Runtime:
        expected, rt = token(), runtime()
        if not expected or rt is None or expected == agent_token():
            raise HTTPException(503, "operator API not configured")
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given.encode(), expected.encode()):
            raise HTTPException(401, "operator token required")
        return rt

    router = APIRouter(tags=["operator"])

    @router.put("/tenants/{cui}")
    def put_tenant(cui: str, body: Tenant, rt: Runtime = Depends(operator)) -> Tenant:
        if body.cui != cui:
            raise HTTPException(422, "body cui differs from the path")
        rt.registry.put_tenant(body)
        return body

    @router.post("/tenants/{cui}/exports/{kind}")
    def put_export(
        cui: str,
        kind: ExportKind,
        filename: str = Query(...),
        product: Product | None = Query(default=None),
        periods: str | None = Query(default=None, description="comma-separated YYYY-MM"),
        data: bytes = _RAW,
        rt: Runtime = Depends(operator),
    ) -> dict[str, Any]:
        try:
            months = [p.strip() for p in periods.split(",")] if periods else None
            return rt.put_export(cui, kind, product, data, filename, months)
        except (ExportError, IngestRefused, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/ingest")
    def ingest(
        cui: str = Query(...),
        filename: str = Query(...),
        data: bytes = _RAW,
        rt: Runtime = Depends(operator),
    ) -> dict[str, Any]:
        try:
            return rt.ingest_upload(cui, data, filename)
        except IngestRefused as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/periods/{cui}/{period}/diff")
    def period_diff(
        cui: str,
        period: str,
        tva: str | None = Query(default=None, description="CO.DiT axis tva until WP-11"),
        exig: str | None = Query(default=None),
        rt: Runtime = Depends(operator),
    ) -> dict[str, Any]:
        axes = {k: v for k, v in (("tva", tva), ("exig", exig)) if v}
        return rt.period_diff(cui, period, axes)

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str, rt: Runtime = Depends(operator)) -> dict[str, Any]:
        try:
            return rt.view(job_id)
        except KeyError as exc:
            raise HTTPException(404, "unknown job") from exc

    @router.post("/jobs/{job_id}/resume")
    def resume(job_id: str, body: Any = Body(...), rt: Runtime = Depends(operator)) -> dict:
        try:
            return rt.resume(job_id, body)
        except KeyError as exc:
            raise HTTPException(404, "unknown job") from exc

    return router
