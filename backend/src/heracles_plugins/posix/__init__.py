"""POSIX plugin: Unix account tab on users and the POSIX group type."""

from __future__ import annotations

import contextlib
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, cast

from heracles.attributes import (
    JSON,
    BooleanAttr,
    DateAttr,
    DepartmentAttr,
    DisplayAttr,
    HiddenAttr,
    IntAttr,
    ListAttr,
    ObjectRefAttr,
    Option,
    SelectAttr,
    StringAttr,
    TextAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    DirectoryError,
    Entry,
    Modification,
    NoSuchObjectError,
)
from heracles.ldap.filter import escape_filter_value
from heracles.objects import (
    ObjectType,
    ObjectValidationError,
    Plugin,
    Section,
    Tab,
    TabAttachment,
)
from heracles.objects.hooks import TabContext
from heracles_plugins.posix.ids import (
    IdAllocationError,
    next_free_id,
    reservations_of,
)

PLUGIN_NAME = "posix"
EPOCH = date(1970, 1, 1)
POSIX_GROUP_FILTER = "(&(objectClass=posixGroup)(!(objectClass=groupOfNames)))"


@dataclass(slots=True)
class PosixSettings:
    """Settings of the POSIX plugin."""

    shells: list[str] = field(
        default_factory=lambda: [
            "/bin/bash",
            "/bin/sh",
            "/bin/zsh",
            "/usr/bin/fish",
            "/bin/false",
            "/usr/sbin/nologin",
        ]
    )
    default_shell: str = "/bin/bash"
    home_pattern: str = "/home/{uid}"
    uid_number_base: str = "1100"
    gid_number_base: str = "1100"
    min_id: int = 0
    groups_rdn: str = "ou=groups"


def settings_of(ctx: TabContext) -> PosixSettings:
    global _live_settings
    value = ctx.settings.get(PLUGIN_NAME)
    if isinstance(value, PosixSettings):
        _live_settings = value
        return value
    return PosixSettings()


#: The settings object of the last registered POSIX plugin. Descriptors have no request
#: context, so the shell select reads the configured shells from here (the registry keeps
#: the same object, and the console updates it when the configuration changes).
_live_settings: PosixSettings | None = None


class ShellAttr(SelectAttr):
    """Login shell: the allowed values are the shells configured at runtime."""

    def _configured(self) -> tuple[tuple[str, ...], str]:
        settings = _live_settings
        if settings is None:
            return tuple(PosixSettings().shells), PosixSettings().default_shell
        return tuple(settings.shells), settings.default_shell

    def _allowed(self) -> tuple[Option, ...]:
        shells, _default = self._configured()
        return tuple(Option(shell, shell) for shell in shells) or self.options

    def _validate(self, value: str) -> list[str]:
        allowed = {option.value for option in self._allowed()}
        if allowed and value not in allowed:
            return [_("Invalid choice.")]
        return []

    def describe_extra(self) -> dict[str, JSON]:
        return {"options": [{"value": o.value, "label": o.label} for o in self._allowed()]}

    def describe(self) -> dict[str, JSON]:
        out = super().describe()
        out["default"] = self._configured()[1]
        return out


def today_epoch_days() -> int:
    """Days since 1970-01-01 (UTC)."""
    return int(time.time() // 86400)


# --------------------------------------------------------------- attributes


class EpochDaysAttr(DateAttr):
    """A date stored as a number of days since 1970-01-01 (shadow format)."""

    def from_ldap(self, values: list[bytes]) -> date | None:
        if not values:
            return None
        text = values[0].decode("ascii", errors="replace").strip()
        if not text.lstrip("-").isdigit():
            return None
        days = int(text)
        return None if days <= 0 else EPOCH + timedelta(days=days)

    def to_ldap(self, value: date | None) -> list[bytes]:
        if value is None:
            return []
        return [str((value - EPOCH).days).encode("ascii")]


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


def _days(value: Any) -> int | None:
    if isinstance(value, date):
        return (value - EPOCH).days
    return value if isinstance(value, int) else None


def posix_status(values: dict[str, Any]) -> str:
    """Human status of the shadow account."""
    now = today_epoch_days()
    expire = _days(values.get("shadowExpire"))
    inactive = values.get("shadowInactive")
    max_age = values.get("shadowMax")
    min_age = values.get("shadowMin")
    last_raw = values.get("shadowLastChange")
    last = int(last_raw) if isinstance(last_raw, str) and last_raw.isdigit() else 0
    if expire is not None and expire > 0 and now >= expire:
        status = _("expired")
        if isinstance(inactive, int) and (now - expire) < inactive:
            status += ", " + _("grace time active")
        return status
    if isinstance(max_age, int) and last + max_age <= now:
        return _("active") + ", " + _("password expired")
    if isinstance(min_age, int) and last + min_age <= now:
        return _("active") + ", " + _("password not changeable")
    return _("active")


def ascii_gecos(text: str) -> str:
    """Transliterate to ASCII; empty when the result has unexpected characters."""
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    allowed = all(c.isalnum() or c in " -" for c in folded)
    return folded if allowed else ""


def _gecos_name(ctx: TabContext, main: dict[str, Any]) -> str:
    """The name ``gecos`` is built from: ``cn`` (spec 06).

    ``cn`` is computed from the given name and the surname *after* the tab hooks, so
    a creation or a rename has no fresh ``cn`` yet: build it the same way (the display
    name attribute of the user type). An entry whose stored ``cn`` differs from that
    join (a legacy entry) keeps its ``cn``.
    """
    name_tab = ctx.info.main_tab.name
    changed = ctx.was_touched("givenName", name_tab) or ctx.was_touched("sn", name_tab)
    cn = main.get("cn")
    if isinstance(cn, str) and cn.strip() and not changed:
        return cn
    parts = [p for p in (main.get("givenName"), main.get("sn")) if isinstance(p, str) and p]
    return " ".join(parts) if parts else (cn if isinstance(cn, str) else "")


# ------------------------------------------------------------------ helpers


def _uid(ctx: TabContext) -> str | None:
    uid = ctx.main_values().get("uid")
    return uid if isinstance(uid, str) and uid else None


def _search(directory: DirectoryClient, flt: str, attrs: list[str]) -> list[Entry]:
    try:
        return list(directory.search(directory.base_dn, flt, attrs=attrs))
    except NoSuchObjectError:
        return []


def _groups_with_member(directory: DirectoryClient, uid: str) -> list[Entry]:
    flt = f"(&(objectClass=posixGroup)(memberUid={escape_filter_value(uid)}))"
    return _search(directory, flt, ["cn", "memberUid", "gidNumber"])


def _group_by_gid(directory: DirectoryClient, gid: int) -> Entry | None:
    found = _search(directory, f"(&(objectClass=posixGroup)(gidNumber={gid}))", ["cn", "gidNumber"])
    return found[0] if found else None


def _group_by_cn(directory: DirectoryClient, cn: str, *, with_gid: bool) -> Entry | None:
    gid = "(gidNumber=*)" if with_gid else ""
    flt = f"(&(objectClass=posixGroup){gid}(cn={escape_filter_value(cn)}))"
    found = _search(directory, flt, ["cn", "gidNumber", "memberUid"])
    return found[0] if found else None


def _gid_of(entry: Entry) -> int | None:
    text = entry.text("gidNumber")
    return int(text) if text and text.strip().isdigit() else None


def _other_holder(
    directory: DirectoryClient, object_class: str, attr: str, value: object, own_dn: str | None
) -> str | None:
    """DN of another entry of ``object_class`` already holding ``attr=value``."""
    if not isinstance(value, int):
        return None
    flt = f"(&(objectClass={object_class})({attr}={value}))"
    for entry in _search(directory, flt, [attr]):
        if own_dn is None or dnlib.normalize(entry.dn) != dnlib.normalize(own_dn):
            return entry.dn
    return None


def _refuse_duplicate(
    directory: DirectoryClient,
    object_class: str,
    attr: str,
    value: object,
    own_dn: str | None,
    field: str,
) -> None:
    """Fail the save (post-write check) when another entry got the same id meanwhile."""
    holder = _other_holder(directory, object_class, attr, value, own_dn)
    if holder is not None:
        raise ObjectValidationError(
            {
                field: _("This id is already used by {dn}.").format(dn=holder),
            }
        )


def _remove_member_everywhere(directory: DirectoryClient, uid: str) -> None:
    for group in _groups_with_member(directory, uid):
        try:
            directory.modify(group.dn, [Modification("delete", "memberUid", [uid.encode()])])
        except DirectoryError:
            continue


def _delete_personal_group(directory: DirectoryClient, uid: str, gid: int | None) -> None:
    """Delete the automatic primary group ``cn=<uid>`` if nobody else uses it."""
    if gid is None:
        return
    flt = f"(&(objectClass=posixGroup)(gidNumber={gid})(cn={escape_filter_value(uid)}))"
    for group in _search(directory, flt, ["memberUid"]):
        members = group.texts("memberUid")
        if not members or members == [uid]:
            try:
                directory.delete(group.dn)
            except DirectoryError:
                continue


# --------------------------------------------------------------------- tabs

PENDING_GROUP = "_pending_primary_group"


class PosixAccountTab(Tab):
    """Unix account (``posixAccount`` + ``shadowAccount``) of a user."""

    name = "posix"
    acl_key = "posixAccount"
    label = _("Unix")
    description = _("Unix account: UID, home directory, shell")
    optional = True
    object_classes = ("posixAccount", "shadowAccount")

    unix = Section(
        _("Unix"),
        StringAttr(
            "homeDirectory",
            _("Home directory"),
            description=_("Path to the home directory (default /home/<login>)"),
            pattern=r"/.*",
        ),
        ShellAttr(
            "loginShell",
            _("Shell"),
        ),
        virtual(
            ObjectRefAttr(
                "primaryGroup",
                _("Primary group"),
                ref_type="posix_group",
                description=_("Leave empty to use a personal group named after the login"),
            )
        ),
        virtual(BooleanAttr("force_ids", _("Force user/group id"), default=False)),
        IntAttr("uidNumber", _("User id"), min=0),
        IntAttr("gidNumber", _("Group id"), min=0),
        DisplayAttr("posixStatus", _("Status"), compute=posix_status),
        HiddenAttr("gecos", "gecos"),
    )
    membership = Section(
        _("Group membership"),
        virtual(
            ListAttr(
                "groupMembership",
                _("Groups"),
                ObjectRefAttr("group", _("Group"), ref_type="posix_group"),
            )
        ),
    )
    account = Section(
        _("Account"),
        virtual(
            BooleanAttr(
                "mustchangepassword",
                _("User must change password on first login"),
                description=_("Needs a value for the delay before forcing password change"),
                default=False,
            )
        ),
        IntAttr("shadowMin", _("Minimum delay between password changes (days)"), min=0),
        IntAttr("shadowMax", _("Delay before forcing password change (days)"), min=0),
        EpochDaysAttr("shadowExpire", _("Password expiration date")),
        IntAttr("shadowInactive", _("Delay of inactivity before disabling user (days)"), min=0),
        IntAttr("shadowWarning", _("Delay for user warning before password expiry (days)"), min=0),
        HiddenAttr("shadowLastChange", "shadowLastChange"),
    )

    # ------------------------------------------------------------- hooks

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        uid = _uid(ctx)
        directory = ctx.directory
        ctx.values["force_ids"] = False
        ctx.values["mustchangepassword"] = False
        ctx.values["groupMembership"] = (
            [g.dn for g in _groups_with_member(directory, uid)] if uid else []
        )
        gid = ctx.values.get("gidNumber")
        primary: str | None = None
        if isinstance(gid, int):
            group = _group_by_gid(directory, gid)
            if group is not None and group.text("cn") != uid:
                primary = group.dn
        ctx.values["primaryGroup"] = primary
        ctx.values["posixStatus"] = posix_status(ctx.values)

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        uid = _uid(ctx)
        if uid is None:
            return
        settings = settings_of(ctx)
        values = ctx.values
        if not values.get("homeDirectory"):
            values["homeDirectory"] = settings.home_pattern.format(uid=uid)
        if not values.get("loginShell"):
            values["loginShell"] = settings.default_shell
        main = ctx.main_values()
        values["gecos"] = ascii_gecos(_gecos_name(ctx, main)) or None
        force = bool(values.get("force_ids"))

        try:
            cls._prepare_ids(ctx, uid, settings, force)
        except IdAllocationError as exc:
            ctx.error("uidNumber", str(exc))
            return
        cls._check_membership_rights(ctx, uid)

        # shadowLastChange
        today = today_epoch_days()
        password_changed = ctx.was_touched("userPassword", ctx.info.main_tab.name) and (
            main.get("userPassword") is not None
        )
        if values.get("mustchangepassword"):
            max_age = values.get("shadowMax")
            if not isinstance(max_age, int):
                ctx.error("shadowMax", _("Required to force a password change."))
            else:
                values["shadowLastChange"] = str(today - max_age - 1)
        elif ctx.activating or password_changed:
            values["shadowLastChange"] = str(today)

    @classmethod
    def _check_membership_rights(cls, ctx: TabContext, uid: str) -> None:
        """The memberships live on the groups: the editor needs the right to change those."""
        if not ctx.was_touched("groupMembership"):
            return
        raw = ctx.values.get("groupMembership")
        wanted = {
            dnlib.normalize(d): d for d in cast("list[object]", raw or []) if isinstance(d, str)
        }
        current = {dnlib.normalize(g.dn): g.dn for g in _groups_with_member(ctx.directory, uid)}
        for key in wanted.keys() ^ current.keys():
            group_dn = wanted.get(key) or current[key]
            if not ctx.can_write_object("posix_group", group_dn, "main", "memberUid"):
                ctx.error(
                    "groupMembership", _("Cannot change the members of {dn}").format(dn=group_dn)
                )
                return

    @classmethod
    def _prepare_ids(cls, ctx: TabContext, uid: str, settings: PosixSettings, force: bool) -> None:
        values = ctx.values
        directory = ctx.directory
        reservations = reservations_of(ctx.registry)
        if ctx.activating and not force:
            values["uidNumber"] = next_free_id(
                directory,
                "posixAccount",
                "uidNumber",
                base=settings.uid_number_base,
                min_id=settings.min_id,
                reservations=reservations,
            )
        elif force and not isinstance(values.get("uidNumber"), int):
            ctx.error("uidNumber", _("Required when ids are forced."))

        primary = values.get("primaryGroup")
        primary_changed = ctx.was_touched("primaryGroup")
        if isinstance(primary, str) and primary:
            if not (ctx.activating or primary_changed):
                return
            group = directory.get(primary, ["gidNumber", "objectClass"])
            gid = _gid_of(group) if group is not None else None
            if gid is None:
                ctx.error("primaryGroup", _("This group has no group id."))
                return
            values["gidNumber"] = gid
            return
        if not (ctx.activating or primary_changed or force):
            return
        if force:
            gid = values.get("gidNumber")
            if not isinstance(gid, int):
                ctx.error("gidNumber", _("Required when ids are forced."))
                return
            if _group_by_gid(directory, gid) is None:
                values[PENDING_GROUP] = True
            return
        existing = _group_by_cn(directory, uid, with_gid=True)
        if existing is not None and _gid_of(existing) is not None:
            values["gidNumber"] = _gid_of(existing)
            return
        values["gidNumber"] = next_free_id(
            directory,
            "posixGroup",
            "gidNumber",
            base=settings.gid_number_base,
            min_id=settings.min_id,
            reservations=reservations,
        )
        values[PENDING_GROUP] = True

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        uid = _uid(ctx)
        if uid is None or ctx.dn is None:
            return
        directory = ctx.directory
        values = ctx.values
        _refuse_duplicate(
            directory,
            "posixAccount",
            "uidNumber",
            values.get("uidNumber"),
            ctx.dn,
            "posix.uidNumber",
        )
        # personal primary group
        if values.pop(PENDING_GROUP, False):
            gid = values.get("gidNumber")
            if isinstance(gid, int):
                group_dn = cls._create_personal_group(ctx, uid, gid)
                _refuse_duplicate(
                    directory, "posixGroup", "gidNumber", gid, group_dn, "posix.gidNumber"
                )
        # login renamed: follow memberUid references
        old_uid = None
        if ctx.original is not None:
            old = ctx.original[ctx.info.main_tab.name].values.get("uid")
            old_uid = old if isinstance(old, str) and old != uid else None
        if old_uid:
            for group in _groups_with_member(directory, old_uid):
                directory.modify(
                    group.dn,
                    [
                        Modification("delete", "memberUid", [old_uid.encode()]),
                        Modification("add", "memberUid", [uid.encode()]),
                    ],
                )
        # secondary groups
        if ctx.was_touched("groupMembership"):
            wanted_raw = values.get("groupMembership")
            wanted = {
                dnlib.normalize(d): d
                for d in cast("list[object]", wanted_raw or [])
                if isinstance(d, str)
            }
            current = {dnlib.normalize(g.dn): g.dn for g in _groups_with_member(directory, uid)}
            for key, group_dn in wanted.items():
                if key not in current:
                    directory.modify(group_dn, [Modification("add", "memberUid", [uid.encode()])])
            for key, group_dn in current.items():
                if key not in wanted:
                    directory.modify(
                        group_dn, [Modification("delete", "memberUid", [uid.encode()])]
                    )

    @classmethod
    def _create_personal_group(cls, ctx: TabContext, uid: str, gid: int) -> str:
        directory = ctx.directory
        settings = settings_of(ctx)
        container = dnlib.join(settings.groups_rdn, ctx.base)
        cn = uid
        for n in range(1, 100):
            if _group_by_cn(directory, cn, with_gid=False) is None:
                break
            cn = f"{uid}_{n}"
        ensure_container(directory, container)
        group_dn = f"cn={dnlib.escape_rdn_value(cn)},{container}"
        with contextlib.suppress(AlreadyExistsError):
            directory.add(
                group_dn,
                {
                    "objectClass": [b"posixGroup"],
                    "cn": [cn.encode()],
                    "gidNumber": [str(gid).encode()],
                    "description": [_("Group of user {uid}").format(uid=uid).encode()],
                },
            )
        return group_dn

    @classmethod
    def on_deactivate(cls, ctx: TabContext) -> None:
        cls._cleanup(ctx)

    @classmethod
    def after_delete(cls, ctx: TabContext) -> None:
        cls._cleanup(ctx)

    @classmethod
    def _cleanup(cls, ctx: TabContext) -> None:
        uid = _uid(ctx)
        if uid is None:
            return
        gid = ctx.values.get("gidNumber")
        _remove_member_everywhere(ctx.directory, uid)
        _delete_personal_group(ctx.directory, uid, gid if isinstance(gid, int) else None)


class PosixGroup(ObjectType):
    """A POSIX group (``posixGroup`` without ``groupOfNames``)."""

    name = "posix_group"
    acl_category = "group"
    label = _("POSIX group")
    label_plural = _("POSIX groups")
    nav = "secondary"
    nav_group = "people"
    icon = "users-round"
    category = "directory"
    filter = POSIX_GROUP_FILTER
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=groups"
    columns = ("cn", "gidNumber", "description")
    search_attrs = ("cn", "description", "memberUid")

    class Main(Tab):
        name = "main"
        acl_key = "posixGroup"
        label = _("POSIX group")
        object_classes = ("posixGroup",)

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True, pattern=r"[A-Za-z0-9_][A-Za-z0-9_.-]*"),
            TextAttr("description", _("Description")),
            virtual(BooleanAttr("force_gid", _("Force group id"), default=False)),
            IntAttr("gidNumber", _("Group id"), min=0),
        )
        members = Section(
            _("Members"),
            ListAttr("memberUid", _("Members (logins)"), StringAttr("uid", _("Login"))),
        )

        @classmethod
        def on_load(cls, ctx: TabContext) -> None:
            ctx.values["force_gid"] = False

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            settings = settings_of(ctx)
            force = bool(ctx.values.get("force_gid"))
            if force:
                if not isinstance(ctx.values.get("gidNumber"), int):
                    ctx.error("gidNumber", _("Required when the group id is forced."))
                return
            if ctx.creating or not isinstance(ctx.values.get("gidNumber"), int):
                try:
                    ctx.values["gidNumber"] = next_free_id(
                        ctx.directory,
                        "posixGroup",
                        "gidNumber",
                        base=settings.gid_number_base,
                        min_id=settings.min_id,
                        reservations=reservations_of(ctx.registry),
                    )
                except IdAllocationError as exc:
                    ctx.error("gidNumber", str(exc))

        @classmethod
        def after_save(cls, ctx: TabContext) -> None:
            _refuse_duplicate(
                ctx.directory,
                "posixGroup",
                "gidNumber",
                ctx.values.get("gidNumber"),
                ctx.dn,
                "main.gidNumber",
            )


def plugin() -> Plugin:
    """Entry point of the POSIX plugin."""
    global _live_settings
    settings = PosixSettings()
    _live_settings = settings
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(PosixGroup,),
        tabs=(TabAttachment("user", PosixAccountTab),),
        required_object_classes=("posixAccount", "shadowAccount", "posixGroup"),
        settings=settings,
    )


__all__ = [
    "EpochDaysAttr",
    "PosixAccountTab",
    "PosixGroup",
    "PosixSettings",
    "ShellAttr",
    "ascii_gecos",
    "plugin",
    "posix_status",
]
