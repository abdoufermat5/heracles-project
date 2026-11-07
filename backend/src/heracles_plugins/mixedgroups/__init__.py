"""Mixed groups plugin: a ``groupOfNames`` that is also a ``posixGroup``.

Adds the optional ``mixed`` tab to the ``group`` type (ACL key
``ogroup/mixedGroup``). Activating it adds the ``posixGroup`` class, allocates a
group id with :func:`heracles_plugins.posix.ids.next_free_id` and keeps
``memberUid`` equal to the logins of the ``member`` users.

``memberUid`` edited directly on a mixed group (for instance by the group
membership of the POSIX user tab) is overwritten the next time the group is
saved; ``member`` is the source of truth.
"""

from __future__ import annotations

from typing import Any

from heracles.attributes import BooleanAttr, IntAttr, ListAttr, StringAttr
from heracles.i18n import _
from heracles.ldap.client import DirectoryClient, Modification
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext
from heracles_plugins.posix import PosixSettings
from heracles_plugins.posix.ids import IdAllocationError, next_free_id

PLUGIN_NAME = "mixedgroups"
POSIX_PLUGIN = "posix"


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


def posix_settings(ctx: TabContext) -> PosixSettings:
    value = ctx.settings.get(POSIX_PLUGIN)
    return value if isinstance(value, PosixSettings) else PosixSettings()


def logins_of(directory: DirectoryClient, member_dns: list[str]) -> list[str]:
    """Logins (``uid``) of the user entries in ``member_dns``, in order, without duplicates."""
    out: list[str] = []
    for dn in member_dns:
        entry = directory.get(dn, ["uid"])
        uid = entry.text("uid") if entry is not None else None
        if uid and uid not in out:
            out.append(uid)
    return out


def _dns(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]  # pyright: ignore[reportUnknownVariableType]


class MixedGroupTab(Tab):
    """POSIX attributes of a group of users."""

    name = "mixed"
    acl_key = "mixedGroup"
    label = _("POSIX group")
    optional = True
    object_classes = ("posixGroup",)

    posix = Section(
        _("POSIX group"),
        virtual(BooleanAttr("force_id", _("Force group id"), default=False)),
        IntAttr("gidNumber", _("Group id"), min=0),
        ListAttr(
            "memberUid",
            _("Members (logins)"),
            StringAttr("uid", _("Login")),
            readonly=True,
            description=_("Logins of the group members, kept in sync automatically"),
        ),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        ctx.values["force_id"] = False

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        values = ctx.values
        members = _dns(ctx.main_values().get("member"))
        values["memberUid"] = logins_of(ctx.directory, members) or None
        gid = values.get("gidNumber")
        if values.get("force_id"):
            if not isinstance(gid, int):
                ctx.error("gidNumber", _("Required when the group id is forced."))
            elif cls._gid_taken(ctx, gid):
                ctx.error("gidNumber", _("This group id is already in use."))
            return
        if isinstance(gid, int) and not ctx.activating:
            return
        settings = posix_settings(ctx)
        try:
            values["gidNumber"] = next_free_id(
                ctx.directory,
                "posixGroup",
                "gidNumber",
                base=settings.gid_number_base,
                min_id=settings.min_id,
            )
        except IdAllocationError as exc:
            ctx.error("gidNumber", str(exc))

    @classmethod
    def _gid_taken(cls, ctx: TabContext, gid: int) -> bool:
        flt = f"(&(objectClass=posixGroup)(gidNumber={gid}))"
        own = (ctx.dn or "").lower()
        return any(
            e.dn.lower() != own
            for e in ctx.directory.search(ctx.directory.base_dn, flt, attrs=["gidNumber"])
        )

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        # Another tab (dynamic membership) may have changed ``member`` after prepare.
        if ctx.dn is None:
            return
        entry = ctx.directory.get(ctx.dn, ["member", "memberUid"])
        if entry is None:
            return
        wanted = logins_of(ctx.directory, entry.texts("member"))
        current = entry.texts("memberUid")
        if sorted(wanted) == sorted(current):
            return
        if wanted:
            change = Modification("replace", "memberUid", [u.encode() for u in wanted])
        else:
            change = Modification("delete", "memberUid")
        ctx.directory.modify(ctx.dn, [change])


def plugin() -> Plugin:
    """Entry point of the mixed groups plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("group", MixedGroupTab),),
        required_object_classes=("posixGroup",),
    )


__all__ = ["MixedGroupTab", "logins_of", "plugin"]
