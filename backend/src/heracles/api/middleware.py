"""Request id / logging and security-header middleware."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from heracles.api.errors import error_body
from heracles.api.settings import ApiSettings

log = structlog.get_logger("heracles.http")

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
}


TOO_LARGE = "The request body is too large"


class BodyLimitMiddleware:
    """Refuse request bodies above a limit before the application parses them.

    ``Content-Length`` is checked first; a body sent without it (chunked) is counted as it
    is read, so a client cannot make the server buffer more than the limit. Paths ending
    with one of ``large_suffixes`` (the import endpoints) get ``large_limit`` instead.
    Answers 413.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit: int,
        large_limit: int = 0,
        large_suffixes: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.limit = limit
        self.large_limit = max(large_limit, limit)
        self.large_suffixes = large_suffixes

    def _limit_for(self, path: str) -> int:
        return self.large_limit if path.endswith(self.large_suffixes) else self.limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit_for(str(scope.get("path", "")))
        for name, value in scope["headers"]:
            if name == b"content-length" and value.isdigit() and int(value) > limit:
                response = JSONResponse(error_body("too_large", TOO_LARGE), status_code=413)
                await response(scope, receive, send)
                return
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # An HTTPException is passed on by FastAPI's body parsing (any other
                    # exception would become a 400) and answered by the error handlers.
                    raise HTTPException(413, TOO_LARGE)
            return message

        await self.app(scope, counted, send)


def install_body_limit(app: FastAPI, settings: ApiSettings) -> None:
    """Add :class:`BodyLimitMiddleware` (install it before :func:`install_middleware`, so
    that the 413 still gets the request id and the security headers)."""
    app.add_middleware(
        BodyLimitMiddleware,
        limit=settings.max_body_bytes,
        large_limit=settings.max_import_body_bytes,
        large_suffixes=tuple(settings.import_paths),
    )


def install_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            log.exception("request_failed", method=request.method, path=request.url.path)
            raise
        response.headers[REQUEST_ID_HEADER] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return response
