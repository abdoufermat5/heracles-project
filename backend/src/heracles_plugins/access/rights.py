"""Who may change a grant: the rights of the normal editors of the holding entry."""

from __future__ import annotations

from heracles.api.deps import CurrentUser
from heracles.api.domain import Domain
from heracles.api.v2.admin import ASSIGNMENT_KEY, rights_of
from heracles.auth.api_tokens import SESSION_KEY
from heracles.ldap.client import Entry
from heracles.ldap.filter import matches as filter_matches
from heracles.objects.registry import TypeInfo, TypeRegistry
from heracles_plugins.access.grants import ACL_KIND


def holder_types(registry: TypeRegistry, entry: Entry, attr: str) -> list[tuple[TypeInfo, str]]:
    """``(type, tab name)`` of the registered types of ``entry`` that edit ``attr``."""
    out: list[tuple[TypeInfo, str]] = []
    for info in registry.list():
        try:
            if not filter_matches(entry, info.type.filter):
                continue
        except ValueError:
            continue
        for tab in info.tabs:
            if any(a.name.lower() == attr.lower() for a in tab.attributes()):
                out.append((info, tab.name))
                break
    return out


def can_read_grants(user: CurrentUser, domain: Domain, entry: Entry, kind: str) -> bool:
    if domain.is_admin(user.dn):
        return True
    if kind == ACL_KIND:
        return rights_of(user, domain, ASSIGNMENT_KEY, entry.dn).read
    for info, tab in holder_types(domain.registry, entry, kind):
        _service, policy = domain.service(user, info.name)
        if policy.can_read(entry.dn, tab, kind):
            return True
    return False


def can_change_grants(user: CurrentUser, domain: Domain, entry: Entry, kind: str) -> bool:
    """Whoever may edit the membership (or the ACL assignments) may date it.

    An API token request always goes through the ACL evaluator, where its scope caps the
    rights (a ``write`` token gets no write on ACL assignments, administrator owner or not).
    """
    if domain.is_admin(user.dn) and SESSION_KEY not in user.session.cache:
        return True
    if kind == ACL_KIND:
        return rights_of(user, domain, ASSIGNMENT_KEY, entry.dn).write
    for info, tab in holder_types(domain.registry, entry, kind):
        _service, policy = domain.service(user, info.name)
        if policy.can_write(entry.dn, tab, kind):
            return True
    return False
