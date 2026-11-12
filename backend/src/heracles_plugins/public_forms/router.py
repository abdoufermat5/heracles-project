"""Public (unauthenticated) endpoints of the public forms.

* ``GET  /api/v2/public/forms/{name}?token=`` form definition;
* ``GET  /api/v2/public/forms/{name}/captcha`` proof-of-work challenge;
* ``POST /api/v2/public/forms/{name}`` submission, creates the object.

A private form needs the personal token of an invitation. Failed attempts are
rate limited per client address and form, and successful submissions are
limited per client address and hour.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from heracles.api.errors import error_body
from heracles.auth.ratelimit import RateLimiter
from heracles.core.audit import AuditSink
from heracles.ldap.client import DirectoryClient, DirectoryError
from heracles.objects import (
    ObjectConflictError,
    ObjectValidationError,
    PermissionDeniedError,
    TypeRegistry,
    UnknownTypeError,
)
from heracles.objects.registry import PluginRouterContext
from heracles_plugins.invitations.tokens import (
    InvitationContext,
    InvitationUsedError,
    resolve_invitation_token,
)
from heracles_plugins.public_forms import shared as shared_state
from heracles_plugins.public_forms.captcha import Captcha
from heracles_plugins.public_forms.forms import (
    FormDefinition,
    FormError,
    describe_form,
    find_form,
    submit_form,
    template_tabs,
)

log = structlog.get_logger(__name__)

PATH = "/api/v2/public/forms"
HOUR = 3600.0


class SubmitBody(BaseModel):
    """Body of a submission; ``values`` is keyed by ``<tab>.<attribute>``."""

    values: dict[str, Any] = Field(default_factory=dict)
    token: str | None = Field(default=None, max_length=512)
    captcha_token: str | None = Field(default=None, max_length=1024)
    captcha_answer: str | None = Field(default=None, max_length=32)
    #: Honeypot: hidden from people, filled in by bots; a non-empty value drops the submission.
    website: str = Field(default="", max_length=256)
    accept_terms: bool = False


def _limited_route(limit: int) -> type[APIRoute]:
    """Route class refusing request bodies above ``limit`` bytes, before they are parsed.

    The ``Content-Length`` header is checked first; a body sent without it (chunked) is
    counted while it is read, so an anonymous client cannot make the server buffer more.
    """

    class LimitedRoute(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            original = super().get_route_handler()

            async def handler(request: Request) -> Response:
                length = request.headers.get("content-length", "")
                if length.isdigit() and int(length) > limit:
                    return _error(413, "too_large", "The submission is too large")
                chunks: list[bytes] = []
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        return _error(413, "too_large", "The submission is too large")
                    chunks.append(chunk)
                request._body = b"".join(chunks)  # pyright: ignore[reportPrivateUsage]
                return await original(request)

            return handler

    return LimitedRoute


class SubmissionWindow:
    """At most ``limit`` events per key in a sliding window."""

    def __init__(
        self, limit: int, window: float, clock: Callable[[], float], max_keys: int = 10_000
    ) -> None:
        self._limit = limit
        self._max_keys = max_keys
        self._window = window
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        events = self._events[key]
        while events and now - events[0] > self._window:
            events.popleft()
        if not events:
            self._events.pop(key, None)
        return events

    def retry_after(self, key: str) -> float:
        now = self._clock()
        with self._lock:
            events = self._prune(key, now)
            if len(events) < self._limit:
                return 0.0
            return max(0.0, self._window - (now - events[0]))

    def record(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            if key not in self._events and len(self._events) >= self._max_keys:
                self._make_room(now)
            self._prune(key, now)
            self._events[key].append(now)

    def _make_room(self, now: float) -> None:
        """Drop the expired keys, then the least recently used tenth when still full."""
        for key in list(self._events):
            self._prune(key, now)
        if len(self._events) >= self._max_keys:
            oldest = sorted(self._events, key=lambda k: self._events[k][-1])
            for key in oldest[: max(1, self._max_keys // 10)]:
                del self._events[key]


def _error(
    status: int,
    code: str,
    message: str,
    *,
    fields: dict[str, str] | None = None,
    retry_after: float | None = None,
) -> JSONResponse:
    headers = {"Retry-After": str(int(retry_after) + 1)} if retry_after else None
    return JSONResponse(error_body(code, message, fields), status_code=status, headers=headers)


def _client_ip(request: Request) -> str:
    state = getattr(request.app.state, "heracles", None)
    if state is not None:
        from heracles.api.deps import client_ip

        return client_ip(request, state)
    return request.client.host if request.client else "unknown"


def default_registry_provider(directory: DirectoryClient) -> Callable[[Request], TypeRegistry]:
    """The application registry, or one built from the plugins when the app has none."""
    cached: list[TypeRegistry] = []

    def provide(request: Request) -> TypeRegistry:
        domain = getattr(request.app.state, "domain", None)
        if domain is not None:
            registry: TypeRegistry = domain.registry
            return registry
        if not cached:
            from heracles.objects.builtin import register_builtin_types

            fresh = TypeRegistry()
            register_builtin_types(fresh)
            fresh.load_plugins(directory)
            cached.append(fresh)
        return cached[0]

    return provide


def build_public_router(
    get_directory: Callable[[], DirectoryClient],
    settings: Any,
    *,
    registry_provider: Callable[[Request], TypeRegistry] | None = None,
    clock: Callable[[], float] = time.time,
    limiter: RateLimiter | None = None,
    captcha: Captcha | None = None,
) -> APIRouter:
    """Router for the public form endpoints (mount it on the application root)."""
    max_body = int(getattr(settings, "max_body_bytes", 1_048_576))
    router = APIRouter(prefix=PATH, tags=["public forms"], route_class=_limited_route(max_body))
    configured_secret = str(getattr(settings, "captcha_secret", "") or "").encode() or None
    per_hour = int(getattr(settings, "submissions_per_hour", 20))
    shared: dict[int, tuple[RateLimiter, Captcha, Any]] = {}

    def parts(request: Request) -> tuple[RateLimiter, Captcha, Any]:
        """Limiter, challenges and submission window: in the application database when there
        is one (replicas share them), in memory otherwise."""
        state = getattr(request.app.state, "heracles", None)
        database = getattr(state, "database", None)
        slot = id(database)
        if slot not in shared:
            ttl = float(getattr(settings, "captcha_ttl_seconds", 600))
            difficulty = int(getattr(settings, "captcha_difficulty", 20))
            min_fill = float(getattr(settings, "captcha_min_fill_seconds", 3.0))
            if database is not None:
                from heracles.auth.ratelimit_db import SqliteRateLimiter

                db_guard: Any = SqliteRateLimiter(database)
                db_captcha = Captcha(
                    configured_secret or shared_state.load_secret(database),
                    ttl=ttl,
                    difficulty=difficulty,
                    min_fill=min_fill,
                    clock=clock,
                    nonces=shared_state.DbNonceStore(database, clock),
                )
                window: Any = shared_state.DbSubmissionWindow(database, per_hour, HOUR, clock)
                shared[slot] = (db_guard, db_captcha, window)
            else:
                if configured_secret is None:
                    log.warning(
                        "public_forms_secret_per_process",
                        detail="no captcha_secret and no application database: challenges "
                        "only verify on the process that issued them",
                    )
                shared[slot] = (
                    RateLimiter(),
                    Captcha(
                        configured_secret,
                        ttl=ttl,
                        difficulty=difficulty,
                        min_fill=min_fill,
                        clock=clock,
                    ),
                    SubmissionWindow(per_hour, HOUR, clock),
                )
        found_guard, found_captcha, found_window = shared[slot]
        return (
            limiter if limiter is not None else found_guard,
            captcha if captcha is not None else found_captcha,
            found_window,
        )

    allow_private_view = bool(getattr(settings, "allow_private_without_invitations", False))

    def registry_of(request: Request) -> TypeRegistry:
        nonlocal registry_provider
        if registry_provider is None:
            registry_provider = default_registry_provider(get_directory())
        return registry_provider(request)

    def now() -> datetime:
        return datetime.fromtimestamp(clock(), UTC)

    def context_of(
        directory: DirectoryClient, form: FormDefinition, token: str | None
    ) -> tuple[InvitationContext | None, bool]:
        """(invitation context, token acceptable); a bad token only matters for private forms."""
        if not token:
            return None, not form.private
        found = resolve_invitation_token(directory, token, now())
        if found is None or found.form_dn.lower() != form.dn.lower():
            return None, not form.private
        return found, True

    @router.get("/{name}", response_model=None)
    def get_form(name: str, request: Request, token: str | None = None) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        guard, _challenges, _successes = parts(request)
        key = RateLimiter.key(_client_ip(request), name)
        wait = guard.retry_after(key)
        if wait > 0:
            return _error(429, "rate_limited", "Too many attempts", retry_after=wait)
        try:
            directory = get_directory()
            form = find_form(directory, name)
            if form is None:
                guard.record_failure(key)
                return _error(404, "not_found", "Form not found")
            context, acceptable = context_of(directory, form, token)
            if not acceptable and not allow_private_view:
                guard.record_failure(key)
                return _error(404, "not_found", "Form not found")
            registry = registry_of(request)
            info = registry.get(form.type_name)
            template = template_tabs(directory, registry, form)
        except (UnknownTypeError, FormError):
            return _error(503, "unavailable", "This form is not available")
        except DirectoryError:
            return _error(503, "unavailable", "Directory unavailable")
        body = describe_form(form, info, template, email=context.email if context else None)
        body["invitation_required"] = form.private and context is None
        return JSONResponse(body)

    @router.get("/{name}/captcha", response_model=None)
    def get_captcha(name: str, request: Request) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        _guard, challenges, _successes = parts(request)
        try:
            form = find_form(get_directory(), name)
        except DirectoryError:
            return _error(503, "unavailable", "Directory unavailable")
        if form is None or not form.captcha:
            return _error(404, "not_found", "Form not found")
        return JSONResponse(challenges.new_challenge())

    @router.post("/{name}", response_model=None)
    def submit(name: str, body: SubmitBody, request: Request) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        guard, challenges, successes = parts(request)
        ip = _client_ip(request)
        key = RateLimiter.key(ip, name)
        wait = max(guard.retry_after(key), successes.retry_after(ip))
        if wait > 0:
            return _error(429, "rate_limited", "Too many attempts", retry_after=wait)
        if body.website:
            # A bot filled the hidden field: answer like a success, create nothing.
            guard.record_failure(key)
            return JSONResponse({"status": "ok", "message": ""}, status_code=201)
        try:
            directory = get_directory()
            form = find_form(directory, name)
            if form is None:
                guard.record_failure(key)
                return _error(404, "not_found", "Form not found")
            context, acceptable = context_of(directory, form, body.token)
            if not acceptable:
                guard.record_failure(key)
                return _error(404, "not_found", "Form not found")
            if form.captcha and not challenges.verify(body.captcha_token, body.captcha_answer):
                guard.record_failure(key)
                return _error(
                    422,
                    "validation",
                    "The check failed",
                    fields={"captcha_answer": "The check failed, try again."},
                )
            if form.tos_url and not body.accept_terms:
                guard.record_failure(key)
                return _error(
                    422,
                    "validation",
                    "The terms must be accepted",
                    fields={"accept_terms": "You must accept the terms."},
                )
            created = submit_form(
                directory, registry_of(request), form, body.values, context=context, now=now()
            )
            _audit_submission(registry_of(request), directory, form, created, context, ip)
        except InvitationUsedError:
            guard.record_failure(key)
            return _error(404, "not_found", "Form not found")
        except ObjectValidationError as exc:
            guard.record_failure(key)
            return _error(422, "validation", "Some fields are invalid", fields=exc.fields)
        except PermissionDeniedError:
            guard.record_failure(key)
            return _error(403, "forbidden", "This form cannot create this object")
        except ObjectConflictError:
            guard.record_failure(key)
            return _error(409, "conflict", "This object already exists")
        except (UnknownTypeError, FormError):
            return _error(503, "unavailable", "This form is not available")
        except DirectoryError:
            return _error(503, "unavailable", "Directory unavailable")
        successes.record(ip)
        guard.record_success(key)
        return JSONResponse({"status": "ok", "message": form.final_text}, status_code=201)

    return router


def _audit_submission(
    registry: Any, directory: DirectoryClient, form: Any, created: str, context: Any, ip: str
) -> None:
    """Record a public submission (anonymous: only the address is known)."""
    sink = AuditSink(registry)
    sink.record(
        directory,
        "create",
        object_type=form.type_name,
        object_dn=created,
        author_ip=ip,
        attributes=[f"form: {form.name}"],
        source="public form",
    )
    if context is not None:
        sink.record(
            directory,
            "modify",
            object_type="registration",
            object_dn=context.registration_dn,
            author_ip=ip,
            attributes=["invitation accepted", f"user: {created}"],
            source="public form",
        )


def build_router(ctx: PluginRouterContext) -> APIRouter:
    """Router factory (``Plugin.public_routers``) on the first configured directory."""
    directory = next(iter(ctx.directories.values()))
    return build_public_router(lambda: directory, ctx.settings)
