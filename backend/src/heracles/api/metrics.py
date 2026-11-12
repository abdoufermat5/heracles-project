"""Request metrics, the build-version header and the protected ``/metrics`` endpoint."""

from __future__ import annotations

import os
import time
from collections.abc import Awaitable, Callable
from functools import lru_cache
from importlib import metadata

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from heracles import metrics
from heracles.api.deps import client_ip
from heracles.api.errors import not_found
from heracles.api.state import AppState
from heracles.auth.login import is_trusted_proxy, parse_networks

VERSION_HEADER = "X-Heracles-Version"
BUILD_ID_ENV = "HERACLES_BUILD_ID"
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


@lru_cache(maxsize=1)
def build_version() -> str:
    """Build id (``$HERACLES_BUILD_ID``) or the package version; the SPA compares it to its own."""
    explicit = os.environ.get(BUILD_ID_ENV, "").strip()
    if explicit:
        return explicit
    try:
        return metadata.version("heracles")
    except metadata.PackageNotFoundError:  # pragma: no cover - not installed
        return "dev"


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unmatched"


def _scheduler_lines(app: FastAPI) -> list[str]:
    store = getattr(app.state, "task_store", None)
    if store is None:
        return []
    try:
        runs = store.last_by_kind()
    except Exception:
        metrics.DATABASE_ERRORS.inc()
        return []
    lines = [
        "# HELP heracles_task_last_run_timestamp_seconds Last run of each task kind",
        "# TYPE heracles_task_last_run_timestamp_seconds gauge",
    ]
    failing = [
        "# HELP heracles_task_last_run_failed 1 when the last run of the task kind failed",
        "# TYPE heracles_task_last_run_failed gauge",
    ]
    for kind, run in sorted(runs.items()):
        lines.append(
            f'heracles_task_last_run_timestamp_seconds{{kind="{kind}"}} '
            f"{run.finished_at.timestamp()}"
        )
        failing.append(
            f'heracles_task_last_run_failed{{kind="{kind}"}} {1 if run.status == "error" else 0}'
        )
    return [*lines, *failing]


def install_metrics(app: FastAPI) -> None:
    """Add the metrics middleware, the version header and ``/metrics`` (404 unless enabled)."""

    @app.middleware("http")
    async def observe(  # pyright: ignore[reportUnusedFunction]
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
        finally:
            route = _route_template(request)
            metrics.HTTP_REQUESTS.inc(request.method, route, str(status))
            metrics.HTTP_SECONDS.observe(time.perf_counter() - started, request.method, route)
        response.headers[VERSION_HEADER] = build_version()
        return response

    @app.get("/metrics", include_in_schema=False)
    def scrape(request: Request) -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        state: AppState = request.app.state.heracles
        cfg = state.settings.metrics
        if not cfg.enabled:
            raise not_found()
        if cfg.allowed_networks:
            peer = client_ip(request, state)
            if not is_trusted_proxy(peer, parse_networks(cfg.allowed_networks)):
                raise not_found()
        body = metrics.REGISTRY.render() + "\n".join(_scheduler_lines(request.app)) + "\n"
        return PlainTextResponse(body, media_type=CONTENT_TYPE)
