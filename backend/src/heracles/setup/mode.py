"""Setup mode of ``heracles serve``: a console that only configures itself.

Until a configuration with a directory exists, the server answers ``503 setup_required`` on
every ``/api`` route except ``/api/v2/setup/*``, which a one-time token authenticates. A
successful ``apply`` writes the configuration and swaps the running application for the real
one behind :class:`SetupDispatcher`, without restarting the process.
"""

from __future__ import annotations

import hmac
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.types import Receive, Scope, Send

from heracles import __version__
from heracles.api.errors import ApiError, install_error_handlers, validation
from heracles.api.middleware import install_body_limit, install_middleware
from heracles.api.settings import ApiSettings
from heracles.api.static import mount_spa
from heracles.auth.ratelimit import RateLimiter
from heracles.setup import service

log = structlog.get_logger(__name__)

TOKEN_HEADER = "X-Setup-Token"  # noqa: S105  (a header name)
PREFIX = "/api/v2/setup"

type AppBuilder = Callable[[Path], FastAPI]


@dataclass(slots=True)
class SetupState:
    token: str
    config_path: Path
    build_app: AppBuilder
    client_factory: service.ClientFactory = service.default_client_factory
    limiter: RateLimiter = field(default_factory=lambda: RateLimiter(free_attempts=5))
    lock: threading.Lock = field(default_factory=threading.Lock)
    #: Called with the new application once the setup is applied.
    on_applied: Callable[[FastAPI], None] = lambda _app: None


# ----------------------------------------------------------------------- request models


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")


class TokenBody(_Body):
    token: str = ""


class DirectoryBody(_Body):
    uri: str
    starttls: bool = False
    ca_file: str | None = None
    bind_dn: str = ""
    bind_password: str = ""
    base_dn: str


class DirectoryApplyBody(DirectoryBody):
    id: str = Field(default="main", min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    label: str = ""


class AdminBody(_Body):
    uid: str
    given_name: str = "Administrator"
    surname: str = "Admin"
    mail: str = ""
    password: str


class ApplyBody(_Body):
    directory: DirectoryApplyBody
    admin: AdminBody
    plugins: list[str] = Field(default_factory=lambda: [])
    public_url: str | None = None


# -------------------------------------------------------------------------- the router


def status_router(config_path: Path | None) -> APIRouter:
    """``GET /api/v2/setup/status`` of a configured server (``setup_required: false``)."""
    router = APIRouter()

    @router.get(f"{PREFIX}/status", include_in_schema=False)
    def status() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return status_body(False, config_path)

    return router


def status_body(required: bool, config_path: Path | None) -> dict[str, Any]:
    return {
        "setup_required": required,
        "version": __version__,
        "config_path": str(config_path) if config_path else "",
    }


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def build_setup_router(state: SetupState) -> APIRouter:
    router = APIRouter(prefix=PREFIX)

    def check_token(
        request: Request,
        x_setup_token: Annotated[str | None, Header(alias=TOKEN_HEADER)] = None,
    ) -> None:
        key = state.limiter.key(_client_ip(request), "setup")
        wait = state.limiter.retry_after(key)
        if wait > 0:
            raise ApiError(
                429,
                "rate_limited",
                "Too many wrong tokens: wait before trying again",
                headers={"Retry-After": str(int(wait) + 1)},
            )
        given = (x_setup_token or "").encode()
        if not given or not hmac.compare_digest(given, state.token.encode()):
            state.limiter.record_failure(key)
            log.warning("setup_token_invalid", ip=_client_ip(request))
            raise ApiError(401, "setup_token_invalid", "The setup token is missing or wrong")
        state.limiter.record_success(key)

    authed = Depends(check_token)

    @router.get("/status")
    def status() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return status_body(True, state.config_path)

    @router.post("/token/verify", status_code=204)
    def verify(body: TokenBody, request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        check_token(request, body.token)
        log.info("setup_token_verified", ip=_client_ip(request))
        return Response(status_code=204)

    @router.post("/directory/test", dependencies=[authed])
    def test_connection(body: DirectoryBody) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        spec = service.DirectorySpec(
            uri=body.uri,
            base_dn=body.base_dn,
            bind_dn=body.bind_dn,
            bind_password=body.bind_password,
            starttls=body.starttls,
            ca_file=body.ca_file,
        )
        return service.test_directory(spec, state.client_factory).to_json()

    @router.get("/schema", dependencies=[authed])
    def schema(format: str = "ldif") -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        from heracles.schema.export import render_ldif, render_schema

        if format not in ("ldif", "schema"):
            raise validation("Unknown format", {"format": "Use ldif or schema."})
        text = render_ldif() if format == "ldif" else render_schema()
        name = "heracles.ldif" if format == "ldif" else "heracles.schema"
        return PlainTextResponse(
            text, headers={"Content-Disposition": f'attachment; filename="{name}"'}
        )

    @router.get("/plugins", dependencies=[authed])
    def plugins() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return service.plugin_catalog()

    @router.post("/apply", dependencies=[authed])
    def apply(body: ApplyBody, request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        d = body.directory
        spec = service.DirectorySpec(
            uri=d.uri,
            base_dn=d.base_dn,
            bind_dn=d.bind_dn,
            bind_password=d.bind_password,
            starttls=d.starttls,
            ca_file=d.ca_file,
            id=d.id,
            label=d.label,
        )
        admin = service.AdminSpec(
            uid=body.admin.uid.strip(),
            password=body.admin.password,
            given_name=body.admin.given_name,
            surname=body.admin.surname,
            mail=body.admin.mail,
        )
        with state.lock:
            if state.token == "":  # already applied by a concurrent request
                raise ApiError(409, "conflict", "The setup has already been applied")
            try:
                result = service.apply_setup(
                    spec,
                    admin,
                    body.plugins,
                    body.public_url,
                    state.config_path,
                    state.client_factory,
                )
            except service.SetupError as exc:
                log.info("setup_apply_refused", reason=exc.message, fields=sorted(exc.fields))
                raise validation(exc.message, exc.fields) from exc
            # build first: when it fails the token stays valid and the apply can be retried
            # (it is idempotent), instead of leaving a console nobody can authenticate to
            app = state.build_app(result.config_path)
            service.remove_token()
            state.token = ""
        service.record_setup_audit(app, result.admin_dn, spec.base_dn, _client_ip(request))
        state.on_applied(app)
        return {"ok": True, "config_path": str(result.config_path), "login_url": "/login"}

    return router


def build_setup_app(state: SetupState, static_dir: Path | None = None) -> FastAPI:
    """The application served while the setup is pending."""
    app = FastAPI(title="Heracles setup", docs_url=None, redoc_url=None, openapi_url=None)
    settings = ApiSettings()
    install_error_handlers(app)
    install_body_limit(app, settings)
    install_middleware(app)
    app.include_router(build_setup_router(state))

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        # the process is healthy: it is waiting for its configuration
        return {"status": "setup_required"}

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    def setup_required(path: str) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        del path
        return JSONResponse(
            {
                "error": {
                    "code": "setup_required",
                    "message": "Heracles is not configured yet: finish the setup first",
                }
            },
            status_code=503,
        )

    if static_dir is not None:
        mount_spa(app, static_dir)
    return app


class SetupDispatcher:
    """ASGI application: the setup app until the setup is applied, then the real one."""

    def __init__(self, setup_app: FastAPI) -> None:
        self.setup_app = setup_app
        self.app: Any = setup_app

    def switch(self, app: FastAPI) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # the lifespan belongs to the application the server started with
        target = self.setup_app if scope["type"] == "lifespan" else self.app
        await target(scope, receive, send)


def make_setup_server(
    config: str | None,
    *,
    static_dir: Path | None,
    with_worker: bool,
    worker_interval: float,
    client_factory: service.ClientFactory = service.default_client_factory,
    build_app: AppBuilder | None = None,
) -> SetupDispatcher:
    """Create the setup-mode application and announce its token."""
    import os

    config_path = service.config_path_for(config)
    token = service.new_token()
    written = service.write_token(token)

    def default_build(path: Path) -> FastAPI:
        from heracles.server import build_app as real_build

        os.environ["HERACLES_CONFIG"] = str(path)
        os.environ["HERACLES_WORKER_INTERVAL"] = str(worker_interval)
        return real_build(path, with_worker=with_worker)

    state = SetupState(
        token=token,
        config_path=config_path,
        build_app=build_app or default_build,
        client_factory=client_factory,
    )
    dispatcher = SetupDispatcher(build_setup_app(state, static_dir))
    state.on_applied = dispatcher.switch
    stored = f" The token is also stored in {written}.\n" if written else ""
    log.warning("setup_required", config=str(config_path), token_file=str(written or ""))
    print(
        "\n"
        "============================================================\n"
        " Heracles is not configured yet.\n"
        " Open the console in your browser and enter this setup token:\n"
        f"\n     {token}\n\n"
        f"{stored}"
        f" The configuration will be written to {config_path}.\n"
        "============================================================\n",
        file=sys.stderr,
        flush=True,
    )
    return dispatcher
