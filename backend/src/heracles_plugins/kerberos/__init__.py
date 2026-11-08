"""Kerberos plugin: MIT krb5 principal tab on users."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from heracles.attributes import (
    AnyAttribute,
    BooleanAttr,
    DateAttr,
    DateTimeAttr,
    IntAttr,
    ListAttr,
    StringAttr,
)
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext

PLUGIN_NAME = "kerberos"

TICKET_FLAGS: Final[tuple[tuple[str, int, str], ...]] = (
    ("DISALLOW_POSTDATED", 0x00000001, _("Disallow postdated tickets")),
    ("DISALLOW_FORWARDABLE", 0x00000002, _("Disallow forwardable tickets")),
    ("DISALLOW_TGT_BASED", 0x00000004, _("Disallow TGT-based tickets")),
    ("DISALLOW_RENEWABLE", 0x00000008, _("Disallow renewable tickets")),
    ("DISALLOW_PROXIABLE", 0x00000010, _("Disallow proxiable tickets")),
    ("DISALLOW_DUP_SKEY", 0x00000020, _("Disallow duplicate session key")),
    ("DISALLOW_ALL_TIX", 0x00000040, _("Disallow all tickets")),
    ("REQUIRES_PRE_AUTH", 0x00000080, _("Requires pre-authentication")),
    ("REQUIRES_HW_AUTH", 0x00000100, _("Requires hardware authentication")),
    ("REQUIRES_PWCHANGE", 0x00000200, _("Requires password change")),
    ("UNKNOWN_0x00000400", 0x00000400, _("Flag 0x00000400")),
    ("UNKNOWN_0x00000800", 0x00000800, _("Flag 0x00000800")),
    ("DISALLOW_SVR", 0x00001000, _("Disallow server tickets")),
    ("PWCHANGE_SERVICE", 0x00002000, _("Password change service")),
    ("SUPPORT_DESMD5", 0x00004000, _("Support DES-MD5")),
    ("NEW_PRINC", 0x00008000, _("New principal")),
)


def virtual[A: AnyAttribute](attr: A) -> A:
    """Mark an attribute as virtual (never written directly to LDAP)."""
    attr.stored = False
    return attr


class KrbUPEnabledAttr(BooleanAttr):
    """Boolean stored as integer 1/0 or TRUE/FALSE in LDAP."""

    def from_ldap(self, values: list[bytes]) -> bool | None:
        if not values:
            return None
        text = values[0].decode("ascii", errors="replace").strip().upper()
        if text in ("1", "TRUE"):
            return True
        if text in ("0", "FALSE"):
            return False
        return None

    def to_ldap(self, value: bool | None) -> list[bytes]:
        if value is None:
            return []
        return [b"1" if value else b"0"]


@dataclass(slots=True)
class KerberosSettings:
    """Settings of the Kerberos plugin."""

    default_realm: str = ""


def settings_of(ctx: TabContext) -> KerberosSettings:
    """Read plugin settings from context."""
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, KerberosSettings) else KerberosSettings()


class KerberosAccountTab(Tab):
    """Kerberos principal tab for user accounts."""

    name = "kerberos"
    acl_key = "kerberosAccount"
    label = _("Kerberos")
    optional = True
    object_classes = ("krbPrincipalAux", "krbTicketPolicyAux")

    identity = Section(
        _("Principal identity"),
        StringAttr("krbPrincipalName", _("Principal name"), required=True),
        StringAttr("krbCanonicalName", _("Canonical name")),
        ListAttr(
            "krbPrincipalAliases",
            _("Principal aliases"),
            StringAttr("alias", _("Alias")),
        ),
        IntAttr("krbPrincipalType", _("Principal type"), default=1),
        KrbUPEnabledAttr("krbUPEnabled", _("User-to-user authentication enabled")),
    )

    policy = Section(
        _("Ticket and password policy"),
        StringAttr("krbTicketPolicyReference", _("Ticket policy reference DN")),
        StringAttr("krbPwdPolicyReference", _("Password policy reference DN")),
        IntAttr("krbMaxTicketLife", _("Maximum ticket life (seconds)"), min=0),
        DateAttr("krbPrincipalExpiration", _("Principal expiration date")),
    )

    flags = Section(
        _("Ticket flags"),
        IntAttr("krbTicketFlags", _("Ticket flags bitmask"), default=0),
        *(virtual(BooleanAttr(name, label, default=False)) for name, _, label in TICKET_FLAGS),
    )

    delegation = Section(
        _("Delegation and authentication"),
        ListAttr(
            "krbAllowedToDelegateTo",
            _("Allowed to delegate to"),
            StringAttr("service", _("Service")),
        ),
        ListAttr(
            "krbPrincipalAuthInd",
            _("Authentication indicators"),
            StringAttr("indicator", _("Indicator")),
        ),
        StringAttr("krbExtraData", _("Extra data")),
    )

    status = Section(
        _("Status"),
        IntAttr("krbLoginFailedCount", _("Failed login count"), readonly=True),
        DateTimeAttr("krbLastAdminUnlock", _("Last admin unlock"), readonly=True),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        raw_flags = ctx.values.get("krbTicketFlags")
        flags = raw_flags if isinstance(raw_flags, int) else 0
        for name, bit, _label in TICKET_FLAGS:
            ctx.values[name] = bool(flags & bit)

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        if any(name in ctx.values for name, _, _label in TICKET_FLAGS):
            flags = 0
            for name, bit, _label in TICKET_FLAGS:
                if ctx.values.get(name):
                    flags |= bit
            ctx.values["krbTicketFlags"] = flags

        if ctx.creating and not ctx.values.get("krbPrincipalName"):
            uid = ctx.main_values().get("uid")
            settings = settings_of(ctx)
            if uid and settings.default_realm:
                ctx.values["krbPrincipalName"] = f"{uid}@{settings.default_realm}"


def plugin() -> Plugin:
    """Entry point of the Kerberos plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("user", KerberosAccountTab),),
        settings=KerberosSettings(),
    )


__all__ = [
    "PLUGIN_NAME",
    "TICKET_FLAGS",
    "KerberosAccountTab",
    "KerberosSettings",
    "KrbUPEnabledAttr",
    "plugin",
]
