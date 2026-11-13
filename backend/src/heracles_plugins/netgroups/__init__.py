"""NIS Netgroup plugin: netgroups (nisNetgroup) and user/system membership tabs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import structlog

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
from heracles.objects import (
    ObjectType,
    ObjectValidationError,
    Plugin,
    Section,
    Tab,
    TabAttachment,
)
from heracles.objects.hooks import TabContext
from heracles_plugins.netgroups.triple import (
    TripleAttr,
    format_triple,
    parse_triple,
)

PLUGIN_NAME = "netgroups"

log = structlog.get_logger(__name__)


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written directly to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


@dataclass(slots=True)
class NetgroupSettings:
    """Settings of the Netgroup plugin."""

    rdn: str = "ou=netgroups"


def _normalized(values: object) -> dict[str, str]:
    """Selected netgroup DNs by normalised DN (spelling and case of a DN are not significant)."""
    items = cast("list[object]", values) if isinstance(values, list) else []
    return {dnlib.normalize(str(d)): str(d) for d in items}


def _check_membership_rights(ctx: TabContext, name: str, position: int) -> None:
    """The memberships live on the netgroups: the editor needs the right to change those.

    ``position`` is the field of the triple holding ``name`` (0 host, 1 user).
    """
    if not ctx.was_touched("nisMembership"):
        return
    wanted = _normalized(ctx.values.get("nisMembership"))
    current: dict[str, str] = {}
    for entry in ctx.directory.search(
        ctx.directory.base_dn,
        "(objectClass=nisNetgroup)",
        Scope.SUBTREE,
        attrs=["nisNetgroupTriple"],
    ):
        for raw in entry.texts("nisNetgroupTriple"):
            triple = parse_triple(raw)
            if triple is not None and triple[position] == name:
                current[dnlib.normalize(entry.dn)] = entry.dn
                break
    for key in wanted.keys() ^ current.keys():
        netgroup_dn = wanted.get(key) or current[key]
        if not ctx.can_write_object("netgroup", netgroup_dn, "main", "nisNetgroupTriple"):
            ctx.error(
                "nisMembership", _("Cannot change the members of {dn}").format(dn=netgroup_dn)
            )
            return


def _write_membership(ctx: TabContext, netgroup_dn: str, changes: list[Modification]) -> None:
    """Apply one membership change; a failure fails the save instead of disappearing."""
    try:
        ctx.directory.modify(netgroup_dn, changes)
    except DirectoryError as exc:
        raise ObjectValidationError(
            {
                f"{ctx.tab_name}.nisMembership": _("Cannot update netgroup {dn}: {error}").format(
                    dn=netgroup_dn, error=type(exc).__name__
                )
            }
        ) from None


def _drop_renamed(ctx: TabContext, attr: str, position: int, name: str) -> None:
    """Remove the triples of the previous login (``uid``) or host name (``cn``) of a renamed
    object: triples hold names, not DNs, so they would keep granting the old name."""
    if ctx.original is None:
        return
    old = ctx.original[ctx.info.main_tab.name].values.get(attr)
    if not isinstance(old, str) or not old.strip() or old.strip().lower() == name.lower():
        return
    for entry in ctx.directory.search(
        ctx.directory.base_dn,
        "(objectClass=nisNetgroup)",
        Scope.SUBTREE,
        attrs=["nisNetgroupTriple"],
    ):
        stale = [
            t
            for t in entry.texts("nisNetgroupTriple")
            if (p := parse_triple(t)) is not None and p[position] == old.strip()
        ]
        if stale:
            try:
                ctx.directory.modify(
                    entry.dn,
                    [
                        Modification(
                            "delete", "nisNetgroupTriple", [t.encode("utf-8") for t in stale]
                        )
                    ],
                )
            except DirectoryError as exc:
                log.warning(
                    "netgroup_stale_triple_not_removed",
                    netgroup=entry.dn,
                    error=type(exc).__name__,
                )


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
    def prepare(cls, ctx: TabContext) -> None:
        uid = str(ctx.main_values().get("uid") or "").strip()
        if uid:
            _check_membership_rights(ctx, uid, 1)

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        uid = str(ctx.main_values().get("uid") or "").strip()
        if not uid:
            return
        if "nisMembership" not in ctx.values:
            return  # unreadable by the acting user: unchanged, not "member of no netgroup"
        desired = _normalized(ctx.values["nisMembership"])
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
        for key, dn in desired.items():
            if key not in {dnlib.normalize(c) for c in current}:
                new_triple = format_triple(host="-", user=uid)
                _write_membership(
                    ctx,
                    dn,
                    [Modification("add", "nisNetgroupTriple", [new_triple.encode("utf-8")])],
                )

        # Remove from unselected netgroups
        for dn, triples_to_remove in current.items():
            if dnlib.normalize(dn) not in desired:
                _write_membership(
                    ctx,
                    dn,
                    [
                        Modification(
                            "delete",
                            "nisNetgroupTriple",
                            [t.encode("utf-8") for t in triples_to_remove],
                        )
                    ],
                )
        _drop_renamed(ctx, "uid", 1, uid)

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
                try:
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
                except DirectoryError as exc:
                    log.warning(
                        "netgroup_membership_not_removed",
                        netgroup=entry.dn,
                        error=type(exc).__name__,
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
    def prepare(cls, ctx: TabContext) -> None:
        cn = str(ctx.main_values().get("cn") or "").strip()
        if cn:
            _check_membership_rights(ctx, cn, 0)

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        cn = str(ctx.main_values().get("cn") or "").strip()
        if not cn:
            return
        if "nisMembership" not in ctx.values:
            return  # unreadable by the acting user: unchanged, not "member of no netgroup"
        desired = _normalized(ctx.values["nisMembership"])
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
        for key, dn in desired.items():
            if key not in {dnlib.normalize(c) for c in current}:
                new_triple = format_triple(host=cn, user="-")
                _write_membership(
                    ctx,
                    dn,
                    [Modification("add", "nisNetgroupTriple", [new_triple.encode("utf-8")])],
                )

        # Remove from unselected netgroups
        for dn, triples_to_remove in current.items():
            if dnlib.normalize(dn) not in desired:
                _write_membership(
                    ctx,
                    dn,
                    [
                        Modification(
                            "delete",
                            "nisNetgroupTriple",
                            [t.encode("utf-8") for t in triples_to_remove],
                        )
                    ],
                )
        _drop_renamed(ctx, "cn", 0, cn)

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
                try:
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
                except DirectoryError as exc:
                    log.warning(
                        "netgroup_membership_not_removed",
                        netgroup=entry.dn,
                        error=type(exc).__name__,
                    )


# --------------------------------------------------------------- plugin entry


#: The user tab plus a membership tab on every system type. Types absent from a registry
#: (plugin off, schema without them) are skipped by ``register_plugins``.
TABS: tuple[TabAttachment, ...] = (
    TabAttachment("user", NetgroupUserTab),
    TabAttachment("workstation", NetgroupSystemTab),
    TabAttachment("terminal", NetgroupSystemTab),
    TabAttachment("server", NetgroupSystemTab),
    TabAttachment("printer", NetgroupSystemTab),
)


def plugin() -> Plugin:
    """Entry point of the Netgroup plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(Netgroup,),
        tabs=TABS,
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
