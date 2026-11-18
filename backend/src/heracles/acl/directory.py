"""LDAP-backed implementation of :class:`AclDirectory`."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from heracles.acl._names import (
    ATTR_ACL_ENTRY,
    ATTR_ACL_TEMPLATE,
    OC_ACL,
    OC_GROUP_OF_NAMES,
    OC_POSIX_GROUP,
    OC_ROLE,
    OC_SIMPLE_SECURITY,
)
from heracles.acl.resolver import AssignmentEntry, escape_filter_value
from heracles.core.generalized_time import parse_generalized_time
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry, Scope

#: End dates of memberships (access plugin): ``<time> <kind> <member DN>``.
_GRANT_EXPIRY = "hrcGrantExpiry"


def _expired_member(entry: Entry, kind: str, member: str, now: datetime) -> bool:
    """Whether the entry carries an end date, already passed, for ``member`` in ``kind``.

    A membership whose date passed grants nothing, even while the expiry task cannot remove
    it (the last member of a ``groupOfNames`` must stay for the entry to be valid).
    """
    wanted = dnlib.normalize(member)
    for raw in entry.texts(_GRANT_EXPIRY):
        stamp, _, rest = raw.strip().partition(" ")
        value_kind, _, value_member = rest.partition(" ")
        if value_kind.lower() != kind.lower() or dnlib.normalize(value_member.strip()) != wanted:
            continue
        try:
            until = parse_generalized_time(stamp)
        except ValueError:
            continue
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        if until <= now:
            return True
    return False


class LdapAclDirectory:
    """Runs the ACL lookups against a :class:`DirectoryClient`."""

    def __init__(
        self, client: DirectoryClient, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._c = client
        self._clock = clock

    def _dns(self, filterstr: str) -> list[str]:
        return [e.dn for e in self._c.search(self._c.base_dn, filterstr, attrs=["1.1"])]

    def groups_of_user(self, user_dn: str) -> list[str]:
        v = escape_filter_value(user_dn)
        found = self._c.search(
            self._c.base_dn,
            f"(&(objectClass={OC_GROUP_OF_NAMES})(member={v}))",
            attrs=[_GRANT_EXPIRY],
        )
        return [e.dn for e in found if not _expired_member(e, "member", user_dn, self._clock())]

    def posix_groups_by_uid(self, uid: str) -> list[str]:
        v = escape_filter_value(uid)
        return self._dns(f"(&(objectClass={OC_POSIX_GROUP})(memberUid={v}))")

    def roles_of_user(self, user_dn: str) -> list[str]:
        v = escape_filter_value(user_dn)
        found = self._c.search(
            self._c.base_dn,
            f"(&(objectClass={OC_ROLE})(!(objectClass={OC_SIMPLE_SECURITY}))(roleOccupant={v}))",
            attrs=[_GRANT_EXPIRY],
        )
        return [
            e.dn for e in found if not _expired_member(e, "roleOccupant", user_dn, self._clock())
        ]

    def assignment_entries(self) -> list[AssignmentEntry]:
        found = self._c.search(self._c.base_dn, f"(objectClass={OC_ACL})", attrs=[ATTR_ACL_ENTRY])
        return [AssignmentEntry(e.dn, e.texts(ATTR_ACL_ENTRY)) for e in found]

    def role_templates(self, role_dn: str) -> list[str]:
        entry = self._c.get(role_dn, [ATTR_ACL_TEMPLATE])
        return entry.texts(ATTR_ACL_TEMPLATE) if entry is not None else []

    def user_matches_filter(self, user_dn: str, filterstr: str) -> bool:
        try:
            return any(True for _ in self._c.search(user_dn, filterstr, Scope.BASE, attrs=["1.1"]))
        except DirectoryError:
            return False

    def search_targets(self, base_dn: str, filterstr: str, limit: int) -> list[str]:
        found: list[str] = []
        try:
            for entry in self._c.search(base_dn, filterstr, Scope.SUBTREE, attrs=["1.1"]):
                found.append(entry.dn)
                if len(found) >= limit:
                    break
        except DirectoryError:
            return found
        return found
