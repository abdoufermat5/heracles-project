"""Samba plugin: Windows domain data for users, POSIX groups and workstations.

* ``samba`` tab on users (``sambaSamAccount``): SID, NT/LM password hashes,
  account flags, logon hours, home drive...
* ``samba`` tab on POSIX groups (``sambaGroupMapping``).
* ``samba`` tab on workstations: machine trust account.
* ``samba_domain`` type (``sambaDomain``).

The terminal server blob ``sambaMungedDial`` is never touched.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from heracles.attributes import (
    BooleanAttr,
    DepartmentAttr,
    DisplayAttr,
    HiddenAttr,
    IntAttr,
    SelectAttr,
    StringAttr,
)
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    DirectoryError,
    Entry,
    Modification,
    NoSuchObjectError,
)
from heracles.ldap.filter import escape_filter_value
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext
from heracles_plugins.posix import settings_of as posix_settings_of
from heracles_plugins.posix.ids import IdAllocationError, next_free_id
from heracles_plugins.samba.flags import (
    DOMAIN_COMPUTERS_RID,
    DOMAIN_USERS_RID,
    FLAG_AUTOLOCKED,
    FLAG_DISABLED,
    FLAG_NEEDS_NO_AUTH,
    FLAG_NO_EXPIRE,
    FLAG_NORMAL,
    FLAG_WORKSTATION,
    PWD_CANNOT_CHANGE,
    WELL_KNOWN_GROUPS,
    WELL_KNOWN_RIDS,
    LogonHoursAttr,
    SidAttr,
    UnixDateAttr,
    WorkstationsAttr,
    format_flags,
    grid_to_hours,
    hours_to_grid,
    parse_flags,
    rid_of,
    set_flag,
    sid_with_rid,
)
from heracles_plugins.samba.hashes import lm_hash, nt_hash

PLUGIN_NAME = "samba"
IDMAP_CLASS = "sambaIdmapEntry"
EXPIRATION_MODES = ("none", "posix", "samba")


@dataclass(slots=True)
class SambaSettings:
    """Settings of the Samba plugin."""

    #: SID of the domain used when no ``sambaDomain`` entry is selected.
    domain_sid: str = ""
    rid_base: int = 1000
    generate_lm_password: bool = False
    #: ``none``, ``posix`` (shadowExpire -> sambaKickoffTime) or ``samba`` (reverse).
    expiration_sync: str = "none"
    depends_on_posix: bool = True
    #: Add ``sambaIdmapEntry`` to users and groups.
    id_mapping: bool = False
    primary_group_warning: bool = True
    #: gidNumber given to machine trust accounts.
    workstation_gid: int = 515


def settings_of(ctx: TabContext) -> SambaSettings:
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, SambaSettings) else SambaSettings()


def now_epoch() -> int:
    """Current unix time (patched in tests)."""
    return int(time.time())


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


class SecretAttr(HiddenAttr):
    """Write-only hash: never sent to clients; ``""`` removes the stored value."""

    write_only = True

    def from_ldap(self, values: list[bytes]) -> str | None:
        return None

    def to_json(self, value: str | None) -> None:
        return None


# ------------------------------------------------------------------ helpers


@dataclass(frozen=True, slots=True)
class DomainInfo:
    name: str | None
    sid: str
    rid_base: int


def _search(directory: DirectoryClient, flt: str, attrs: list[str]) -> list[Entry]:
    try:
        return list(directory.search(directory.base_dn, flt, attrs=attrs))
    except NoSuchObjectError:
        return []


def _int(text: str | None) -> int | None:
    return int(text) if text and text.strip().isdigit() else None


def resolve_domain(ctx: TabContext, name: str | None) -> DomainInfo | None:
    """Domain SID and RID base: the named ``sambaDomain``, else the settings."""
    settings = settings_of(ctx)
    attrs = ["sambaDomainName", "sambaSID", "sambaAlgorithmicRidBase"]
    if name:
        flt = f"(&(objectClass=sambaDomain)(sambaDomainName={escape_filter_value(name)}))"
        found = _search(ctx.directory, flt, attrs)
    elif not settings.domain_sid:
        found = _search(ctx.directory, "(objectClass=sambaDomain)", attrs)
        found = found if len(found) == 1 else []
    else:
        found = []
    for entry in found:
        sid = entry.text("sambaSID")
        if sid:
            base = _int(entry.text("sambaAlgorithmicRidBase"))
            return DomainInfo(
                entry.text("sambaDomainName"), sid, base if base is not None else settings.rid_base
            )
    if settings.domain_sid:
        return DomainInfo(name, settings.domain_sid, settings.rid_base)
    return None


def free_sid(directory: DirectoryClient, domain_sid: str, rid: int, own_dn: str | None) -> str:
    """First unused ``<domain>-<rid>``, incrementing ``rid`` while the SID is taken."""
    for candidate in range(rid, rid + 100_000):
        sid = sid_with_rid(domain_sid, candidate)
        taken = _search(directory, f"(sambaSID={escape_filter_value(sid)})", ["sambaSID"])
        if all(
            own_dn is not None and dnlib.normalize(e.dn) == dnlib.normalize(own_dn) for e in taken
        ):
            return sid
    raise IdAllocationError("no free SID")


def mapped_group_sid(directory: DirectoryClient, gid: int) -> str | None:
    """SID of the Samba group mapped to ``gid``."""
    flt = f"(&(objectClass=sambaGroupMapping)(gidNumber={gid}))"
    for entry in _search(directory, flt, ["sambaSID"]):
        sid = entry.text("sambaSID")
        if sid:
            return sid
    return None


def _set_idmap(ctx: TabContext, *, enabled: bool) -> None:
    """Add (or remove) the ``sambaIdmapEntry`` class on the object."""
    if ctx.dn is None:
        return
    known = {c.lower() for c in ctx.directory.schema_object_classes()}
    if IDMAP_CLASS.lower() not in known:
        return
    entry = ctx.directory.get(ctx.dn, ["objectClass"])
    if entry is None:
        return
    present = entry.has_object_class(IDMAP_CLASS)
    try:
        if enabled and not present:
            ctx.directory.modify(
                ctx.dn, [Modification("add", "objectClass", [IDMAP_CLASS.encode()])]
            )
        elif not enabled and present:
            ctx.directory.modify(
                ctx.dn, [Modification("delete", "objectClass", [IDMAP_CLASS.encode()])]
            )
    except DirectoryError:
        return


def _posix_values(ctx: TabContext) -> dict[str, Any] | None:
    state = ctx.tabs.get("posix")
    return state.values if state is not None and state.active else None


# ----------------------------------------------------------------- user tab


def _gid_warning(values: dict[str, Any]) -> str | None:
    value = values.get("_primary_group_warning")
    return value if isinstance(value, str) else None


class SambaUserTab(Tab):
    """Samba account (``sambaSamAccount``) of a user."""

    name = "samba"
    acl_key = "sambaAccount"
    label = _("Samba")
    optional = True
    object_classes = ("sambaSamAccount",)

    identity = Section(
        _("Samba account"),
        StringAttr(
            "sambaDomainName",
            _("Domain"),
            description=_("Name of a Samba domain; leave empty for the default domain"),
        ),
        SidAttr("sambaSID", _("SID"), readonly=True),
        SidAttr("sambaPrimaryGroupSID", _("Primary group SID"), readonly=True),
        DisplayAttr(
            "primaryGroupStatus",
            _("Primary group mapping"),
            compute=_gid_warning,
        ),
    )
    profile = Section(
        _("Home and profile"),
        SelectAttr(
            "sambaHomeDrive",
            _("Home drive"),
            options=[(f"{c}:", f"{c}:") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"],
        ),
        StringAttr("sambaHomePath", _("Home path"), description=_(r"For example \\server\share")),
        StringAttr("sambaLogonScript", _("Logon script")),
        StringAttr("sambaProfilePath", _("Profile path")),
        WorkstationsAttr(
            "sambaUserWorkstations",
            _("Allowed workstations"),
            description=_("Comma separated list of workstation names; empty means all"),
        ),
    )
    restrictions = Section(
        _("Restrictions"),
        virtual(BooleanAttr("flag_disabled", _("Account disabled"), default=False)),
        virtual(BooleanAttr("flag_pwdNeverExpires", _("Password never expires"), default=False)),
        virtual(BooleanAttr("flag_noPwdRequired", _("No password required"), default=False)),
        virtual(
            BooleanAttr(
                "flag_autoLocked",
                _("Locked automatically"),
                readonly=True,
                default=False,
            )
        ),
        virtual(BooleanAttr("hrc_pwdCantChange", _("Password cannot be changed"), default=False)),
        UnixDateAttr("sambaKickoffTime", _("Account expiration date")),
        LogonHoursAttr(
            "sambaLogonHours",
            _("Logon hours"),
            description=_("42 hexadecimal characters, one bit per hour from Sunday 00:00 UTC"),
        ),
    )
    internal = Section(
        _("Internal"),
        HiddenAttr("sambaAcctFlags", "sambaAcctFlags"),
        HiddenAttr("sambaPwdLastSet", "sambaPwdLastSet"),
        SecretAttr("sambaNTPassword", "sambaNTPassword"),
        SecretAttr("sambaLMPassword", "sambaLMPassword"),
    )

    # ------------------------------------------------------------- hooks

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        values = ctx.values
        letters = parse_flags(cast("str | None", values.get("sambaAcctFlags")))
        values["flag_disabled"] = FLAG_DISABLED in letters
        values["flag_pwdNeverExpires"] = FLAG_NO_EXPIRE in letters
        values["flag_noPwdRequired"] = FLAG_NEEDS_NO_AUTH in letters
        values["flag_autoLocked"] = FLAG_AUTOLOCKED in letters
        values["hrc_pwdCantChange"] = values.get("sambaPwdLastSet") == str(PWD_CANNOT_CHANGE)
        values["_primary_group_warning"] = None
        if settings_of(ctx).primary_group_warning:
            domain = resolve_domain(ctx, cast("str | None", values.get("sambaDomainName")))
            if domain is not None:
                values["_primary_group_warning"] = cls._group_warning(ctx, domain)[1]
        values["primaryGroupStatus"] = _gid_warning(values)

    @staticmethod
    def _group_warning(ctx: TabContext, domain: DomainInfo) -> tuple[str, str | None]:
        """Primary group SID and a warning when the group has no Samba mapping."""
        posix = _posix_values(ctx)
        gid = posix.get("gidNumber") if posix is not None else None
        mapped = mapped_group_sid(ctx.directory, gid) if isinstance(gid, int) else None
        if mapped is not None:
            return mapped, None
        warning = _("The primary group has no Samba mapping: Domain Users is used instead.")
        return sid_with_rid(domain.sid, DOMAIN_USERS_RID), warning

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        settings = settings_of(ctx)
        values = ctx.values
        posix = _posix_values(ctx)
        if settings.depends_on_posix and posix is None:
            ctx.error("sambaDomainName", _("The Unix account tab must be enabled first."))
            return
        name = values.get("sambaDomainName")
        domain = resolve_domain(ctx, name if isinstance(name, str) and name else None)
        if domain is None:
            ctx.error("sambaDomainName", _("No Samba domain is configured for this account."))
            return
        if domain.name and not values.get("sambaDomainName"):
            values["sambaDomainName"] = domain.name

        cls._prepare_sid(ctx, domain, posix)
        sid, warning = cls._group_warning(ctx, domain)
        values["sambaPrimaryGroupSID"] = sid
        values["_primary_group_warning"] = warning if settings.primary_group_warning else None
        cls._prepare_flags(values)
        cls._prepare_password(ctx, settings)
        cls._sync_expiration(settings, values, posix)

    @classmethod
    def _prepare_sid(
        cls, ctx: TabContext, domain: DomainInfo, posix: dict[str, Any] | None
    ) -> None:
        values = ctx.values
        if not (ctx.activating or not values.get("sambaSID") or ctx.was_touched("sambaDomainName")):
            return
        uid_number = posix.get("uidNumber") if posix is not None else None
        rid = uid_number * 2 + domain.rid_base if isinstance(uid_number, int) else domain.rid_base
        try:
            values["sambaSID"] = free_sid(ctx.directory, domain.sid, rid, ctx.dn)
        except IdAllocationError as exc:
            ctx.error("sambaSID", str(exc))

    @staticmethod
    def _prepare_flags(values: dict[str, Any]) -> None:
        letters = parse_flags(cast("str | None", values.get("sambaAcctFlags")))
        if FLAG_WORKSTATION not in letters:
            letters = set_flag(letters, FLAG_NORMAL, True)
        letters = set_flag(letters, FLAG_DISABLED, bool(values.get("flag_disabled")))
        letters = set_flag(letters, FLAG_NO_EXPIRE, bool(values.get("flag_pwdNeverExpires")))
        letters = set_flag(letters, FLAG_NEEDS_NO_AUTH, bool(values.get("flag_noPwdRequired")))
        values["sambaAcctFlags"] = format_flags(letters)

    @classmethod
    def _prepare_password(cls, ctx: TabContext, settings: SambaSettings) -> None:
        values = ctx.values
        password = ctx.main_values().get("userPassword")
        changed = (
            ctx.was_touched("userPassword", ctx.info.main_tab.name)
            and isinstance(password, str)
            and password != ""
        )
        if changed:
            assert isinstance(password, str)
            values["sambaNTPassword"] = nt_hash(password)
            lm = lm_hash(password) if settings.generate_lm_password else None
            values["sambaLMPassword"] = lm or ""
        cannot = bool(values.get("hrc_pwdCantChange"))
        was_cannot = bool(ctx.original_values().get("hrc_pwdCantChange"))
        if cannot:
            values["sambaPwdLastSet"] = str(PWD_CANNOT_CHANGE)
        elif changed or was_cannot:
            values["sambaPwdLastSet"] = str(now_epoch())

    @staticmethod
    def _sync_expiration(
        settings: SambaSettings, values: dict[str, Any], posix: dict[str, Any] | None
    ) -> None:
        if posix is None:
            return
        if settings.expiration_sync == "posix":
            expire = posix.get("shadowExpire")
            values["sambaKickoffTime"] = expire if isinstance(expire, date) else None
        elif settings.expiration_sync == "samba":
            kickoff = values.get("sambaKickoffTime")
            posix["shadowExpire"] = kickoff if isinstance(kickoff, date) else None

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        if settings_of(ctx).id_mapping:
            _set_idmap(ctx, enabled=True)

    @classmethod
    def on_deactivate(cls, ctx: TabContext) -> None:
        _set_idmap(ctx, enabled=False)


# ---------------------------------------------------------------- group tab


class SambaGroupTab(Tab):
    """Samba group mapping (``sambaGroupMapping``) of a POSIX group."""

    name = "samba"
    acl_key = "sambaGroup"
    label = _("Samba")
    optional = True
    object_classes = ("sambaGroupMapping",)

    mapping = Section(
        _("Samba group"),
        StringAttr(
            "sambaDomainName",
            _("Domain"),
            description=_("Name of a Samba domain; leave empty for the default domain"),
        ),
        virtual(
            SelectAttr(
                "wellKnownRid",
                _("Well-known group"),
                description=_("Leave empty to derive the SID from the group id"),
                options=[(rid, f"{label} ({rid})") for rid, label in WELL_KNOWN_GROUPS],
            )
        ),
        SidAttr("sambaSID", _("SID"), readonly=True),
        SelectAttr(
            "sambaGroupType",
            _("Group type"),
            options=[("2", _("Domain group")), ("4", _("Local group")), ("5", _("Built-in group"))],
        ),
        StringAttr("displayName", _("Display name")),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        rid = rid_of(cast("str | None", ctx.values.get("sambaSID")))
        ctx.values["wellKnownRid"] = str(rid) if rid in WELL_KNOWN_RIDS else None

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        values = ctx.values
        name = values.get("sambaDomainName")
        domain = resolve_domain(ctx, name if isinstance(name, str) and name else None)
        if domain is None:
            ctx.error("sambaDomainName", _("No Samba domain is configured for this group."))
            return
        if domain.name and not values.get("sambaDomainName"):
            values["sambaDomainName"] = domain.name
        if not values.get("displayName"):
            cn = ctx.main_values().get("cn")
            values["displayName"] = cn if isinstance(cn, str) and cn else None
        well_known = values.get("wellKnownRid")
        if not values.get("sambaGroupType"):
            is_alias = (
                isinstance(well_known, str) and well_known.isdigit() and int(well_known) >= 544
            )
            values["sambaGroupType"] = "4" if is_alias else "2"
        recompute = (
            ctx.activating
            or not values.get("sambaSID")
            or ctx.was_touched("sambaDomainName")
            or ctx.was_touched("wellKnownRid")
        )
        if not recompute:
            return
        try:
            if isinstance(well_known, str) and well_known:
                sid = sid_with_rid(domain.sid, int(well_known))
                holders = _search(ctx.directory, f"(sambaSID={escape_filter_value(sid)})", [])
                if any(dnlib.normalize(e.dn) != dnlib.normalize(ctx.dn or "") for e in holders):
                    ctx.error("wellKnownRid", _("This well-known group already exists."))
                    return
                values["sambaSID"] = sid
                return
            gid = ctx.main_values().get("gidNumber")
            if not isinstance(gid, int):
                ctx.error("sambaSID", _("The group needs a group id."))
                return
            values["sambaSID"] = free_sid(
                ctx.directory, domain.sid, gid * 2 + domain.rid_base + 1, ctx.dn
            )
        except IdAllocationError as exc:
            ctx.error("sambaSID", str(exc))

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        if settings_of(ctx).id_mapping:
            _set_idmap(ctx, enabled=True)

    @classmethod
    def on_deactivate(cls, ctx: TabContext) -> None:
        _set_idmap(ctx, enabled=False)


# ---------------------------------------------------------- workstation tab


class SambaWorkstationTab(Tab):
    """Machine trust account (``posixAccount`` + ``sambaSamAccount``) of a workstation."""

    name = "samba"
    acl_key = "sambaSystemTab"
    label = _("Samba")
    optional = True
    object_classes = ("posixAccount", "sambaSamAccount")

    account = Section(
        _("Machine account"),
        StringAttr(
            "sambaDomainName",
            _("Domain"),
            description=_("Name of a Samba domain; leave empty for the default domain"),
        ),
        SidAttr("sambaSID", _("SID"), readonly=True),
        HiddenAttr("uid", "uid"),
        HiddenAttr("uidNumber", "uidNumber"),
        HiddenAttr("gidNumber", "gidNumber"),
        HiddenAttr("homeDirectory", "homeDirectory"),
        HiddenAttr("loginShell", "loginShell"),
        HiddenAttr("sambaPrimaryGroupSID", "sambaPrimaryGroupSID"),
        HiddenAttr("sambaAcctFlags", "sambaAcctFlags"),
    )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        settings = settings_of(ctx)
        values = ctx.values
        cn = ctx.main_values().get("cn")
        if not isinstance(cn, str) or not cn:
            return
        name = values.get("sambaDomainName")
        domain = resolve_domain(ctx, name if isinstance(name, str) and name else None)
        if domain is None:
            ctx.error("sambaDomainName", _("No Samba domain is configured for this account."))
            return
        if domain.name and not values.get("sambaDomainName"):
            values["sambaDomainName"] = domain.name
        values["uid"] = f"{cn}$"
        values["homeDirectory"] = "/dev/null"
        values["loginShell"] = "/bin/false"
        values["gidNumber"] = str(settings.workstation_gid)
        values["sambaAcctFlags"] = format_flags(FLAG_WORKSTATION)
        values["sambaPrimaryGroupSID"] = sid_with_rid(domain.sid, DOMAIN_COMPUTERS_RID)
        try:
            if not _int(cast("str | None", values.get("uidNumber"))):
                posix = posix_settings_of(ctx)
                values["uidNumber"] = str(
                    next_free_id(
                        ctx.directory,
                        "posixAccount",
                        "uidNumber",
                        base=posix.uid_number_base,
                        min_id=posix.min_id,
                    )
                )
            if ctx.activating or not values.get("sambaSID") or ctx.was_touched("sambaDomainName"):
                uid_number = int(str(values["uidNumber"]))
                values["sambaSID"] = free_sid(
                    ctx.directory, domain.sid, uid_number * 2 + domain.rid_base, ctx.dn
                )
        except IdAllocationError as exc:
            ctx.error("sambaSID", str(exc))


# -------------------------------------------------------------- domain type


class SambaDomain(ObjectType):
    """A Samba domain (``sambaDomain``)."""

    name = "samba_domain"
    acl_category = "sambaDomain"
    label = _("Samba domain")
    label_plural = _("Samba domains")
    icon = "network"
    category = "systems"
    filter = "(objectClass=sambaDomain)"
    main_attr = "sambaDomainName"
    name_attr = "sambaDomainName"
    rdn = ""
    columns = ("sambaDomainName", "sambaSID")
    search_attrs = ("sambaDomainName", "sambaSID")

    class Main(Tab):
        name = "main"
        acl_key = "sambaDomain"
        label = _("Samba domain")
        object_classes = ("sambaDomain",)

        properties = Section(
            _("Domain"),
            DepartmentAttr("base", _("Department")),
            StringAttr(
                "sambaDomainName",
                _("Name"),
                required=True,
                pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]*",
            ),
            SidAttr("sambaSID", _("Domain SID"), required=True),
            IntAttr(
                "sambaAlgorithmicRidBase",
                _("Algorithmic RID base"),
                description=_("Offset added to twice the unix id to build a RID"),
                min=0,
            ),
        )
        policy = Section(
            _("Password policy"),
            IntAttr("sambaMinPwdAge", _("Minimum password age (seconds)"), min=0),
            IntAttr("sambaMaxPwdAge", _("Maximum password age (seconds)"), min=-1),
            IntAttr("sambaMinPwdLength", _("Minimum password length"), readonly=True),
            IntAttr("sambaPwdHistoryLength", _("Password history length"), readonly=True),
            IntAttr("sambaLogonToChgPwd", _("Logon required to change password"), readonly=True),
            IntAttr("sambaLockoutDuration", _("Lockout duration"), readonly=True),
            IntAttr(
                "sambaLockoutObservationWindow", _("Lockout observation window"), readonly=True
            ),
            IntAttr("sambaLockoutThreshold", _("Lockout threshold"), readonly=True),
            IntAttr("sambaForceLogoff", _("Force logoff"), readonly=True),
            IntAttr(
                "sambaRefuseMachinePwdChange", _("Refuse machine password change"), readonly=True
            ),
        )
        counters = Section(
            _("Counters"),
            IntAttr("sambaNextRid", _("Next RID"), readonly=True),
            IntAttr("sambaNextGroupRid", _("Next group RID"), readonly=True),
            IntAttr("sambaNextUserRid", _("Next user RID"), readonly=True),
        )


# ---------------------------------------------------------------- lock hook


def lock_account(entry: Entry, locked: bool) -> list[Modification]:
    """Account lock hook: add (or remove) the ``D`` flag of ``sambaAcctFlags``."""
    if not entry.has_object_class("sambaSamAccount"):
        return []
    raw = entry.text("sambaAcctFlags")
    if raw is None:
        return []
    letters = parse_flags(raw)
    updated = format_flags(set_flag(letters, FLAG_DISABLED, locked))
    if updated == raw:
        return []
    return [Modification("replace", "sambaAcctFlags", [updated.encode()])]


def plugin() -> Plugin:
    """Entry point of the Samba plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(SambaDomain,),
        tabs=(
            TabAttachment("user", SambaUserTab),
            TabAttachment("posix_group", SambaGroupTab),
            TabAttachment("workstation", SambaWorkstationTab),
        ),
        required_object_classes=(
            "sambaSamAccount",
            "sambaGroupMapping",
            "posixGroup",
            "hrcWorkstation",
        ),
        account_lock_hooks=(lock_account,),
        settings=SambaSettings(),
    )


__all__ = [
    "SambaDomain",
    "SambaGroupTab",
    "SambaSettings",
    "SambaUserTab",
    "SambaWorkstationTab",
    "grid_to_hours",
    "hours_to_grid",
    "lock_account",
    "plugin",
]
