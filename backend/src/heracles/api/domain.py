"""Domain services shared by the object routers (registry, ACL, locks, snapshots).

``create_app`` stays domain-agnostic; :func:`install_domain` attaches a
:class:`Domain` to an application and the object routers reach it through
:data:`DomainDep`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, FastAPI, Request

from heracles.acl import AclEvaluator, AclResolver, LdapAclDirectory, ResolvedAcl, Rights
from heracles.api.deps import CurrentUser
from heracles.auth.sessions import Session
from heracles.core.locks import LockService
from heracles.core.snapshots import SnapshotService
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient
from heracles.objects import ObjectService, TypeInfo, TypeRegistry
from heracles.objects.model import Tab
from heracles.objects.policy import CompositeEvents, ObjectEvents
from heracles.objects.registry import EventsContext

_ACL_CACHE_KEY = "acl.resolved"


class TypeAclPolicy:
    """Object-layer access policy for one object type, backed by the ACL evaluator."""

    def __init__(
        self, evaluator: AclEvaluator, info: TypeInfo, registry: TypeRegistry | None = None
    ) -> None:
        self._ev = evaluator
        self._info = info
        self._registry = registry

    def for_type(self, type_name: str) -> TypeAclPolicy:
        """The same user's policy for another object type."""
        if self._registry is None:
            return self
        return TypeAclPolicy(self._ev, self._registry.get(type_name), self._registry)

    def _key(self, tab_name: str) -> str | None:
        tab = self._info.tab(tab_name)
        return self._info.acl_object(tab) if tab is not None else None

    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        key = self._key(tab)
        return key is not None and self._ev.can_read_attr(dn, key, attr)

    def can_write(self, dn: str, tab: str, attr: str) -> bool:
        key = self._key(tab)
        return key is not None and self._ev.can_write_attr(dn, key, attr)

    def can_create(self, type_name: str, base: str) -> bool:
        return self._ev.permissions(base, self._info.acl_object(self._info.main_tab)).create

    def can_delete(self, dn: str, type_name: str) -> bool:
        return self._ev.permissions(dn, self._info.acl_object(self._info.main_tab)).delete

    def can_move(self, dn: str) -> bool:
        return self._ev.permissions(dn, self._info.acl_object(self._info.main_tab)).move

    def tab_rights(self, dn: str, tab: type[Tab]) -> tuple[Rights, dict[str, Rights]]:
        """Object-level rights of a tab and per-attribute rights (for the ``acl`` block)."""
        key = self._info.acl_object(tab)
        object_rights = self._ev.permissions(dn, key)
        attributes = {a.name: self._ev.permissions(dn, key, a.name) for a in tab.attributes()}
        return object_rights, attributes


@dataclass(slots=True)
class Domain:
    """Domain services available to the object routers."""

    registry: TypeRegistry
    #: Users (normalised DNs) for whom ACLs are ignored (bootstrap administrators).
    admin_dns: frozenset[str] = frozenset()
    acl_target_limit: int = 100
    lock_services: dict[str, LockService] = field(default_factory=lambda: {})
    snapshot_services: dict[str, SnapshotService] = field(default_factory=lambda: {})
    #: Department types (registry names) used to build the navigation tree.
    department_types: Sequence[str] = (
        "department",
        "department_o",
        "department_l",
        "department_c",
        "department_dc",
    )

    def is_admin(self, user_dn: str) -> bool:
        return dnlib.normalize(user_dn) in self.admin_dns

    def locks(self, directory_id: str, directory: DirectoryClient) -> LockService:
        service = self.lock_services.get(directory_id)
        if service is None:
            service = self.lock_services[directory_id] = LockService(directory)
        return service

    def snapshots(self, directory_id: str, directory: DirectoryClient) -> SnapshotService:
        service = self.snapshot_services.get(directory_id)
        if service is None:
            service = self.snapshot_services[directory_id] = SnapshotService(directory)
        return service

    def category_tabs(self) -> Mapping[str, Sequence[str]]:
        """ACL category → tab keys, for category wildcards (``<cat>/0``)."""
        out: dict[str, list[str]] = {}
        for info in self.registry.list():
            keys = out.setdefault(info.acl_category, [])
            for tab in info.tabs:
                key = info.acl_object(tab).split("/", 1)[1]
                if key not in keys:
                    keys.append(key)
        return out

    def evaluator(self, user: CurrentUser) -> AclEvaluator:
        """ACL evaluator of the connected user (resolution cached in the session)."""
        resolved = _cached_resolution(user.session)
        if resolved is None:
            entry = user.directory.get(user.dn)
            attrs: dict[str, list[str]] = {}
            uid: str | None = None
            if entry is not None:
                attrs = {
                    k: [v.decode("utf-8", "replace") for v in vals]
                    for k, vals in entry.attrs.items()
                }
                uid = entry.text("uid")
            resolver = AclResolver(
                LdapAclDirectory(user.directory), target_limit=self.acl_target_limit
            )
            resolved = resolver.resolve(user.dn, uid=uid, user_attrs=attrs)
            user.session.cache[_ACL_CACHE_KEY] = resolved
        return AclEvaluator(
            resolved, category_tabs=self.category_tabs(), ignore_acl=self.is_admin(user.dn)
        )

    def service(self, user: CurrentUser, type_name: str) -> tuple[ObjectService, TypeAclPolicy]:
        """Object service for one type, enforcing the user's ACLs."""
        info = self.registry.get(type_name)
        policy = TypeAclPolicy(self.evaluator(user), info, self.registry)
        events = self.events(user)
        return ObjectService(user.directory, self.registry, policy=policy, events=events), policy

    def events(self, user: CurrentUser) -> ObjectEvents:
        """Object event hooks contributed by the plugins, for one request."""
        hooks = [
            factory(
                EventsContext(
                    user.directory, user.dn, user.client_ip, self.registry.settings.get(name)
                )
            )
            for name, factory in self.registry.events_factories
        ]
        return CompositeEvents(hooks)


def _cached_resolution(session: Session) -> ResolvedAcl | None:
    value = session.cache.get(_ACL_CACHE_KEY)
    return value if isinstance(value, ResolvedAcl) else None


def invalidate_acl_cache(session: Session) -> None:
    """Forget the cached ACL resolution (after ACL or membership changes)."""
    session.cache.pop(_ACL_CACHE_KEY, None)


def install_domain(app: FastAPI, domain: Domain) -> None:
    app.state.domain = domain


def get_domain(request: Request) -> Domain:
    domain: Domain = request.app.state.domain
    return domain


DomainDep = Annotated[Domain, Depends(get_domain)]

AdminCheck = Callable[[DirectoryClient, str], bool]
