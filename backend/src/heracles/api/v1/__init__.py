"""API v1 (compatibility REST API) — router skeleton.

Sessions are identified by the ``X-Session-Token`` header instead of a cookie,
so v1 is exempt from CSRF protection (spec 03).

TODO: the remaining v1 resources (objects, types, ...) once the object layer
is merged. Only ``/login`` and ``/logout`` exist for now. Second-factor
accounts cannot use v1 login.
"""

from __future__ import annotations

import math
from typing import Annotated

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field

from heracles.api.deps import StateDep, client_ip
from heracles.api.errors import ApiError, unauthenticated, validation
from heracles.auth.login import InvalidLoginError, authenticate_bind

SESSION_HEADER = "X-Session-Token"

router = APIRouter(prefix="/api/v1", tags=["v1"])


class V1LoginBody(BaseModel):
    username: Annotated[str, Field(min_length=1, max_length=256)]
    password: Annotated[str, Field(max_length=1024)]
    directory: str | None = None


class V1LoginResponse(BaseModel):
    token: str


@router.post("/login")
def login(body: V1LoginBody, request: Request, state: StateDep) -> V1LoginResponse:
    directory_id = body.directory or next(iter(state.directories), "")
    directory = state.directories.get(directory_id)
    if directory is None:
        raise validation("Unknown directory", {"directory": "Unknown directory"})
    key = state.limiter.key(client_ip(request, state), body.username)
    wait = state.limiter.retry_after(key)
    if wait > 0:
        raise ApiError(
            429,
            "rate_limited",
            "Too many attempts, try again later",
            headers={"Retry-After": str(math.ceil(wait))},
        )
    try:
        user_dn = authenticate_bind(directory, state.login_config, body.username, body.password)
    except InvalidLoginError:
        state.limiter.record_failure(key)
        raise unauthenticated("Invalid username or password") from None
    if state.second_factor.methods_for(user_dn):
        raise unauthenticated("Second factor accounts cannot use API v1")
    state.limiter.record_success(key)
    session = state.sessions.create(user_dn, directory_id)
    return V1LoginResponse(token=session.id)


@router.post("/logout", status_code=204)
def logout(
    state: StateDep,
    token: Annotated[str | None, Header(alias=SESSION_HEADER)] = None,
) -> None:
    if token:
        session = state.sessions.delete(token)
        if session is not None:
            for hook in state.logout_hooks:
                hook(session)
