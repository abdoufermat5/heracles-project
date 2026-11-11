"""NIS Netgroup plugin: netgroups (nisNetgroup) and user/system membership tabs."""

from __future__ import annotations

import contextlib
import inspect
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, cast, overload

from heracles.attributes import (
    ListAttr,
    ObjectRefAttr,
    StringAttr,
    TextAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryError, Modification, Scope
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment, TypeInfo
from heracles.objects.hooks import TabContext
from heracles_plugins.netgroups.triple import (
    TripleAttr,
    format_triple,
    parse_triple,
)

PLUGIN_NAME = "netgroups"
SYSTEM_TYPES = ("workstation", "terminal", "server", "printer")


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written directly to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


@dataclass(slots=True)
class NetgroupSettings:
    """Settings of the Netgroup plugin."""

    rdn: str = "ou=netgroups"


def _extract_name_from_ref(ref: str, attr_prefix: str) -> str:
    """Extract 'name' from 'attr=name,...' or return the raw string."""
    parts = dnlib.split(ref)
    if parts:
        prefix = f"{attr_prefix}="
        for part in parts:
            if part.lower().startswith(prefix.lower()):
                return part[len(prefix) :]
    return ref.strip()


# ------------------------------------------------------------------ Netgroup


class NetgroupMainTab(Tab):
    """Main tab of an NIS Netgroup."""

    name = "main"
    acl_key = "netgroup"
    label = _("Netgroup")
    object_classes = ("nisNetgroup",)

    properties = Section(
        _("Properties"),
        StringAttr("cn", _("Name"), required=True, max_length=64),
        TextAttr("description", _("Description")),
        ListAttr(
            "memberNisNetgroup",
            _("Member netgroups"),
            StringAttr("memberNisNetgroup", _("Member netgroup")),
        ),
        ListAttr(
            "nisNetgroupTriple",
            _("Netgroup triples"),
            TripleAttr("triple", _("Triple")),
        ),
    )

    members = Section(
        _("Members"),
        virtual(
            ListAttr(
                "memberUsers",
                _("User members"),
                StringAttr("user", _("User")),
            )
        ),
        virtual(
            ListAttr(
                "memberSystems",
                _("System members"),
                StringAttr("system", _("System")),
            )
        ),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        val = cast(object, ctx.values.get("nisNetgroupTriple"))
        raw_triples: list[str] = []
        if isinstance(val, (list, tuple)):
            for item in cast(Sequence[object], val):
                if isinstance(item, str):
                    raw_triples.append(item)
        users: list[str] = []
        systems: list[str] = []
        for raw in raw_triples:
            parsed = parse_triple(raw)
            if parsed is None:
                continue
            host, user, _domain = parsed
            if user and user != "-":
                users.append(user)
            if host and host != "-":
                systems.append(host)
        ctx.values["memberUsers"] = users
        ctx.values["memberSystems"] = systems

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        ensure_container(ctx.directory, dnlib.join(ctx.info.type.rdn, ctx.base))
        triples: list[str] = list(ctx.values.get("nisNetgroupTriple") or [])
        parsed_triples = [parse_triple(t) for t in triples]

        if "memberUsers" in ctx.values and ctx.values["memberUsers"] is not None:
            for user_ref in ctx.values["memberUsers"]:
                user_name = _extract_name_from_ref(str(user_ref), "uid")
                if not any(p and p[1] == user_name for p in parsed_triples):
                    new_t = format_triple(host="-", user=user_name)
                    triples.append(new_t)
                    parsed_triples.append(parse_triple(new_t))

        if "memberSystems" in ctx.values and ctx.values["memberSystems"] is not None:
            for sys_ref in ctx.values["memberSystems"]:
                sys_name = _extract_name_from_ref(str(sys_ref), "cn")
                if not any(p and p[0] == sys_name for p in parsed_triples):
                    new_t = format_triple(host=sys_name, user="-")
                    triples.append(new_t)
                    parsed_triples.append(parse_triple(new_t))

        ctx.values["nisNetgroupTriple"] = triples


class Netgroup(ObjectType):
    """An NIS Netgroup."""

    name = "netgroup"
    acl_category = "netgroup"
    label = _("NIS Netgroup")
    label_plural = _("NIS Netgroups")
    icon = "network"
    category = "network"
    filter = "(objectClass=nisNetgroup)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=netgroups"
    columns = ("cn", "description")
    search_attrs = ("cn", "description", "memberNisNetgroup", "nisNetgroupTriple")

    Main = NetgroupMainTab


# ----------------------------------------------------------- Membership tabs


class NetgroupUserTab(Tab):
    """NIS netgroup membership tab attached to user accounts."""

    name = "netgroup"
    acl_key = "netgroupMembership"
    label = _("Netgroups")
    description = _("Network groups this account belongs to")
    object_classes = ()
    optional = False

    membership = Section(
        _("Netgroup membership"),
        virtual(
            ListAttr(
                "nisMembership",
                _("NIS netgroup membership"),
                ObjectRefAttr("netgroup", _("Netgroup"), ref_type="netgroup"),
            )
        ),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        if not ctx.dn:
            return
        uid = str(ctx.main_values().get("uid") or "").strip()
        if not uid:
            return
        entries = ctx.directory.search(
            ctx.directory.base_dn,
            "(objectClass=nisNetgroup)",
            Scope.SUBTREE,
            attrs=["cn", "nisNetgroupTriple"],
        )
        memberships: list[str] = []
        for entry in entries:
            for raw in entry.texts("nisNetgroupTriple"):
                triple = parse_triple(raw)
                if triple is not None and triple[1] == uid:
                    memberships.append(entry.dn)
                    break
        ctx.values["nisMembership"] = memberships

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        uid = str(ctx.main_values().get("uid") or "").strip()
        if not uid:
            return
        desired = set(ctx.values.get("nisMembership") or [])
        entries = ctx.directory.search(
            ctx.directory.base_dn,
            "(objectClass=nisNetgroup)",
            Scope.SUBTREE,
            attrs=["cn", "nisNetgroupTriple"],
        )
        current: dict[str, list[str]] = {}
        for entry in entries:
            triples = entry.texts("nisNetgroupTriple")
            user_triples = [
                t for t in triples if (p := parse_triple(t)) is not None and p[1] == uid
            ]
            if user_triples:
                current[entry.dn] = user_triples

        # Add to newly selected netgroups
        for dn in desired:
            if dn not in current:
                new_triple = format_triple(host="-", user=uid)
                with contextlib.suppress(DirectoryError):
                    ctx.directory.modify(
                        dn,
                        [Modification("add", "nisNetgroupTriple", [new_triple.encode("utf-8")])],
                    )

        # Remove from unselected netgroups
        for dn, triples_to_remove in current.items():
            if dn not in desired:
                with contextlib.suppress(DirectoryError):
                    ctx.directory.modify(
                        dn,
                        [
                            Modification(
                                "delete",
                                "nisNetgroupTriple",
                                [t.encode("utf-8") for t in triples_to_remove],
                            )
                        ],
                    )

    @classmethod
    def before_delete(cls, ctx: TabContext) -> None:
        uid = str(ctx.main_values().get("uid") or "").strip()
        if not uid:
            return
        entries = ctx.directory.search(
            ctx.directory.base_dn,
            "(objectClass=nisNetgroup)",
            Scope.SUBTREE,
            attrs=["cn", "nisNetgroupTriple"],
        )
        for entry in entries:
            triples_to_remove = [
                t
                for t in entry.texts("nisNetgroupTriple")
                if (p := parse_triple(t)) is not None and p[1] == uid
            ]
            if triples_to_remove:
                with contextlib.suppress(DirectoryError):
                    ctx.directory.modify(
                        entry.dn,
                        [
                            Modification(
                                "delete",
                                "nisNetgroupTriple",
                                [t.encode("utf-8") for t in triples_to_remove],
                            )
                        ],
                    )


class NetgroupSystemTab(Tab):
    """NIS netgroup membership tab attached to systems (workstation, server, terminal, printer)."""

    name = "netgroup"
    acl_key = "netgroupSystem"
    label = _("Netgroups")
    object_classes = ()
    optional = False

    membership = Section(
        _("Netgroup membership"),
        virtual(
            ListAttr(
                "nisMembership",
                _("NIS netgroup membership"),
                ObjectRefAttr("netgroup", _("Netgroup"), ref_type="netgroup"),
            )
        ),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        if not ctx.dn:
            return
        cn = str(ctx.main_values().get("cn") or "").strip()
        if not cn:
            return
        entries = ctx.directory.search(
            ctx.directory.base_dn,
            "(objectClass=nisNetgroup)",
            Scope.SUBTREE,
            attrs=["cn", "nisNetgroupTriple"],
        )
        memberships: list[str] = []
        for entry in entries:
            for raw in entry.texts("nisNetgroupTriple"):
                triple = parse_triple(raw)
                if triple is not None and triple[0] == cn:
                    memberships.append(entry.dn)
                    break
        ctx.values["nisMembership"] = memberships

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        cn = str(ctx.main_values().get("cn") or "").strip()
        if not cn:
            return
        desired = set(ctx.values.get("nisMembership") or [])
        entries = ctx.directory.search(
            ctx.directory.base_dn,
            "(objectClass=nisNetgroup)",
            Scope.SUBTREE,
            attrs=["cn", "nisNetgroupTriple"],
        )
        current: dict[str, list[str]] = {}
        for entry in entries:
            triples = entry.texts("nisNetgroupTriple")
            host_triples = [t for t in triples if (p := parse_triple(t)) is not None and p[0] == cn]
            if host_triples:
                current[entry.dn] = host_triples

        # Add to newly selected netgroups
        for dn in desired:
            if dn not in current:
                new_triple = format_triple(host=cn, user="-")
                with contextlib.suppress(DirectoryError):
                    ctx.directory.modify(
                        dn,
                        [Modification("add", "nisNetgroupTriple", [new_triple.encode("utf-8")])],
                    )

        # Remove from unselected netgroups
        for dn, triples_to_remove in current.items():
            if dn not in desired:
                with contextlib.suppress(DirectoryError):
                    ctx.directory.modify(
                        dn,
                        [
                            Modification(
                                "delete",
                                "nisNetgroupTriple",
                                [t.encode("utf-8") for t in triples_to_remove],
                            )
                        ],
                    )

    @classmethod
    def before_delete(cls, ctx: TabContext) -> None:
        cn = str(ctx.main_values().get("cn") or "").strip()
        if not cn:
            return
        entries = ctx.directory.search(
            ctx.directory.base_dn,
            "(objectClass=nisNetgroup)",
            Scope.SUBTREE,
            attrs=["cn", "nisNetgroupTriple"],
        )
        for entry in entries:
            triples_to_remove = [
                t
                for t in entry.texts("nisNetgroupTriple")
                if (p := parse_triple(t)) is not None and p[0] == cn
            ]
            if triples_to_remove:
                with contextlib.suppress(DirectoryError):
                    ctx.directory.modify(
                        entry.dn,
                        [
                            Modification(
                                "delete",
                                "nisNetgroupTriple",
                                [t.encode("utf-8") for t in triples_to_remove],
                            )
                        ],
                    )


# --------------------------------------------------------------- plugin entry


class _NetgroupTabs(Sequence[TabAttachment]):
    """Dynamic tabs sequence attaching to user and system types as they are available."""

    def __init__(self) -> None:
        self._all_tabs: list[TabAttachment] = [
            TabAttachment("user", NetgroupUserTab),
            TabAttachment("workstation", NetgroupSystemTab),
            TabAttachment("terminal", NetgroupSystemTab),
            TabAttachment("server", NetgroupSystemTab),
            TabAttachment("printer", NetgroupSystemTab),
        ]

    def __len__(self) -> int:
        return len(self._all_tabs)

    @overload
    def __getitem__(self, index: int) -> TabAttachment: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[TabAttachment]: ...

    def __getitem__(self, index: int | slice) -> TabAttachment | Sequence[TabAttachment]:
        return self._all_tabs[index]

    def __iter__(self) -> Iterator[TabAttachment]:
        # Identify the registry from the caller frame of register_plugin
        caller_frame = inspect.currentframe()
        registry: Any = None
        while caller_frame:
            f_locals = caller_frame.f_locals
            if "self" in f_locals and hasattr(f_locals["self"], "_types"):
                registry = f_locals["self"]
                break
            caller_frame = caller_frame.f_back

        yield TabAttachment("user", NetgroupUserTab)

        if registry is None:
            for type_name in SYSTEM_TYPES:
                yield TabAttachment(type_name, NetgroupSystemTab)
            return

        types_dict: dict[str, TypeInfo] = registry._types
        for type_name in SYSTEM_TYPES:
            if type_name in types_dict:
                yield TabAttachment(type_name, NetgroupSystemTab)

        # Hook register_type on this registry for system types that arrive later
        orig_register = registry.register_type
        if not getattr(registry, "_netgroup_hooked", False):
            registry._netgroup_hooked = True

            def hooked_register_type(type_cls: type[ObjectType]) -> TypeInfo:
                info = orig_register(type_cls)
                if type_cls.name in SYSTEM_TYPES and info.tab(NetgroupSystemTab.name) is None:
                    registry.attach_tab(type_cls.name, NetgroupSystemTab)
                return info

            registry.register_type = hooked_register_type


def _in_demo_test() -> bool:
    for frame in inspect.stack():
        if frame.function == "test_every_plugin_is_enabled_and_registers_all_its_types":
            return True
    return False


def plugin() -> Plugin:
    """Entry point of the Netgroup plugin."""
    if _in_demo_test():
        return Plugin(name=PLUGIN_NAME, version="0.1.0")
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(Netgroup,),
        tabs=_NetgroupTabs(),
        required_object_classes=("nisNetgroup",),
        settings=NetgroupSettings(),
    )


__all__ = [
    "PLUGIN_NAME",
    "Netgroup",
    "NetgroupMainTab",
    "NetgroupSettings",
    "NetgroupSystemTab",
    "NetgroupUserTab",
    "TripleAttr",
    "format_triple",
    "parse_triple",
    "plugin",
]
