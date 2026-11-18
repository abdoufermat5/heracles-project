"""Account actions shared by the console routes and the other API surfaces."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager  # pyright: ignore[reportDeprecated]
from typing import cast

from heracles.api.deps import CurrentUser
from heracles.api.domain import Domain
from heracles.api.errors import forbidden, not_found, validation
from heracles.api.state import AppState
from heracles.attributes import JSON
from heracles.auth.passwords import is_locked, lock, unlock
from heracles.auth.sessions import session_ref
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Modification
from heracles.objects import ObjectValidationError
from heracles.objects.policy import EventContext

#: ACL attribute protecting the account lock action (compatibility key).
USER_LOCK_ACL = "userLock"


def end_account_access(
    state: AppState | None,
    *dns: str,
    keep_session: str | None = None,
    revoke_tokens: bool = True,
) -> None:
    """Sign the account(s) out everywhere, at once and on every replica.

    Used when the account is locked or deleted and when its password changes: whoever holds
    a session (or an API token, unless ``revoke_tokens`` is false) of the account must not
    keep it. ``keep_session`` is the id of one session to spare (the person changing their
    own password). The stores are shared by the replicas, so nothing here is process-local.
    """
    if state is None:  # a caller without sessions (tests, tools)
        return
    spared = session_ref(keep_session) if keep_session else None
    for dn in {dnlib.normalize(d): d for d in dns}.values():
        state.sessions.delete_for_user(dn, keep=spared)
        if revoke_tokens:
            state.api_tokens.delete_for_owner(dn)


@contextmanager  # pyright: ignore[reportDeprecated]
def trigger_errors() -> Iterator[None]:
    """A failing ``pre*`` trigger aborts the operation with its output."""
    try:
        yield
    except ObjectValidationError as exc:
        raise validation("The change was refused", exc.fields) from exc


def set_account_lock(
    user: CurrentUser, domain: Domain, state: AppState | None, dn: str, locked: bool
) -> dict[str, JSON]:
    """Lock or unlock the account ``dn`` as ``user`` (needs the ``userLock`` write right).

    Raises :class:`~heracles.api.errors.ApiError` (403, 404, 422) like the console routes.
    """
    info = domain.registry.get("user")
    evaluator = domain.evaluator(user)
    if not evaluator.can_write_attr(dn, info.acl_object(info.main_tab), USER_LOCK_ACL):
        raise forbidden("You cannot lock or unlock this account")
    entry = user.directory.get(dn)
    if entry is None or not entry.has_object_class("inetOrgPerson"):
        raise not_found("User not found")
    stored = entry.text("userPassword") or ""
    new = lock(stored) if locked else unlock(stored)
    changes: list[Modification] = []
    if new != stored:
        if new:
            changes.append(Modification("replace", "userPassword", [new.encode()]))
        else:
            changes.append(Modification("delete", "userPassword"))
    for hook in domain.registry.account_lock_hooks:
        changes.extend(hook(entry, locked))
    service, _policy = domain.service(user, "user")
    events = domain.events(user)
    before = service.load("user", dn)
    pre = EventContext(type_name="user", dn=dn, before=before, after=before, changes=changes)
    with trigger_errors():
        (events.pre_lock if locked else events.pre_unlock)(pre)
    if changes:
        user.directory.modify(dn, changes)
    after = service.load("user", dn)
    post = EventContext(type_name="user", dn=dn, before=before, after=after, changes=changes)
    (events.post_lock if locked else events.post_unlock)(post)
    if locked:
        end_account_access(state, dn)
    warnings, messages = domain.collected(user)
    result: dict[str, JSON] = {"dn": dn, "locked": is_locked(new)}
    if warnings:
        result["warnings"] = cast(JSON, warnings)
    if messages:
        result["messages"] = cast(JSON, messages)
    return result
