"""Conditional JSON responses (strong ETag from the content hash).

For the rarely changing reads (types, department tree): the browser revalidates with
``If-None-Match`` on every use and gets a bodyless ``304`` while nothing changed. The tag is
a hash of what this very user would receive, so it never lets one user's cached copy stand
for another's. ``private, no-cache`` replaces the blanket ``no-store`` of the API for these
responses only.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

__all__ = ["CACHE_CONTROL", "json_with_etag"]

CACHE_CONTROL = "private, no-cache"


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    if header.strip() == "*":
        return True
    # a weak validator (a proxy recompressed the body) still matches for GET
    candidates = {part.strip().removeprefix("W/") for part in header.split(",")}
    return etag in candidates


def json_with_etag(request: Request, payload: Any) -> Response:
    """``payload`` as JSON with its ETag, or ``304`` when the client already has it."""
    body = JSONResponse(payload).body
    etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Cache-Control": CACHE_CONTROL}
    if _matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)
