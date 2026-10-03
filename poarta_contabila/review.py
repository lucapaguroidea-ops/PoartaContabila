"""The review page (WP-66, 00_LAW §8 A8): a thin page over the operator API.

Three static files, served without a token: they hold no data. The page asks the person for
the operator token (kept in the tab's session storage) and their name, reads
``GET /inbox/{cui}/{period}`` and sends each answer, unchanged, to the question's own resume
route with ``X-Operator-Name``. No model is in the answer path and nothing is loaded from
outside this app: the content security policy allows this origin only, and every value from
a document is written as text, never as markup.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

UI = Path(__file__).parent / "ui"
FILES = {
    "": ("review.html", "text/html; charset=utf-8"),
    "review.js": ("review.js", "text/javascript; charset=utf-8"),
    "review.css": ("review.css", "text/css; charset=utf-8"),
    "icon.svg": ("icon.svg", "image/svg+xml"),
}
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def review_router() -> APIRouter:
    router = APIRouter(tags=["review"])

    @router.get("/review", include_in_schema=False)
    def page() -> Response:
        return _file("")

    @router.get("/review/{name}", include_in_schema=False)
    def asset(name: str) -> Response:
        if name not in FILES or not name:
            raise HTTPException(404)
        return _file(name)

    return router


def _file(name: str) -> Response:
    filename, media_type = FILES[name]
    return Response((UI / filename).read_bytes(), media_type=media_type, headers=HEADERS)
