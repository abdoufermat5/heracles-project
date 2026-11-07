"""LDAP-backed implementation of :class:`AclDirectory`."""

from __future__ import annotations

from heracles.acl._compat import (
    ATTR_ACL_ENTRY,
    ATTR_ACL_TEMPLATE,
    OC_ACL,
    OC_GROUP_OF_NAMES,
    OC_POSIX_GROUP,
    OC_ROLE,
)
from heracles.acl.resolver import AssignmentEntry, escape_filter_value
from heracles.ldap.client import DirectoryClient, DirectoryError, Scope


class LdapAclDirectory:
    """Runs the ACL lookups against a :class:`DirectoryClient`."""

    def __init__(self, client: DirectoryClient) -> None:
        self._c = client

    def _dns(self, filterstr: str) -> list[str]:
        return [e.dn for e in self._c.search(self._c.base_dn, filterstr, attrs=["1.1"])]

    def groups_of_user(self, user_dn: str) -> list[str]:
        v = escape_filter_value(user_dn)
        return self._dns(f"(&(objectClass={OC_GROUP_OF_NAMES})(member={v}))")

    def posix_groups_by_uid(self, uid: str) -> list[str]:
        v = escape_filter_value(uid)
        return self._dns(f"(&(objectClass={OC_POSIX_GROUP})(memberUid={v}))")

    def roles_of_user(self, user_dn: str) -> list[str]:
        v = escape_filter_value(user_dn)
        return self._dns(f"(&(objectClass={OC_ROLE})(roleOccupant={v}))")

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
