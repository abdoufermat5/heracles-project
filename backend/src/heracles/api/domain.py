"""Domain services shared by the object routers (registry, ACL, locks, snapshots).

``create_app`` stays domain-agnostic; :func:`install_domain` attaches a
:class:`Domain` to an application and the object routers reach it through
:data:`DomainDep`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Annotated, cast

from fastapi import Depends, FastAPI, Request

from heracles.acl import AclEvaluator, AclResolver, LdapAclDirectory, ResolvedAcl, Rights
from heracles.api.deps import CurrentUser
from heracles.auth.sessions import Session
from heracles.core.audit import AuditSink
from heracles.core.locks import LockService
from heracles.core.snapshots import SnapshotService
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient
from heracles.objects import ObjectService, TypeInfo, TypeRegistry
from heracles.objects.activation import PluginManager
from heracles.objects.listing_cache import ListingCache, ListingScope
from heracles.objects.listing_epochs import ListingEpochs
from heracles.objects.model import Tab
from heracles.objects.policy import CompositeEvents, ObjectEvents
from heracles.objects.registry import EventsContext

#: How long a session keeps its ACL resolution before resolving again. Roles, assignments and
#: group memberships changed by someone else (a revocation, say) apply to a live session
#: within this time instead of at its next login.
ACL_CACHE_SECONDS = 60.0

_ACL_CACHE_KEY = "acl.resolved"
#: How often a process compares its enabled plugins with the shared app database.
PLUGIN_SYNC_SECONDS = 2.0


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

    def permissions(self, dn: str, object_key: str, attribute: str = "") -> Rights:
        """Effective rights of the user, for the ACL assignment guard of the object layer."""
        return self._ev.permissions(dn, object_key, attribute)

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
    #: Plugin activation (``None`` when the registry was supplied ready-made).
    plugins: PluginManager | None = None
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
    #: Listing snapshots shared by the requests of this process (one set per session).
    listings: ListingCache = field(default_factory=ListingCache)
    #: Per-session change counters shared with the other replicas (``None``: single process).
    epochs: ListingEpochs | None = None
    #: When this process last compared its plugins with the app database (monotonic).
    _plugins_checked: float = field(default=float("-inf"), repr=False, compare=False)

    def sync_plugins(self, interval: float = PLUGIN_SYNC_SECONDS) -> TypeRegistry:
        """The current registry, rebuilt first when another process switched a plugin.

        The check (one small query of the app database) runs at most every ``interval``
        seconds; it is a no-op when the plugins are not configurable.
        """
        manager = self.plugins
        if manager is not None:
            now = time.monotonic()
            if now - self._plugins_checked >= interval:
                self._plugins_checked = now
                fresh = manager.refresh()
                if fresh is not None:
                    self.swap_registry(fresh)
        return self.registry

    def swap_registry(self, registry: TypeRegistry) -> None:
        """Serve ``registry`` from now on (plugin switched here or in another process)."""
        self.registry = registry
        own = registry.settings.get("acl_admin")
        if own is not None and hasattr(own, "registry"):
            own.registry = registry  # trigger settings follow the live registry

    @property
    def audit(self) -> AuditSink:
        """Audit sink bound to this domain's registry (no-op without the audit plugin)."""
        return AuditSink(self.registry)

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
        """ACL evaluator of the connected user (resolution cached in the session).

        One evaluator serves the whole request, so its permission cache is shared by
        every service and check of that request. It is rebuilt when the session's
        resolution was invalidated in between (ACL or membership change).
        """
        resolved = _cached_resolution(user.session)
        memo = cast("tuple[ResolvedAcl, AclEvaluator] | None", user.acl)
        if memo is not None and memo[0] is resolved:
            return memo[1]
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
        evaluator = AclEvaluator(
            resolved, category_tabs=self.category_tabs(), ignore_acl=self.is_admin(user.dn)
        )
        # ``CurrentUser`` is frozen: the memo lives in a field only this method writes.
        object.__setattr__(user, "acl", (resolved, evaluator))
        return evaluator

    def service(self, user: CurrentUser, type_name: str) -> tuple[ObjectService, TypeAclPolicy]:
        """Object service for one type, enforcing the user's ACLs.

        Listings reuse the user's snapshots (see :class:`ListingCache`); they are tied to
        the ACL resolution the evaluator was built from.
        """
        info = self.registry.get(type_name)
        evaluator = self.evaluator(user)
        policy = TypeAclPolicy(evaluator, info, self.registry)
        events = self.events(user)
        memo = cast("tuple[ResolvedAcl, AclEvaluator]", user.acl)
        epochs = self.epochs
        sid = user.session.id
        listings = ListingScope(
            self.listings,
            sid,
            memo[0],
            (lambda: epochs.current(sid)) if epochs is not None else None,
        )
        service = ObjectService(
            user.directory, self.registry, policy=policy, events=events, listings=listings
        )
        return service, policy

    def invalidate_listings(self, session_id: str) -> None:
        """Drop the listing snapshots of one session (the raw id, as in ``Session.id``)."""
        self.listings.invalidate(session_id)
        if self.epochs is not None:
            self.epochs.bump(session_id)  # the snapshots other replicas hold go stale too

    def events(self, user: CurrentUser) -> ObjectEvents:
        """Object event hooks contributed by the plugins, for one request.

        The same instance is reused for the whole request, so the output triggers and
        hooks collected during a write can be read back with :meth:`collected`.
        """
        if user.events is None:
            hooks = [
                factory(
                    EventsContext(
                        user.directory, user.dn, user.client_ip, self.registry.settings.get(name)
                    )
                )
                for name, factory in self.registry.events_factories
            ]
            # ``CurrentUser`` is frozen: the memo lives in a field only this method writes.
            object.__setattr__(user, "events", CompositeEvents(hooks))
        return cast("ObjectEvents", user.events)

    def collected(self, user: CurrentUser) -> tuple[list[str], list[str]]:
        """Warnings and messages the events of this request collected."""
        events = user.events
        if isinstance(events, CompositeEvents):
            return events.collected()
        return [], []


def _cached_resolution(session: Session) -> ResolvedAcl | None:
    value = session.cache.get(_ACL_CACHE_KEY)
    if not isinstance(value, ResolvedAcl):
        return None
    if time.monotonic() - value.resolved_at > ACL_CACHE_SECONDS:
        return None  # a change made by another administrator reaches the session in time
    return value


def invalidate_acl_cache(session: Session) -> None:
    """Forget the cached ACL resolution (after ACL or membership changes).

    The session's listing snapshots die with it: they are bound to the resolution they
    were filtered with, and the next request resolves the ACLs again.
    """
    session.cache.pop(_ACL_CACHE_KEY, None)


def install_domain(app: FastAPI, domain: Domain) -> None:
    app.state.domain = domain
    state = getattr(app.state, "heracles", None)
    if state is not None and state.database is not None and domain.epochs is None:
        domain.epochs = ListingEpochs(state.database)
    if state is not None:
        # follow the live registry: plugins can be switched on and off from the console
        state.audit.attach(lambda: domain.registry)


def get_domain(request: Request) -> Domain:
    domain: Domain = request.app.state.domain
    domain.sync_plugins()
    return domain


DomainDep = Annotated[Domain, Depends(get_domain)]

AdminCheck = Callable[[DirectoryClient, str], bool]
