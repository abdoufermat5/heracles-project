"""Audit events of the sign-in flows (shared by the API v1 and v2 login routes)."""

from __future__ import annotations

from fastapi import Request

from heracles.api.deps import client_ip
from heracles.api.state import AppState
from heracles.auth.login import find_user_dn
from heracles.ldap.client import DirectoryClient, DirectoryError


def audit_login_failed(
    state: AppState, request: Request, directory: DirectoryClient, login: str, reason: str
) -> None:
    """Record a failed sign-in: the author is unknown, the attempted login is noted."""
    if not state.audit.enabled:
        return
    try:
        target = find_user_dn(directory, state.login_config, login) or login
    except DirectoryError:
        target = login
    state.audit.record(
        directory,
        "login_failed",
        object_type="user",
        object_dn=target,
        author_ip=client_ip(request, state),
        attributes=[f"login: {login}", f"reason: {reason}"],
        result="failure",
    )


def audit_login(
    state: AppState, request: Request, directory: DirectoryClient, user_dn: str, via: str
) -> None:
    state.audit.record(
        directory,
        "login",
        object_type="user",
        object_dn=user_dn,
        author_dn=user_dn,
        author_ip=client_ip(request, state),
        attributes=[f"method: {via}"],
    )
