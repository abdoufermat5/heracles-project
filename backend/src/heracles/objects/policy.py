"""Extension points: access policy and object lifecycle events."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from heracles.ldap.client import Modification
from heracles.objects.state import ObjectState

TAB_ATTR = "*"
"""Pseudo attribute name used for tab-level checks (activation/deactivation)."""


class AccessPolicy(Protocol):
    """Authorisation hook; the ACL engine implements it."""

    def can_read(self, dn: str, tab: str, attr: str) -> bool: ...

    def can_write(self, dn: str, tab: str, attr: str) -> bool: ...

    def can_create(self, type_name: str, base: str) -> bool: ...

    def can_delete(self, dn: str, type_name: str) -> bool: ...


@runtime_checkable
class TypedPolicy(Protocol):
    """A policy able to answer for another object type (cross-object side effects)."""

    def for_type(self, type_name: str) -> AccessPolicy: ...


class AllowAll:
    """Default policy."""

    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        return True

    def can_write(self, dn: str, tab: str, attr: str) -> bool:
        return True

    def can_create(self, type_name: str, base: str) -> bool:
        return True

    def can_delete(self, dn: str, type_name: str) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class EventContext:
    """What a hook receives."""

    type_name: str
    dn: str
    before: ObjectState | None = None
    after: ObjectState | None = None
    changes: Sequence[Modification] = ()


class ObjectEvents(Protocol):
    """Lifecycle hooks. ``pre_*`` may raise to veto the operation."""

    def pre_create(self, ctx: EventContext) -> None: ...

    def post_create(self, ctx: EventContext) -> None: ...

    def pre_modify(self, ctx: EventContext) -> None: ...

    def post_modify(self, ctx: EventContext) -> None: ...

    def pre_delete(self, ctx: EventContext) -> None: ...

    def post_delete(self, ctx: EventContext) -> None: ...


class NullEvents:
    """No-op events; subclass and override what is needed."""

    def pre_create(self, ctx: EventContext) -> None:
        pass

    def post_create(self, ctx: EventContext) -> None:
        pass

    def pre_modify(self, ctx: EventContext) -> None:
        pass

    def post_modify(self, ctx: EventContext) -> None:
        pass

    def pre_delete(self, ctx: EventContext) -> None:
        pass

    def post_delete(self, ctx: EventContext) -> None:
        pass


class CompositeEvents:
    """Calls several :class:`ObjectEvents` in order (a ``pre_*`` veto stops the chain)."""

    def __init__(self, events: Sequence[ObjectEvents]) -> None:
        self.events = list(events)

    def pre_create(self, ctx: EventContext) -> None:
        for e in self.events:
            e.pre_create(ctx)

    def post_create(self, ctx: EventContext) -> None:
        for e in self.events:
            e.post_create(ctx)

    def pre_modify(self, ctx: EventContext) -> None:
        for e in self.events:
            e.pre_modify(ctx)

    def post_modify(self, ctx: EventContext) -> None:
        for e in self.events:
            e.post_modify(ctx)

    def pre_delete(self, ctx: EventContext) -> None:
        for e in self.events:
            e.pre_delete(ctx)

    def post_delete(self, ctx: EventContext) -> None:
        for e in self.events:
            e.post_delete(ctx)
