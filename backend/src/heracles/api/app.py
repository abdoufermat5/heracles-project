"""FastAPI application factory."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse

from heracles.api import v1, v2
from heracles.api.errors import install_error_handlers
from heracles.api.middleware import install_body_limit, install_middleware
from heracles.api.settings import ApiSettings
from heracles.api.state import AdminResolver, AppState, LogoutHook
from heracles.api.static import mount_spa
from heracles.auth.login import LoginConfig, parse_networks
from heracles.auth.mail import Mailer, MemoryMailer
from heracles.auth.passwords import PasswordPolicy
from heracles.auth.ratelimit import LoginLimiter, RateLimiter
from heracles.auth.ratelimit_db import SqliteRateLimiter
from heracles.auth.recovery import InMemoryTokenStore, RecoveryService, TokenStore
from heracles.auth.recovery_db import SqliteTokenStore
from heracles.auth.second_factor import (
    InMemorySecondFactorStore,
    SecondFactorService,
    SecondFactorStore,
)
from heracles.auth.second_factor_db import SqliteSecondFactorStore
from heracles.auth.sessions import InMemorySessionStore, SessionStore
from heracles.auth.sessions_db import SqliteSessionStore
from heracles.auth.webauthn import WebAuthnService
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError
from heracles.storage import Database


def _default_admin_resolver(admin_dns: Iterable[str]) -> AdminResolver:
    normalized = {dnlib.normalize(d) for d in admin_dns}

    def resolve(_directory: DirectoryClient, user_dn: str) -> bool:
        return dnlib.normalize(user_dn) in normalized

    return resolve


def create_app(
    settings: ApiSettings,
    directories: dict[str, DirectoryClient],
    *,
    sessions: SessionStore | None = None,
    second_factor_store: SecondFactorStore | None = None,
    token_store: TokenStore | None = None,
    mailer: Mailer | None = None,
    limiter: LoginLimiter | None = None,
    is_admin: AdminResolver | None = None,
    logout_hooks: Iterable[LogoutHook] = (),
    extra_routers: Iterable[APIRouter] = (),
    public_routers: Iterable[APIRouter] = (),
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    """Build the application.

    ``extra_routers`` are included under the CSRF-protected ``/api/v2`` router
    (their own prefix is relative to ``/api/v2``); ``public_routers`` are mounted
    at the root without session or CSRF checks. Every service has an
    in-memory default so the app runs without any backend but the directory.
    With a database (``settings.database.path``) the sessions, the second-factor
    registrations, the recovery tokens and the login limiter default to stores in it,
    so several worker processes share them.
    """
    app = FastAPI(
        title="Heracles",
        docs_url="/api/docs" if settings.enable_docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.enable_docs else None,
    )

    database = Database(settings.database.path) if settings.database.path is not None else None
    session_store: SessionStore
    if sessions is not None:
        session_store = sessions
    elif database is not None:
        session_store = SqliteSessionStore(
            database,
            idle_timeout=settings.session.idle_timeout_seconds,
            absolute_timeout=settings.session.absolute_timeout_seconds,
            clock=clock,
        )
    else:
        session_store = InMemorySessionStore(
            idle_timeout=settings.session.idle_timeout_seconds,
            absolute_timeout=settings.session.absolute_timeout_seconds,
        )
    mail = mailer if mailer is not None else MemoryMailer()
    sf_store: SecondFactorStore
    if second_factor_store is not None:
        sf_store = second_factor_store
    elif database is not None:
        sf_store = SqliteSecondFactorStore(database)
    else:
        sf_store = InMemorySecondFactorStore()
    tokens: TokenStore
    if token_store is not None:
        tokens = token_store
    elif database is not None:
        tokens = SqliteTokenStore(database, clock)
    else:
        tokens = InMemoryTokenStore()
    login_limiter: LoginLimiter
    if limiter is not None:
        login_limiter = limiter
    elif database is not None:
        login_limiter = SqliteRateLimiter(
            database,
            free_attempts=settings.login.free_attempts,
            base_delay=settings.login.base_delay_seconds,
            max_delay=settings.login.max_delay_seconds,
            clock=clock,
        )
    else:
        login_limiter = RateLimiter(
            free_attempts=settings.login.free_attempts,
            base_delay=settings.login.base_delay_seconds,
            max_delay=settings.login.max_delay_seconds,
        )
    policy_cfg = settings.password
    policy = PasswordPolicy(
        min_length=policy_cfg.min_length,
        min_differing=policy_cfg.min_differing,
        default_method=policy_cfg.default_method,
        allowed_methods=tuple(policy_cfg.allowed_methods),
        force_default=policy_cfg.force_default,
    )
    login_cfg = LoginConfig(
        login_attribute=settings.login.login_attribute,
        user_object_class=settings.login.user_object_class,
    )
    app.state.heracles = AppState(
        settings=settings,
        directories=directories,
        sessions=session_store,
        limiter=login_limiter,
        second_factor=SecondFactorService(sf_store, issuer=settings.totp_issuer, clock=clock),
        webauthn=WebAuthnService(sf_store, settings.webauthn, clock=clock),
        recovery=RecoveryService(
            store=tokens,
            mailer=mail,
            policy=policy,
            login_config=login_cfg,
            config=settings.recovery.to_config(),
            clock=clock,
        ),
        mailer=mail,
        policy=policy,
        login_config=login_cfg,
        trusted_proxies=parse_networks(settings.login.trusted_proxies),
        is_admin=is_admin or _default_admin_resolver(settings.admin_dns),
        logout_hooks=list(logout_hooks),
        clock=clock,
        database=database,
    )

    install_error_handlers(app)
    install_body_limit(app, settings)
    install_middleware(app)

    app.include_router(v2.build_router(extra_routers))
    for public in public_routers:
        app.include_router(public)
    app.include_router(v1.router)
    _install_health(app)

    if settings.static_dir is not None:
        mount_spa(app, settings.static_dir)
    return app


def _install_health(app: FastAPI) -> None:
    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        state: AppState = app.state.heracles
        results: dict[str, bool] = {}
        for dir_id, directory in state.directories.items():
            try:
                results[dir_id] = directory.get(directory.base_dn, ["objectClass"]) is not None
            except DirectoryError:
                results[dir_id] = False
        ready = all(results.values())
        return JSONResponse(
            {"status": "ok" if ready else "unavailable", "directories": results},
            status_code=200 if ready else 503,
        )
