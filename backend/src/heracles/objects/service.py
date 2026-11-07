"""Object service: load / list / create / update / delete on top of a directory."""

from __future__ import annotations

import base64
import binascii
import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from heracles.attributes import (
    JSON,
    AnyAttribute,
    DepartmentAttr,
    DisplayAttr,
    ListAttr,
    ObjectRefAttr,
    ValidationError,
)
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    Entry,
    NoSuchObjectError,
    Scope,
)
from heracles.objects import filters
from heracles.objects.diff import diff_modifications
from heracles.objects.errors import (
    ObjectConflictError,
    ObjectNotFoundError,
    ObjectValidationError,
    PermissionDeniedError,
)
from heracles.objects.model import Tab
from heracles.objects.policy import (
    TAB_ATTR,
    AccessPolicy,
    AllowAll,
    EventContext,
    NullEvents,
    ObjectEvents,
)
from heracles.objects.registry import TypeInfo, TypeRegistry
from heracles.objects.state import ObjectState, TabState

DEFAULT_LIMIT = 50

type Touched = list[tuple[str, str]]
type StrList = list[str]


@dataclass(frozen=True, slots=True)
class ListRow:
    """One listing row."""

    dn: str
    values: dict[str, str]
    locked: bool = False

    def to_json(self) -> dict[str, JSON]:
        return {"dn": self.dn, "values": dict(self.values), "locked": self.locked}


@dataclass(frozen=True, slots=True)
class ListPage:
    """A page of listing rows."""

    items: Sequence[ListRow] = field(default_factory=tuple)
    next_cursor: str | None = None
    total: int | None = None

    def to_json(self) -> dict[str, JSON]:
        return {
            "items": [r.to_json() for r in self.items],
            "next_cursor": self.next_cursor,
            "total": self.total,
        }


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode()


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return max(0, int(base64.urlsafe_b64decode(cursor.encode()).decode()))
    except (ValueError, binascii.Error):
        return 0


def department_of(dn: str, container_rdn: str) -> str:
    """Department DN of an object: its DN minus the RDN and the type container."""
    container = dnlib.parent(dn) or ""
    if container_rdn:
        suffix = dnlib.normalize(container_rdn) + ","
        if dnlib.normalize(container).startswith(suffix):
            parts = dnlib.split(container)
            return ",".join(parts[len(dnlib.split(container_rdn)) :])
    return container


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


class ObjectService:
    """CRUD on typed objects, enforcing validation, the access policy and hooks."""

    def __init__(
        self,
        directory: DirectoryClient,
        registry: TypeRegistry,
        *,
        policy: AccessPolicy | None = None,
        events: ObjectEvents | None = None,
    ) -> None:
        self.directory = directory
        self.registry = registry
        self.policy: AccessPolicy = policy or AllowAll()
        self.events: ObjectEvents = events or NullEvents()

    # ------------------------------------------------------------------ load

    def load(self, type_name: str, dn: str) -> ObjectState:
        """Read an entry and build its :class:`ObjectState`."""
        info = self.registry.get(type_name)
        entry = self.directory.get(dn)
        if entry is None:
            raise ObjectNotFoundError(dn)
        main = info.main_tab
        if not all(entry.has_object_class(c) for c in main.object_classes):
            raise ObjectNotFoundError(f"{dn} is not a {type_name}")
        tabs: dict[str, TabState] = {}
        for tab in info.tabs:
            active = (not tab.optional) or all(
                entry.has_object_class(c) for c in tab.object_classes
            )
            state = TabState(active=active)
            if active:
                state.values = self._read_values(info, tab, entry)
            tabs[tab.name] = state
        raw = {k: list(v) for k, v in entry.attrs.items()}
        return ObjectState.build(entry.dn, type_name, tabs, raw, entry.texts("objectClass"))

    def _read_values(self, info: TypeInfo, tab: type[Tab], entry: Entry) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for attr in tab.attributes():
            if not self.policy.can_read(entry.dn, tab.name, attr.name):
                continue
            if isinstance(attr, DepartmentAttr):
                values[attr.name] = department_of(entry.dn, info.type.rdn)
            elif attr.stored:
                values[attr.name] = attr.from_ldap(entry.get(attr.name))
        for attr in tab.attributes():
            if (
                isinstance(attr, DisplayAttr)
                and not attr.stored
                and attr.name not in values
                and self.policy.can_read(entry.dn, tab.name, attr.name)
            ):
                values[attr.name] = attr.compute(values)
        return values

    def state_json(self, state: ObjectState) -> dict[str, JSON]:
        """JSON of a state (``GET /objects/{type}/{dn}`` without ``acl``)."""
        return state.to_json(self.registry.get(state.type_name).tabs)

    # ------------------------------------------------------------------ list

    def list(
        self,
        type_name: str,
        base: str | None = None,
        scope: Scope = Scope.ONE,
        query: str | None = None,
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
        *,
        sort: str | None = None,
        descending: bool = False,
    ) -> ListPage:
        """List objects of a type below a department (``ONE``: its container, ``SUB``: tree)."""
        info = self.registry.get(type_name)
        base = base or self.directory.base_dn
        if scope == Scope.SUBTREE:
            search_base, ldap_scope = base, Scope.SUBTREE
        else:
            search_base, ldap_scope = dnlib.join(info.type.rdn, base), Scope.ONE
        search_attrs = self._search_attrs(info)
        flt = filters.and_(info.type.filter, filters.text_query(search_attrs, query or ""))
        wanted = list(dict.fromkeys([*info.type.columns, info.type.main_attr, info.type.name_attr]))
        try:
            entries = [
                e
                for e in self.directory.search(
                    search_base, flt, ldap_scope, [a for a in wanted if a]
                )
                if self.policy.can_read(e.dn, info.main_tab.name, info.type.main_attr)
            ]
        except NoSuchObjectError:
            entries = []

        sort_key = sort or info.type.main_attr
        entries.sort(
            key=lambda e: ((e.text(sort_key) or "").lower(), dnlib.normalize(e.dn)),
            reverse=descending,
        )
        offset = _decode_cursor(cursor)
        limit = max(1, limit)
        window = entries[offset : offset + limit]
        more = offset + limit < len(entries)
        return ListPage(
            items=[self._row(info, e) for e in window],
            next_cursor=_encode_cursor(offset + limit) if more else None,
            total=len(entries),
        )

    @staticmethod
    def _search_attrs(info: TypeInfo) -> StrList:
        names = [*info.type.search_attrs] or [
            *info.type.columns,
            info.type.main_attr,
            info.type.name_attr,
        ]
        out: list[str] = []
        for name in dict.fromkeys(n for n in names if n):
            attr = info.find_attribute(name)
            if attr is None or attr.stored:
                out.append(name)
        return out

    def _row(self, info: TypeInfo, entry: Entry) -> ListRow:
        keys = [*info.type.columns] or [info.type.main_attr]
        values: dict[str, str] = {}
        for key in keys:
            if not self.policy.can_read(entry.dn, info.main_tab.name, key):
                continue
            attr = info.find_attribute(key)
            if attr is not None and not attr.stored:
                continue
            if attr is not None and not attr.write_only and attr.kind not in ("image", "file"):
                shown = attr.to_json(attr.from_ldap(entry.get(key)))
            else:
                shown = ", ".join(_text(v) for v in entry.get(key)) if attr is None else None
            if isinstance(shown, list):
                text = ", ".join(str(s) for s in shown)
            else:
                text = "" if shown is None else str(shown)
            values[key] = text
        return ListRow(entry.dn, values)

    # ---------------------------------------------------------------- create

    def create(self, type_name: str, base: str, tabs_json: Mapping[str, Any]) -> str:
        """Create an object below department ``base``; returns its DN."""
        info = self.registry.get(type_name)
        if not self.policy.can_create(type_name, base):
            raise PermissionDeniedError(f"cannot create {type_name} in {base}")
        initial: dict[str, TabState] = {}
        for tab in info.tabs:
            state = TabState(active=not tab.optional)
            if state.active:
                state.values = self._defaults(tab)
            initial[tab.name] = state
        errors: dict[str, str] = {}
        new, touched = self._apply(info, initial, tabs_json, errors, creating=True)
        dept = self._department_attr(info)
        if dept is not None:
            new[dept[0].name].values[dept[1].name] = base
        self._compute(info, new)
        self._validate(info, new, None, errors, creating=True)

        main_tab = info.main_tab
        main_value = new[main_tab.name].values.get(info.type.main_attr)
        if not isinstance(main_value, str) or not main_value:
            errors.setdefault(
                f"{main_tab.name}.{info.type.main_attr}", _("This field is required.")
            )
        elif not errors:
            self._check_unique(info, base, main_value, None, errors)
        if errors:
            raise ObjectValidationError(errors)
        assert isinstance(main_value, str)

        # not dnlib.join for the RDN: it would strip an escaped trailing space
        rdn = f"{info.type.main_attr}={dnlib.escape_rdn_value(main_value)}"
        dn = f"{rdn},{dnlib.join(info.type.rdn, base)}"
        self._check_writes(dn, touched)

        classes: list[str] = []
        attrs: dict[str, list[bytes]] = {}
        for tab in info.tabs:
            state = new[tab.name]
            if not state.active:
                continue
            for oc in tab.object_classes:
                if oc.lower() not in {c.lower() for c in classes}:
                    classes.append(oc)
            for attr in tab.attributes():
                if attr.stored and attr.name in state.values:
                    raw = attr.to_ldap(state.values[attr.name])
                    if raw:
                        attrs[attr.name] = raw
        attrs["objectClass"] = [c.encode() for c in classes]

        after = ObjectState.build(dn, type_name, new, attrs, classes)
        ctx = EventContext(type_name, dn, None, after)
        self.events.pre_create(ctx)
        try:
            self.directory.add(dn, attrs)
        except AlreadyExistsError:
            raise ObjectConflictError(f"{dn} already exists") from None
        self.events.post_create(ctx)
        return dn

    @staticmethod
    def _defaults(tab: type[Tab]) -> dict[str, Any]:
        return {a.name: a.default for a in tab.attributes()}

    # ---------------------------------------------------------------- update

    def update(self, type_name: str, dn: str, tabs_json: Mapping[str, Any]) -> ObjectState:
        """Apply a PATCH-like change; one ``modify`` plus an optional rename."""
        info = self.registry.get(type_name)
        state = self.load(type_name, dn)
        errors: dict[str, str] = {}
        new, touched = self._apply(info, state.tabs, tabs_json, errors, creating=False)
        self._compute(info, new)
        self._validate(info, new, state, errors, creating=False)

        main_name = info.type.main_attr
        old_main = state.original[info.main_tab.name].values.get(main_name)
        new_main = new[info.main_tab.name].values.get(main_name)
        dept = self._department_attr(info)
        old_base = department_of(dn, info.type.rdn)
        new_base = old_base
        if dept is not None:
            new_base = new[dept[0].name].values.get(dept[1].name) or old_base
        renamed = (isinstance(new_main, str) and new_main != old_main) or dnlib.normalize(
            new_base
        ) != dnlib.normalize(old_base)
        if renamed and isinstance(new_main, str) and not errors:
            self._check_unique(info, new_base, new_main, dn, errors)
        if errors:
            raise ObjectValidationError(errors)
        self._check_writes(dn, touched)

        mods = diff_modifications(
            info.tabs, main_name, state.raw, state.object_classes, state.original, new
        )
        after = ObjectState.build(dn, type_name, new, state.raw, state.object_classes)
        ctx = EventContext(type_name, dn, state, after, mods)
        self.events.pre_modify(ctx)
        if mods:
            self.directory.modify(dn, mods)
        new_dn = dn
        if renamed:
            new_rdn = (
                f"{main_name}={dnlib.escape_rdn_value(str(new_main))}"
                if isinstance(new_main, str) and new_main != old_main
                else dnlib.rdn(dn)
            )
            superior = (
                dnlib.join(info.type.rdn, new_base)
                if dnlib.normalize(new_base) != dnlib.normalize(old_base)
                else None
            )
            try:
                new_dn = self.directory.rename(dn, new_rdn, superior)
            except AlreadyExistsError:
                raise ObjectConflictError(f"{new_rdn} already exists") from None
        result = self.load(type_name, new_dn)
        self.events.post_modify(EventContext(type_name, new_dn, state, result, mods))
        return result

    # ---------------------------------------------------------------- delete

    def delete(self, type_name: str, dn: str) -> None:
        """Delete an object."""
        self.registry.get(type_name)
        state = self.load(type_name, dn)
        if not self.policy.can_delete(dn, type_name):
            raise PermissionDeniedError(f"cannot delete {dn}")
        ctx = EventContext(type_name, dn, state, None)
        self.events.pre_delete(ctx)
        try:
            self.directory.delete(dn)
        except NoSuchObjectError:
            raise ObjectNotFoundError(dn) from None
        self.events.post_delete(ctx)

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _department_attr(info: TypeInfo) -> tuple[type[Tab], AnyAttribute] | None:
        for tab in info.tabs:
            for attr in tab.attributes():
                if isinstance(attr, DepartmentAttr):
                    return tab, attr
        return None

    def _apply(
        self,
        info: TypeInfo,
        base_tabs: Mapping[str, TabState],
        tabs_json: Mapping[str, Any],
        errors: dict[str, str],
        *,
        creating: bool,
    ) -> tuple[dict[str, TabState], Touched]:
        """Merge JSON into a copy of ``base_tabs``; returns it and the (tab, attr) writes."""
        new = copy.deepcopy(dict(base_tabs))
        touched: list[tuple[str, str]] = []
        for tab_name, data in tabs_json.items():
            tab = info.tab(tab_name)
            if tab is None:
                errors[tab_name] = _("Unknown tab.")
                continue
            if not isinstance(data, Mapping):
                errors[tab_name] = _("Expected an object.")
                continue
            body: Mapping[str, Any] = data  # pyright: ignore[reportUnknownVariableType]
            state = new[tab_name]
            wanted = body.get("active", state.active)
            if not isinstance(wanted, bool):
                errors[tab_name] = _("'active' must be a boolean.")
                continue
            if not tab.optional and not wanted:
                errors[tab_name] = _("The main tab cannot be deactivated.")
                continue
            if wanted != state.active:
                touched.append((tab_name, TAB_ATTR))
                state.active = wanted
                state.values = self._defaults(tab) if wanted else {}
            values: object = body.get("values") or {}
            if not isinstance(values, Mapping):
                errors[tab_name] = _("'values' must be an object.")
                continue
            if values and not state.active:
                errors[tab_name] = _("The tab is not active.")
                continue
            for attr_name, raw in values.items():  # pyright: ignore[reportUnknownVariableType]
                self._apply_value(tab, state, str(attr_name), raw, errors, touched, creating)  # pyright: ignore[reportUnknownArgumentType]
        return new, touched

    @staticmethod
    def _apply_value(
        tab: type[Tab],
        state: TabState,
        attr_name: str,
        raw: object,
        errors: dict[str, str],
        touched: Touched,
        creating: bool,
    ) -> None:
        key = f"{tab.name}.{attr_name}"
        attr = tab.attribute(attr_name)
        if attr is None:
            errors[key] = _("Unknown attribute.")
            return
        if isinstance(attr, DisplayAttr):
            return  # computed
        try:
            value = attr.from_json(raw)
        except ValidationError as exc:
            errors[key] = exc.message
            return
        current = state.values.get(attr_name)
        if attr.write_only:
            if value is not None:
                touched.append((tab.name, attr_name))
                state.values[attr_name] = value
            return
        if value == current:
            return
        if attr.readonly and not creating:
            errors[key] = _("This field is read-only.")
            return
        touched.append((tab.name, attr_name))
        state.values[attr_name] = value

    @staticmethod
    def _compute(info: TypeInfo, tabs: dict[str, TabState]) -> None:
        for tab in info.tabs:
            state = tabs[tab.name]
            if not state.active:
                continue
            for attr in tab.attributes():
                if isinstance(attr, DisplayAttr):
                    state.values[attr.name] = attr.compute(state.values)
            tab.compute(state.values)

    def _validate(
        self,
        info: TypeInfo,
        tabs: Mapping[str, TabState],
        old: ObjectState | None,
        errors: dict[str, str],
        *,
        creating: bool,
    ) -> None:
        for tab in info.tabs:
            state = tabs[tab.name]
            if not state.active:
                continue
            for req in tab.requires:
                if req not in tabs or not tabs[req].active:
                    errors.setdefault(tab.name, _("Requires the '{tab}' tab.").format(tab=req))
            for attr in tab.attributes():
                key = f"{tab.name}.{attr.name}"
                if key in errors or isinstance(attr, DisplayAttr):
                    continue
                value = state.values.get(attr.name)
                problems = attr.validate(value)
                if creating and attr.write_only and attr.required and not value:
                    problems = [_("This field is required.")]
                if problems:
                    errors[key] = problems[0]
                    continue
                self._check_refs(attr, value, old, tab.name, key, errors)

    def _check_refs(
        self,
        attr: AnyAttribute,
        value: object,
        old: ObjectState | None,
        tab_name: str,
        key: str,
        errors: dict[str, str],
    ) -> None:
        targets: Sequence[object]
        if isinstance(attr, ObjectRefAttr):
            targets = [value]
        elif isinstance(attr, ListAttr) and isinstance(attr.item, ObjectRefAttr):  # pyright: ignore[reportUnknownMemberType]
            targets = cast("list[object]", value) if isinstance(value, list) else []
        else:
            return
        previous: object = None
        if old is not None and tab_name in old.original:
            previous = old.original[tab_name].values.get(attr.name)
        known = {
            dnlib.normalize(d)
            for d in (cast("list[object]", previous) if isinstance(previous, list) else [previous])
            if isinstance(d, str)
        }
        for target in targets:
            if not isinstance(target, str) or dnlib.normalize(target) in known:
                continue
            if self.directory.get(target, ["objectClass"]) is None:
                errors[key] = _("Referenced object does not exist: {dn}").format(dn=target)
                return

    def _check_unique(
        self,
        info: TypeInfo,
        base: str,
        value: str,
        exclude_dn: str | None,
        errors: dict[str, str],
    ) -> None:
        flt = filters.and_(info.type.filter, filters.equals(info.type.main_attr, value))
        try:
            found = self.directory.search(base, flt, Scope.SUBTREE, [info.type.main_attr])
            others = [
                e
                for e in found
                if exclude_dn is None or dnlib.normalize(e.dn) != dnlib.normalize(exclude_dn)
            ]
        except NoSuchObjectError:
            return
        if others:
            errors[f"{info.main_tab.name}.{info.type.main_attr}"] = _("Already in use.")

    def _check_writes(self, dn: str, touched: Sequence[tuple[str, str]]) -> None:
        for tab, attr in touched:
            if not self.policy.can_write(dn, tab, attr):
                raise PermissionDeniedError(f"cannot write {tab}.{attr} on {dn}")


__all__ = ["ListPage", "ListRow", "ObjectService", "department_of"]
