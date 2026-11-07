"""Unauthenticated endpoint that extends an expiring account with a reminder token.

``POST /api/v2/reminder/prolong`` with ``{"login", "token"}``. The router is
built by :func:`build_prolong_router`; see the plugin docstring for how to
register it on the main application (outside the session and CSRF protected
router).
"""

from __future__ import annotations

import hmac
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from heracles.auth.ratelimit import RateLimiter
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    DirectoryError,
    Modification,
    NoSuchObjectError,
    Scope,
)
from heracles.ldap.filter import escape_filter_value
from heracles.schema import legacy
from heracles_plugins.user_reminder.runner import (
    EPOCH,
    TOKEN_TYPE_REMINDER,
    expiration_of,
    hash_token,
    reminder_tokens_container,
)

PATH = "/api/v2/reminder"


class ProlongRequest(BaseModel):
    login: str = Field(min_length=1, max_length=256)
    token: str = Field(min_length=1, max_length=512)


class ProlongError(Exception):
    """Token invalid, expired, already used or not matching the user."""


def prolong_account(
    directory: DirectoryClient, login: str, token: str, *, days: int, now: datetime
) -> date:
    """Validate and consume ``token`` and extend the account; returns the new expiry."""
    flt = (
        f"(&(objectClass={legacy.STD_OC.INET_ORG_PERSON})"
        f"({legacy.STD_ATTR.UID}={escape_filter_value(login)}))"
    )
    users = list(directory.search(directory.base_dn, flt, Scope.SUBTREE, ["shadowExpire"]))
    if len(users) != 1:
        raise ProlongError
    user = users[0]
    hashed = hash_token(token)
    container = reminder_tokens_container(directory)
    tflt = (
        f"(&(objectClass={legacy.OC.TOKEN})({legacy.ATTR.TOKEN_TYPE}={TOKEN_TYPE_REMINDER})"
        f"({legacy.ATTR.TOKEN}={escape_filter_value(hashed)}))"
    )
    try:
        found = list(directory.search(container, tflt))
    except NoSuchObjectError:
        raise ProlongError from None
    entry = next(
        (
            e
            for e in found
            if hmac.compare_digest((e.text(legacy.ATTR.TOKEN) or "").encode(), hashed.encode())
        ),
        None,
    )
    if entry is None:
        raise ProlongError
    owner = entry.text(legacy.ATTR.TOKEN_USER_DN) or ""
    if dnlib.normalize(owner) != dnlib.normalize(user.dn):
        raise ProlongError
    try:
        expires_at = int(entry.text(legacy.ATTR.TOKEN_TIMESTAMP) or "0")
    except ValueError:
        expires_at = 0
    utc_now = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    try:
        directory.delete(entry.dn)  # single use: the loser of a race gets NoSuchObject
    except NoSuchObjectError:
        raise ProlongError from None
    if utc_now.timestamp() > expires_at:
        raise ProlongError
    today = utc_now.date()
    current = expiration_of(user)
    new = max(today, current) if current else today
    new += timedelta(days=days)
    directory.modify(
        user.dn, [Modification("replace", "shadowExpire", [str((new - EPOCH).days).encode()])]
    )
    return new


def build_prolong_router(
    get_directory: Callable[[], DirectoryClient],
    settings: Any,
    *,
    clock: Callable[[], float] = time.time,
    limiter: RateLimiter | None = None,
) -> APIRouter:
    """Router for ``POST /api/v2/reminder/prolong``.

    ``settings`` is the plugin settings object (``prolongation_days``), read at each request.
    Failed attempts are rate limited per client address and login.
    """
    router = APIRouter(prefix=PATH, tags=["reminder"])
    guard = limiter if limiter is not None else RateLimiter()

    @router.post("/prolong")
    def prolong(body: ProlongRequest, request: Request) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        ip = request.client.host if request.client else "unknown"
        key = RateLimiter.key(ip, body.login)
        wait = guard.retry_after(key)
        if wait > 0:
            raise HTTPException(
                429, "Too many attempts", headers={"Retry-After": str(int(wait) + 1)}
            )
        try:
            new = prolong_account(
                get_directory(),
                body.login,
                body.token,
                days=int(settings.prolongation_days),
                now=datetime.fromtimestamp(clock(), UTC),
            )
        except ProlongError:
            guard.record_failure(key)
            raise HTTPException(400, "Invalid or expired link") from None
        except DirectoryError:
            raise HTTPException(503, "Directory unavailable") from None
        guard.record_success(key)
        return {"status": "ok", "new_expiration": new.isoformat()}

    return router
