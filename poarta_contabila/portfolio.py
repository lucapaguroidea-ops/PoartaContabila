"""The portfolio calendar page (R45): a thin, read-only page over ``GET /calendar``.

Two static files, served without a token: they hold no data. The page asks for the operator
token (kept in the tab's session storage, under the review page's key) and reads the calendar
route; it sends nothing else. The route lists every tenant's filing items by due date, the
undated ones apart with the calendar's reason, and the tenant key is the only client field
(``filings.PORTFOLIO_FIELDS``). The review page's stylesheet, icon and security headers serve
it too.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from poarta_contabila.review import HEADERS, UI

FILES = {
    "": ("portfolio.html", "text/html; charset=utf-8"),
    "portfolio.js": ("portfolio.js", "text/javascript; charset=utf-8"),
}


def portfolio_router() -> APIRouter:
    router = APIRouter(tags=["portfolio"])

    @router.get("/portfolio", include_in_schema=False)
    def page() -> Response:
        return _file("")

    @router.get("/portfolio/{name}", include_in_schema=False)
    def asset(name: str) -> Response:
        if name not in FILES or not name:
            raise HTTPException(404)
        return _file(name)

    return router


def _file(name: str) -> Response:
    filename, media_type = FILES[name]
    return Response((UI / filename).read_bytes(), media_type=media_type, headers=HEADERS)
