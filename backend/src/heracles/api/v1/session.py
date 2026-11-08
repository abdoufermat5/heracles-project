"""v1 authentication endpoints: login, logout, token, directories."""

from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from heracles.api.deps import StateDep, client_ip
from heracles.api.errors import ApiError, unauthenticated, validation
from heracles.api.v1.common import V1Route, V1UserDep, session_token
from heracles.auth.login import InvalidLoginError, authenticate_bind

router = APIRouter(route_class=V1Route, tags=["authentification"])


class LoginRequest(BaseModel):
    """Body of ``POST /login``."""

    directory: str | None = Field(
        default=None,
        description="The directory to log into. Use /directories to get possible values.",
    )
    user: Annotated[str | None, Field(max_length=256, description="The user to login as")] = None
    #: Backward compatible spelling of ``user``.
    username: Annotated[str | None, Field(max_length=256, exclude=True)] = None
    password: Annotated[str, Field(max_length=1024, description="The password to use")]


@router.post("/login", summary="Login to the API", operation_id="login")
def login(body: LoginRequest, request: Request, state: StateDep) -> str:
    login_name = body.user or body.username
    if not login_name:
        raise validation("The 'user' field is required", {"user": "required"})
    directory_id = body.directory or next(iter(state.directories), "")
    directory = state.directories.get(directory_id)
    if directory is None:
        raise validation("Unknown directory", {"directory": "Unknown directory"})
    key = state.limiter.key(client_ip(request, state), login_name)
    wait = state.limiter.retry_after(key)
    if wait > 0:
        raise ApiError(
            429,
            "rate_limited",
            "Too many attempts, try again later",
            headers={"Retry-After": str(math.ceil(wait))},
        )
    try:
        user_dn = authenticate_bind(directory, state.login_config, login_name, body.password)
    except InvalidLoginError:
        state.limiter.record_failure(key)
        raise unauthenticated("Invalid username or password") from None
    if state.second_factor.methods_for(user_dn):
        raise unauthenticated("Second factor accounts cannot use API v1")
    state.limiter.record_success(key)
    return state.sessions.create(user_dn, directory_id).id


@router.get(
    "/directories", summary="List the directories usable at login", operation_id="listDirectories"
)
def list_directories(state: StateDep) -> dict[str, str]:
    labels = state.settings.directory_labels
    return {i: labels.get(i, i) for i in state.directories}


@router.post("/logout", status_code=204, summary="End the session", operation_id="logout")
def logout(request: Request, state: StateDep) -> Response:
    token = session_token(request)
    session = state.sessions.delete(token) if token else None
    if session is None:
        raise unauthenticated("A valid Session-Token header is required")
    for hook in state.logout_hooks:
        hook(session)
    return Response(status_code=204)


@router.get("/token", summary="Token of the current session", operation_id="getToken")
def get_token(request: Request, user: V1UserDep) -> str:
    del user
    return session_token(request) or ""
