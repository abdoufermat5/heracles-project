"""Request id / logging and security-header middleware."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from heracles.api.errors import error_body
from heracles.api.settings import ApiSettings
from heracles.api.state import AppState
from heracles.auth.login import IPNetwork, is_trusted_proxy
from heracles.auth.sessions import Session

if TYPE_CHECKING:
    from heracles.api.domain import Domain

log = structlog.get_logger("heracles.http")

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

#: ASGI scope key of the sessions a request loaded (the request and this middleware share it).
SESSIONS_SCOPE_KEY = "heracles.sessions"

#: Session token headers of API v1 (the cookie of API v2 is named by the settings).
SESSION_HEADER = "Session-Token"
LEGACY_SESSION_HEADER = "X-Session-Token"

_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

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
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), "
        "publickey-credentials-get=(self), publickey-credentials-create=(self)"
    ),
}

HSTS = "max-age=31536000; includeSubDomains"


def is_https(request: Request, trusted_proxies: list[IPNetwork]) -> bool:
    """Whether the client reached us over HTTPS (directly, or through a trusted proxy)."""
    if request.url.scheme == "https":
        return True
    peer = request.client.host if request.client else ""
    if peer and is_trusted_proxy(peer, trusted_proxies):
        return request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower() == "https"
    return False


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


#: Responses smaller than this are sent as they are (compressing them gains nothing).
GZIP_MINIMUM_BYTES = 1024


async def _save_sessions(request: Request) -> None:
    """Persist what the handlers changed on the sessions this request loaded.

    Handlers edit the session object in place; a store shared between processes only
    sees the change through ``save`` (a no-op for the in-memory store).
    """
    touched: list[Session] | None = request.scope.get(SESSIONS_SCOPE_KEY)
    state: AppState | None = getattr(request.app.state, "heracles", None)
    if not touched or state is None:
        return
    store = state.sessions

    def save_all() -> None:
        for session in touched:
            store.save(session)

    try:
        await run_in_threadpool(save_all)
    except Exception:
        log.exception("session_save_failed")


def _invalidate_listings(request: Request) -> None:
    """Drop the listing snapshots of the session behind a request that may have written.

    Whatever the router (API v1, v2, a plugin's), a request that is not read-only makes
    the snapshots of its session stale. The raw id of the cookie or token is enough: an
    unknown id matches no snapshot, so no session lookup is needed.
    """
    if request.method in _READ_ONLY_METHODS:
        return
    domain: Domain | None = getattr(request.app.state, "domain", None)
    state: AppState | None = getattr(request.app.state, "heracles", None)
    if domain is None or state is None:
        return
    sid = (
        request.cookies.get(state.settings.session.cookie_name)
        or request.headers.get(SESSION_HEADER)
        or request.headers.get(LEGACY_SESSION_HEADER)
    )
    if sid:
        domain.invalidate_listings(sid)


def install_middleware(app: FastAPI) -> None:
    # Added first so it sits inside ``request_context``: the SPA bundle and the JSON
    # listings compress to about a quarter of their size.
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MINIMUM_BYTES)

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
        finally:
            _invalidate_listings(request)
            await _save_sessions(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        app_state: AppState | None = getattr(request.app.state, "heracles", None)
        if app_state is not None and is_https(request, app_state.trusted_proxies):
            response.headers.setdefault("Strict-Transport-Security", HSTS)
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
