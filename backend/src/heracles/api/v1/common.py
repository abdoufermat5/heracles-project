"""Shared plumbing of API v1: error shape, session-token dependency."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from heracles.api.deps import CurrentUser, StateDep, client_ip
from heracles.api.errors import ApiError, unauthenticated
from heracles.api.middleware import LEGACY_SESSION_HEADER, SESSION_HEADER
from heracles.ldap.client import DirectoryError


def v1_error(status: int, message: str, fields: dict[str, str] | None = None) -> JSONResponse:
    """The v1 ``Error`` body: ``{"message": ...}`` (plus ``fields`` on validation errors)."""
    body: dict[str, Any] = {"message": message}
    if fields:
        body["fields"] = fields
    return JSONResponse(body, status_code=status)


class V1Route(APIRoute):
    """Route turning every error into the v1 ``{"message": ...}`` shape."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except ApiError as exc:
                response = v1_error(exc.status, exc.message, exc.fields)
                for name, value in (exc.headers or {}).items():
                    response.headers[name] = value
                return response
            except RequestValidationError as exc:
                fields: dict[str, str] = {}
                for err in exc.errors():
                    loc = [str(p) for p in err["loc"] if p not in ("body", "query", "path")]
                    fields[".".join(loc) or "_"] = str(err["msg"])
                return v1_error(400, "Invalid request", fields)
            except StarletteHTTPException as exc:
                return v1_error(exc.status_code, str(exc.detail))
            except DirectoryError:
                return v1_error(502, "The directory server reported an error")

        return handler


def session_token(request: Request) -> str | None:
    """The session token header (``Session-Token``, or the older ``X-Session-Token``)."""
    return request.headers.get(SESSION_HEADER) or request.headers.get(LEGACY_SESSION_HEADER)


def v1_user(request: Request, state: StateDep) -> CurrentUser:
    """The user owning the session token of the request."""
    token = session_token(request)
    session = state.sessions.get(token) if token else None
    if session is None:
        raise unauthenticated("A valid Session-Token header is required")
    if session.second_factor_pending:
        raise unauthenticated("Second factor accounts cannot use API v1")
    directory = state.directories.get(session.directory_id)
    if directory is None:
        raise unauthenticated("Unknown directory")
    return CurrentUser(session, session.directory_id, directory, client_ip(request, state))


V1UserDep = Annotated[CurrentUser, Depends(v1_user)]
