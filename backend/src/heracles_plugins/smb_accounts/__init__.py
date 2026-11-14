"""SMB plugin: Windows domain data for users, POSIX groups and workstations.

* ``smb`` tab on users (``hrcSmbAccount``): SID, NT/LM password hashes,
  account flags, logon hours, home drive...
* ``smb`` tab on POSIX groups (``hrcSmbGroupMapping``).
* ``smb`` tab on workstations: machine trust account.
* ``smb_domain`` type (``hrcSmbDomain``).

The terminal server blob ``hrcSmbMungedDial`` is never touched.
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
from heracles_plugins.posix.ids import IdAllocationError, next_free_id, reservations_of
from heracles_plugins.smb_accounts.flags import (
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
from heracles_plugins.smb_accounts.hashes import lm_hash, nt_hash

PLUGIN_NAME = "smb_accounts"
IDMAP_CLASS = "hrcSmbIdmapEntry"
EXPIRATION_MODES = ("none", "posix", "smb")


@dataclass(slots=True)
class SMBSettings:
    """Settings of the SMB plugin."""

    #: SID of the domain used when no ``hrcSmbDomain`` entry is selected.
    domain_sid: str = ""
    rid_base: int = 1000
    generate_lm_password: bool = False
    #: ``none``, ``posix`` (shadowExpire -> hrcSmbKickoffTime) or ``smb`` (reverse).
    expiration_sync: str = "none"
    depends_on_posix: bool = True
    #: Add ``hrcSmbIdmapEntry`` to users and groups.
    id_mapping: bool = False
    primary_group_warning: bool = True
    #: gidNumber given to machine trust accounts.
    workstation_gid: int = 515


def settings_of(ctx: TabContext) -> SMBSettings:
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, SMBSettings) else SMBSettings()


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
    """Domain SID and RID base: the named ``hrcSmbDomain``, else the settings."""
    settings = settings_of(ctx)
    attrs = ["hrcSmbDomainName", "hrcSmbSID", "hrcSmbAlgorithmicRidBase"]
    if name:
        flt = f"(&(objectClass=hrcSmbDomain)(hrcSmbDomainName={escape_filter_value(name)}))"
        found = _search(ctx.directory, flt, attrs)
    elif not settings.domain_sid:
        found = _search(ctx.directory, "(objectClass=hrcSmbDomain)", attrs)
        found = found if len(found) == 1 else []
    else:
        found = []
    for entry in found:
        sid = entry.text("hrcSmbSID")
        if sid:
            base = _int(entry.text("hrcSmbAlgorithmicRidBase"))
            return DomainInfo(
                entry.text("hrcSmbDomainName"), sid, base if base is not None else settings.rid_base
            )
    if settings.domain_sid:
        return DomainInfo(name, settings.domain_sid, settings.rid_base)
    return None


def free_sid(directory: DirectoryClient, domain_sid: str, rid: int, own_dn: str | None) -> str:
    """First unused ``<domain>-<rid>``, incrementing ``rid`` while the SID is taken."""
    for candidate in range(rid, rid + 100_000):
        sid = sid_with_rid(domain_sid, candidate)
        taken = _search(directory, f"(hrcSmbSID={escape_filter_value(sid)})", ["hrcSmbSID"])
        if all(
            own_dn is not None and dnlib.normalize(e.dn) == dnlib.normalize(own_dn) for e in taken
        ):
            return sid
    raise IdAllocationError("no free SID")


def mapped_group_sid(directory: DirectoryClient, gid: int) -> str | None:
    """SID of the SMB group mapped to ``gid``."""
    flt = f"(&(objectClass=hrcSmbGroupMapping)(gidNumber={gid}))"
    for entry in _search(directory, flt, ["hrcSmbSID"]):
        sid = entry.text("hrcSmbSID")
        if sid:
            return sid
    return None


def _set_idmap(ctx: TabContext, *, enabled: bool) -> None:
    """Add (or remove) the ``hrcSmbIdmapEntry`` class on the object."""
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


class SMBUserTab(Tab):
    """SMB account (``hrcSmbAccount``) of a user."""

    name = "smb"
    acl_key = "smbAccount"
    label = _("SMB")
    description = _("Windows network account: SID, home share, logon script")
    optional = True
    object_classes = ("hrcSmbAccount",)

    identity = Section(
        _("SMB account"),
        StringAttr(
            "hrcSmbDomainName",
            _("Domain"),
            description=_("Name of a SMB domain; leave empty for the default domain"),
        ),
        SidAttr("hrcSmbSID", _("SID"), readonly=True),
        SidAttr("hrcSmbPrimaryGroupSID", _("Primary group SID"), readonly=True),
        DisplayAttr(
            "primaryGroupStatus",
            _("Primary group mapping"),
            compute=_gid_warning,
        ),
    )
    profile = Section(
        _("Home and profile"),
        SelectAttr(
            "hrcSmbHomeDrive",
            _("Home drive"),
            options=[(f"{c}:", f"{c}:") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"],
        ),
        StringAttr("hrcSmbHomePath", _("Home path"), description=_(r"For example \\server\share")),
        StringAttr("hrcSmbLogonScript", _("Logon script")),
        StringAttr("hrcSmbProfilePath", _("Profile path")),
        WorkstationsAttr(
            "hrcSmbUserWorkstations",
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
        UnixDateAttr("hrcSmbKickoffTime", _("Account expiration date")),
        LogonHoursAttr(
            "hrcSmbLogonHours",
            _("Logon hours"),
            description=_("42 hexadecimal characters, one bit per hour from Sunday 00:00 UTC"),
        ),
    )
    internal = Section(
        _("Internal"),
        HiddenAttr("hrcSmbAcctFlags", "hrcSmbAcctFlags"),
        HiddenAttr("hrcSmbPwdLastSet", "hrcSmbPwdLastSet"),
        SecretAttr("hrcSmbNTPassword", "hrcSmbNTPassword"),
        SecretAttr("hrcSmbLMPassword", "hrcSmbLMPassword"),
    )

    # ------------------------------------------------------------- hooks

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        values = ctx.values
        letters = parse_flags(cast("str | None", values.get("hrcSmbAcctFlags")))
        values["flag_disabled"] = FLAG_DISABLED in letters
        values["flag_pwdNeverExpires"] = FLAG_NO_EXPIRE in letters
        values["flag_noPwdRequired"] = FLAG_NEEDS_NO_AUTH in letters
        values["flag_autoLocked"] = FLAG_AUTOLOCKED in letters
        values["hrc_pwdCantChange"] = values.get("hrcSmbPwdLastSet") == str(PWD_CANNOT_CHANGE)
        values["_primary_group_warning"] = None
        if settings_of(ctx).primary_group_warning:
            domain = resolve_domain(ctx, cast("str | None", values.get("hrcSmbDomainName")))
            if domain is not None:
                values["_primary_group_warning"] = cls._group_warning(ctx, domain)[1]
        values["primaryGroupStatus"] = _gid_warning(values)

    @staticmethod
    def _group_warning(ctx: TabContext, domain: DomainInfo) -> tuple[str, str | None]:
        """Primary group SID and a warning when the group has no SMB mapping."""
        posix = _posix_values(ctx)
        gid = posix.get("gidNumber") if posix is not None else None
        mapped = mapped_group_sid(ctx.directory, gid) if isinstance(gid, int) else None
        if mapped is not None:
            return mapped, None
        warning = _("The primary group has no SMB mapping: Domain Users is used instead.")
        return sid_with_rid(domain.sid, DOMAIN_USERS_RID), warning

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        settings = settings_of(ctx)
        values = ctx.values
        posix = _posix_values(ctx)
        if settings.depends_on_posix and posix is None:
            ctx.error("hrcSmbDomainName", _("The Unix account tab must be enabled first."))
            return
        name = values.get("hrcSmbDomainName")
        domain = resolve_domain(ctx, name if isinstance(name, str) and name else None)
        if domain is None:
            ctx.error("hrcSmbDomainName", _("No SMB domain is configured for this account."))
            return
        if domain.name and not values.get("hrcSmbDomainName"):
            values["hrcSmbDomainName"] = domain.name

        cls._prepare_sid(ctx, domain, posix)
        sid, warning = cls._group_warning(ctx, domain)
        values["hrcSmbPrimaryGroupSID"] = sid
        values["_primary_group_warning"] = warning if settings.primary_group_warning else None
        cls._prepare_flags(values)
        cls._prepare_password(ctx, settings)
        cls._sync_expiration(settings, values, posix)

    @classmethod
    def _prepare_sid(
        cls, ctx: TabContext, domain: DomainInfo, posix: dict[str, Any] | None
    ) -> None:
        values = ctx.values
        if not (
            ctx.activating or not values.get("hrcSmbSID") or ctx.was_touched("hrcSmbDomainName")
        ):
            return
        uid_number = posix.get("uidNumber") if posix is not None else None
        rid = uid_number * 2 + domain.rid_base if isinstance(uid_number, int) else domain.rid_base
        try:
            values["hrcSmbSID"] = free_sid(ctx.directory, domain.sid, rid, ctx.dn)
        except IdAllocationError as exc:
            ctx.error("hrcSmbSID", str(exc))

    @staticmethod
    def _prepare_flags(values: dict[str, Any]) -> None:
        letters = parse_flags(cast("str | None", values.get("hrcSmbAcctFlags")))
        if FLAG_WORKSTATION not in letters:
            letters = set_flag(letters, FLAG_NORMAL, True)
        letters = set_flag(letters, FLAG_DISABLED, bool(values.get("flag_disabled")))
        letters = set_flag(letters, FLAG_NO_EXPIRE, bool(values.get("flag_pwdNeverExpires")))
        letters = set_flag(letters, FLAG_NEEDS_NO_AUTH, bool(values.get("flag_noPwdRequired")))
        values["hrcSmbAcctFlags"] = format_flags(letters)

    @classmethod
    def _prepare_password(cls, ctx: TabContext, settings: SMBSettings) -> None:
        values = ctx.values
        password = ctx.main_values().get("userPassword")
        changed = (
            ctx.was_touched("userPassword", ctx.info.main_tab.name)
            and isinstance(password, str)
            and password != ""
        )
        if changed:
            assert isinstance(password, str)
            values["hrcSmbNTPassword"] = nt_hash(password)
            lm = lm_hash(password) if settings.generate_lm_password else None
            values["hrcSmbLMPassword"] = lm or ""
        cannot = bool(values.get("hrc_pwdCantChange"))
        was_cannot = bool(ctx.original_values().get("hrc_pwdCantChange"))
        if cannot:
            values["hrcSmbPwdLastSet"] = str(PWD_CANNOT_CHANGE)
        elif changed or was_cannot:
            values["hrcSmbPwdLastSet"] = str(now_epoch())

    @staticmethod
    def _sync_expiration(
        settings: SMBSettings, values: dict[str, Any], posix: dict[str, Any] | None
    ) -> None:
        if posix is None:
            return
        if settings.expiration_sync == "posix":
            expire = posix.get("shadowExpire")
            values["hrcSmbKickoffTime"] = expire if isinstance(expire, date) else None
        elif settings.expiration_sync == "smb":
            kickoff = values.get("hrcSmbKickoffTime")
            posix["shadowExpire"] = kickoff if isinstance(kickoff, date) else None

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        if settings_of(ctx).id_mapping:
            _set_idmap(ctx, enabled=True)

    @classmethod
    def on_deactivate(cls, ctx: TabContext) -> None:
        _set_idmap(ctx, enabled=False)


# ---------------------------------------------------------------- group tab


class SMBGroupTab(Tab):
    """SMB group mapping (``hrcSmbGroupMapping``) of a POSIX group."""

    name = "smb"
    acl_key = "smbGroup"
    label = _("SMB")
    optional = True
    object_classes = ("hrcSmbGroupMapping",)

    mapping = Section(
        _("SMB group"),
        StringAttr(
            "hrcSmbDomainName",
            _("Domain"),
            description=_("Name of a SMB domain; leave empty for the default domain"),
        ),
        virtual(
            SelectAttr(
                "wellKnownRid",
                _("Well-known group"),
                description=_("Leave empty to derive the SID from the group id"),
                options=[(rid, f"{label} ({rid})") for rid, label in WELL_KNOWN_GROUPS],
            )
        ),
        SidAttr("hrcSmbSID", _("SID"), readonly=True),
        SelectAttr(
            "hrcSmbGroupType",
            _("Group type"),
            options=[("2", _("Domain group")), ("4", _("Local group")), ("5", _("Built-in group"))],
        ),
        StringAttr("displayName", _("Display name")),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        rid = rid_of(cast("str | None", ctx.values.get("hrcSmbSID")))
        ctx.values["wellKnownRid"] = str(rid) if rid in WELL_KNOWN_RIDS else None

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        values = ctx.values
        name = values.get("hrcSmbDomainName")
        domain = resolve_domain(ctx, name if isinstance(name, str) and name else None)
        if domain is None:
            ctx.error("hrcSmbDomainName", _("No SMB domain is configured for this group."))
            return
        if domain.name and not values.get("hrcSmbDomainName"):
            values["hrcSmbDomainName"] = domain.name
        if not values.get("displayName"):
            cn = ctx.main_values().get("cn")
            values["displayName"] = cn if isinstance(cn, str) and cn else None
        well_known = values.get("wellKnownRid")
        if not values.get("hrcSmbGroupType"):
            is_alias = (
                isinstance(well_known, str) and well_known.isdigit() and int(well_known) >= 544
            )
            values["hrcSmbGroupType"] = "4" if is_alias else "2"
        recompute = (
            ctx.activating
            or not values.get("hrcSmbSID")
            or ctx.was_touched("hrcSmbDomainName")
            or ctx.was_touched("wellKnownRid")
        )
        if not recompute:
            return
        try:
            if isinstance(well_known, str) and well_known:
                sid = sid_with_rid(domain.sid, int(well_known))
                holders = _search(ctx.directory, f"(hrcSmbSID={escape_filter_value(sid)})", [])
                if any(dnlib.normalize(e.dn) != dnlib.normalize(ctx.dn or "") for e in holders):
                    ctx.error("wellKnownRid", _("This well-known group already exists."))
                    return
                values["hrcSmbSID"] = sid
                return
            gid = ctx.main_values().get("gidNumber")
            if not isinstance(gid, int):
                ctx.error("hrcSmbSID", _("The group needs a group id."))
                return
            values["hrcSmbSID"] = free_sid(
                ctx.directory, domain.sid, gid * 2 + domain.rid_base + 1, ctx.dn
            )
        except IdAllocationError as exc:
            ctx.error("hrcSmbSID", str(exc))

    @classmethod
    def after_save(cls, ctx: TabContext) -> None:
        if settings_of(ctx).id_mapping:
            _set_idmap(ctx, enabled=True)

    @classmethod
    def on_deactivate(cls, ctx: TabContext) -> None:
        _set_idmap(ctx, enabled=False)


# ---------------------------------------------------------- workstation tab


class SMBWorkstationTab(Tab):
    """Machine trust account (``posixAccount`` + ``hrcSmbAccount``) of a workstation."""

    name = "smb"
    acl_key = "smbSystemTab"
    label = _("SMB")
    optional = True
    object_classes = ("posixAccount", "hrcSmbAccount")

    account = Section(
        _("Machine account"),
        StringAttr(
            "hrcSmbDomainName",
            _("Domain"),
            description=_("Name of a SMB domain; leave empty for the default domain"),
        ),
        SidAttr("hrcSmbSID", _("SID"), readonly=True),
        HiddenAttr("uid", "uid"),
        HiddenAttr("uidNumber", "uidNumber"),
        HiddenAttr("gidNumber", "gidNumber"),
        HiddenAttr("homeDirectory", "homeDirectory"),
        HiddenAttr("loginShell", "loginShell"),
        HiddenAttr("hrcSmbPrimaryGroupSID", "hrcSmbPrimaryGroupSID"),
        HiddenAttr("hrcSmbAcctFlags", "hrcSmbAcctFlags"),
    )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        settings = settings_of(ctx)
        values = ctx.values
        cn = ctx.main_values().get("cn")
        if not isinstance(cn, str) or not cn:
            return
        name = values.get("hrcSmbDomainName")
        domain = resolve_domain(ctx, name if isinstance(name, str) and name else None)
        if domain is None:
            ctx.error("hrcSmbDomainName", _("No SMB domain is configured for this account."))
            return
        if domain.name and not values.get("hrcSmbDomainName"):
            values["hrcSmbDomainName"] = domain.name
        values["uid"] = f"{cn}$"
        values["homeDirectory"] = "/dev/null"
        values["loginShell"] = "/bin/false"
        values["gidNumber"] = str(settings.workstation_gid)
        values["hrcSmbAcctFlags"] = format_flags(FLAG_WORKSTATION)
        values["hrcSmbPrimaryGroupSID"] = sid_with_rid(domain.sid, DOMAIN_COMPUTERS_RID)
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
                        reservations=reservations_of(ctx.registry),
                    )
                )
            if ctx.activating or not values.get("hrcSmbSID") or ctx.was_touched("hrcSmbDomainName"):
                uid_number = int(str(values["uidNumber"]))
                values["hrcSmbSID"] = free_sid(
                    ctx.directory, domain.sid, uid_number * 2 + domain.rid_base, ctx.dn
                )
        except IdAllocationError as exc:
            ctx.error("hrcSmbSID", str(exc))


# -------------------------------------------------------------- domain type


class SMBDomain(ObjectType):
    """A SMB domain (``hrcSmbDomain``)."""

    name = "smb_domain"
    acl_category = "hrcSmbDomain"
    label = _("SMB domain")
    label_plural = _("SMB domains")
    nav = "secondary"
    nav_group = "settings"
    icon = "database"
    category = "systems"
    filter = "(objectClass=hrcSmbDomain)"
    main_attr = "hrcSmbDomainName"
    name_attr = "hrcSmbDomainName"
    rdn = ""
    columns = ("hrcSmbDomainName", "hrcSmbSID")
    search_attrs = ("hrcSmbDomainName", "hrcSmbSID")

    class Main(Tab):
        name = "main"
        acl_key = "hrcSmbDomain"
        label = _("SMB domain")
        object_classes = ("hrcSmbDomain",)

        properties = Section(
            _("Domain"),
            DepartmentAttr("base", _("Department")),
            StringAttr(
                "hrcSmbDomainName",
                _("Name"),
                required=True,
                pattern=r"[A-Za-z0-9][A-Za-z0-9_.-]*",
            ),
            SidAttr("hrcSmbSID", _("Domain SID"), required=True),
            IntAttr(
                "hrcSmbAlgorithmicRidBase",
                _("Algorithmic RID base"),
                description=_("Offset added to twice the unix id to build a RID"),
                min=0,
            ),
        )
        policy = Section(
            _("Password policy"),
            IntAttr("hrcSmbMinPwdAge", _("Minimum password age (seconds)"), min=0),
            IntAttr("hrcSmbMaxPwdAge", _("Maximum password age (seconds)"), min=-1),
            IntAttr("hrcSmbMinPwdLength", _("Minimum password length"), readonly=True),
            IntAttr("hrcSmbPwdHistoryLength", _("Password history length"), readonly=True),
            IntAttr("hrcSmbLogonToChgPwd", _("Logon required to change password"), readonly=True),
            IntAttr("hrcSmbLockoutDuration", _("Lockout duration"), readonly=True),
            IntAttr(
                "hrcSmbLockoutObservationWindow", _("Lockout observation window"), readonly=True
            ),
            IntAttr("hrcSmbLockoutThreshold", _("Lockout threshold"), readonly=True),
            IntAttr("hrcSmbForceLogoff", _("Force logoff"), readonly=True),
            IntAttr(
                "hrcSmbRefuseMachinePwdChange", _("Refuse machine password change"), readonly=True
            ),
        )
        counters = Section(
            _("Counters"),
            IntAttr("hrcSmbNextRid", _("Next RID"), readonly=True),
            IntAttr("hrcSmbNextGroupRid", _("Next group RID"), readonly=True),
            IntAttr("hrcSmbNextUserRid", _("Next user RID"), readonly=True),
        )


# ---------------------------------------------------------------- lock hook


def lock_account(entry: Entry, locked: bool) -> list[Modification]:
    """Account lock hook: add (or remove) the ``D`` flag of ``hrcSmbAcctFlags``."""
    if not entry.has_object_class("hrcSmbAccount"):
        return []
    raw = entry.text("hrcSmbAcctFlags")
    if raw is None:
        return []
    letters = parse_flags(raw)
    updated = format_flags(set_flag(letters, FLAG_DISABLED, locked))
    if updated == raw:
        return []
    return [Modification("replace", "hrcSmbAcctFlags", [updated.encode()])]


def plugin() -> Plugin:
    """Entry point of the SMB plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(SMBDomain,),
        tabs=(
            TabAttachment("user", SMBUserTab),
            TabAttachment("posix_group", SMBGroupTab),
            TabAttachment("workstation", SMBWorkstationTab),
        ),
        required_object_classes=(
            "hrcSmbAccount",
            "hrcSmbGroupMapping",
            "posixGroup",
            "hrcWorkstation",
        ),
        account_lock_hooks=(lock_account,),
        settings=SMBSettings(),
    )


__all__ = [
    "SMBDomain",
    "SMBGroupTab",
    "SMBSettings",
    "SMBUserTab",
    "SMBWorkstationTab",
    "grid_to_hours",
    "hours_to_grid",
    "lock_account",
    "plugin",
]
