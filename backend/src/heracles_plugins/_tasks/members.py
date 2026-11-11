"""Member expansion: users, groups and roles resolved to user entries."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry
from heracles.schema import names as schema

USER_ATTRS = (
    "objectClass",
    "uid",
    "cn",
    "givenName",
    "sn",
    "mail",
    "shadowExpire",
    "member",
    "roleOccupant",
)


def expand_members(
    directory: DirectoryClient, dns: Iterable[str], extra_attrs: Sequence[str] = ()
) -> list[Entry]:
    """Resolve DNs of users, groups (``member``) and roles (``roleOccupant``) to user entries.

    Nested groups are followed; every user appears once. ``extra_attrs`` are read in
    addition to the common user attributes.
    """
    attrs = list(dict.fromkeys([*USER_ATTRS, *extra_attrs]))
    users: dict[str, Entry] = {}
    seen: set[str] = set()
    pending = list(dns)
    while pending:
        dn = pending.pop(0)
        key = dnlib.normalize(dn)
        if key in seen:
            continue
        seen.add(key)
        try:
            entry = directory.get(dn, attrs)
        except DirectoryError:
            continue
        if entry is None:
            continue
        if entry.has_object_class("organizationalRole"):
            pending.extend(entry.texts("roleOccupant"))
        elif entry.has_object_class("groupOfNames") or entry.has_object_class(
            schema.OC.OBJECT_GROUP
        ):
            pending.extend(entry.texts("member"))
        else:
            users[key] = entry
    return list(users.values())
