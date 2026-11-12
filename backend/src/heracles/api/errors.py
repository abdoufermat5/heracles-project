"""Error model and handlers producing the API JSON error format."""

from __future__ import annotations

import sqlite3
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from heracles import metrics
from heracles.ldap.client import DirectoryError, DirectoryUnavailableError
from heracles.storage.database import DatabaseError

log = structlog.get_logger(__name__)

_STATUS_CODES = {
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "too_large",
    429: "rate_limited",
    501: "not_implemented",
    502: "ldap_error",
}


class ApiError(Exception):
    """Raise from any endpoint to produce ``{"error": {...}}``."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        fields: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields
        self.extra = extra or {}
        self.headers = headers


def unauthenticated(message: str = "Authentication required") -> ApiError:
    return ApiError(401, "unauthenticated", message)


def forbidden(message: str = "Forbidden") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(message: str = "Not found") -> ApiError:
    return ApiError(404, "not_found", message)


def validation(message: str, fields: dict[str, str] | None = None) -> ApiError:
    return ApiError(422, "validation", message, fields=fields or {})


def error_body(
    code: str,
    message: str,
    fields: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if fields is not None:
        body["fields"] = fields
    if extra:
        body.update(extra)
    return {"error": body}


def _api_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return JSONResponse(
        error_body(exc.code, exc.message, exc.fields, exc.extra),
        status_code=exc.status,
        headers=exc.headers,
    )


def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_CODES.get(exc.status_code)
    if code is None:
        code = "internal" if exc.status_code >= 500 else "validation"
    return JSONResponse(
        error_body(code, str(exc.detail)),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(p) for p in err["loc"] if p not in ("body", "query", "path")]
        fields[".".join(loc) or "_"] = str(err["msg"])
    return JSONResponse(
        error_body("validation", "Invalid request", fields),
        status_code=422,
    )


def _directory_error(_: Request, exc: Exception) -> JSONResponse:
    log.warning("directory_error", error=type(exc).__name__)
    return JSONResponse(
        error_body("ldap_error", "The directory server reported an error"),
        status_code=502,
    )


def _directory_unavailable(_: Request, exc: Exception) -> JSONResponse:
    log.warning("directory_unavailable", error=str(exc))
    return JSONResponse(
        error_body("directory_unavailable", "The directory is unavailable, try again shortly"),
        status_code=503,
        headers={"Retry-After": "5"},
    )


def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled_exception", exc_info=exc)
    if isinstance(exc, sqlite3.Error | DatabaseError):
        metrics.DATABASE_ERRORS.inc()
        return JSONResponse(
            error_body("database_unavailable", "The application database is unavailable"),
            status_code=503,
        )
    return JSONResponse(
        error_body("internal", "Internal server error"),
        status_code=500,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(DirectoryError, _directory_error)
    app.add_exception_handler(DirectoryUnavailableError, _directory_unavailable)
    app.add_exception_handler(Exception, _unhandled)
