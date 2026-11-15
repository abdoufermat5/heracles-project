"""Account actions shared by the console routes and the other API surfaces."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager  # pyright: ignore[reportDeprecated]
from typing import cast

from heracles.api.deps import CurrentUser
from heracles.api.domain import Domain
from heracles.api.errors import forbidden, not_found, validation
from heracles.attributes import JSON
from heracles.auth.passwords import is_locked, lock, unlock
from heracles.ldap.client import Modification
from heracles.objects import ObjectValidationError
from heracles.objects.policy import EventContext

#: ACL attribute protecting the account lock action (compatibility key).
USER_LOCK_ACL = "userLock"


@contextmanager  # pyright: ignore[reportDeprecated]
def trigger_errors() -> Iterator[None]:
    """A failing ``pre*`` trigger aborts the operation with its output."""
    try:
        yield
    except ObjectValidationError as exc:
        raise validation("The change was refused", exc.fields) from exc


def set_account_lock(user: CurrentUser, domain: Domain, dn: str, locked: bool) -> dict[str, JSON]:
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
    warnings, messages = domain.collected(user)
    result: dict[str, JSON] = {"dn": dn, "locked": is_locked(new)}
    if warnings:
        result["warnings"] = cast(JSON, warnings)
    if messages:
        result["messages"] = cast(JSON, messages)
    return result
