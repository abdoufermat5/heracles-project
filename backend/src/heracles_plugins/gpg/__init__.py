"""GPG plugin: PGP keys (``pgpKeyInfo``), key server info, and user tab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from heracles.attributes import (
    AnyAttribute,
    BooleanAttr,
    DateTimeAttr,
    DepartmentAttr,
    DisplayAttr,
    ListAttr,
    ObjectRefAttr,
    StringAttr,
    TextAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext
from heracles_plugins.gpg.parser import (
    ParsedPgpKey,
    normalize_hex,
    parse_openpgp_key,
)

PLUGIN_NAME = "gpg"


def virtual[A: AnyAttribute](attr: A) -> A:
    """Mark an attribute as virtual (never written directly to LDAP)."""
    attr.stored = False
    return attr


@dataclass(slots=True)
class GpgSettings:
    """Settings of the GPG plugin."""

    keys_rdn: str = "ou=pgp"
    server_software: str = "Heracles PGP"
    server_version: str = "1.0"


def settings_of(ctx: TabContext) -> GpgSettings:
    """Read GPG settings from context."""
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, GpgSettings) else GpgSettings()


def summarize_user_keys(values: dict[str, Any]) -> str | None:
    """Read-only summary of the user's referenced PGP keys."""
    raw = values.get("hrcUserKeyDN")
    if not isinstance(raw, list) or not raw:
        return None
    items = cast("list[object]", raw)
    lines: list[str] = []
    for item in items:
        if isinstance(item, str):
            lines.append(item)
    return "\n".join(lines) or None


class GpgAccountTab(Tab):
    """User tab referencing PGP keys."""

    name = "gpg"
    acl_key = "gpgAccount"
    label = _("GPG")
    description = _("OpenPGP key and key server settings")
    optional = True
    object_classes = ("hrcGpgAccount",)

    keys = Section(
        _("PGP keys"),
        ListAttr(
            "hrcUserKeyDN",
            _("PGP keys"),
            ObjectRefAttr("key", _("PGP key"), ref_type="pgp_key"),
        ),
        DisplayAttr("gpgSummary", _("Key summary"), compute=summarize_user_keys),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        raw_keys = ctx.values.get("hrcUserKeyDN")
        if not isinstance(raw_keys, list) or not raw_keys:
            ctx.values["gpgSummary"] = None
            return
        lines: list[str] = []
        for dn_obj in cast("list[object]", raw_keys):
            if not isinstance(dn_obj, str):
                continue
            entry = ctx.directory.get(dn_obj, ["pgpCertID", "pgpUserID", "pgpKey"])
            if entry is not None:
                cert_id = entry.text("pgpCertID") or ""
                uid_text = entry.text("pgpUserID") or ""
                fp = _fingerprint_of(entry.text("pgpKey"))
                suffix = f" ({fp})" if fp else ""
                lines.append(f"{cert_id} - {uid_text}{suffix}".strip())
            else:
                lines.append(dn_obj)
        ctx.values["gpgSummary"] = "\n".join(lines) if lines else None


class ZeroOneAttr(BooleanAttr):
    """Boolean stored as ``1`` / ``0`` (key server schema convention)."""

    def from_ldap(self, values: list[bytes]) -> bool | None:
        if not values:
            return None
        return values[0].strip() not in (b"", b"0")

    def to_ldap(self, value: bool | None) -> list[bytes]:
        if value is None:
            return []
        return [b"1" if value else b"0"]


def _fingerprint_of(armored: object) -> str | None:
    """Fingerprint computed from the stored public key (not stored itself)."""
    if not isinstance(armored, str) or not armored.strip():
        return None
    parsed = parse_openpgp_key(armored)
    return parsed.fingerprint if parsed is not None else None


class PgpKey(ObjectType):
    """An OpenPGP public key entry (``pgpKeyInfo``)."""

    name = "pgp_key"
    icon = "key"
    label = _("PGP key")
    label_plural = _("PGP keys")
    category = "access"
    acl_category = "pgpKey"
    required_object_classes = ("top",)
    filter = "(objectClass=pgpKeyInfo)"
    main_attr = "pgpCertID"
    rdn = "ou=pgp"
    columns = ("pgpCertID", "pgpUserID", "pgpKeyType")
    search_attrs = ("pgpCertID", "pgpUserID", "pgpKeyID")

    class Main(Tab):
        name = "main"
        acl_key = "pgpKey"
        label = _("PGP key")
        object_classes = ("pgpKeyInfo", "top")

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr(
                "pgpCertID",
                _("Key ID"),
                required=True,
                pattern=r"^[0-9A-Fa-f]{8,16}$",
                description=_("8 or 16 hexadecimal characters"),
            ),
            StringAttr("pgpKeyID", _("Secondary key ID")),
            StringAttr("pgpUserID", _("User identity"), required=True),
            DisplayAttr(
                "fingerprint",
                _("Fingerprint"),
                compute=lambda values: _fingerprint_of(values.get("pgpKey")),
            ),
            StringAttr("pgpKeyType", _("Key type")),
            DateTimeAttr("pgpKeyCreateTime", _("Creation time")),
            DateTimeAttr("pgpKeyExpireTime", _("Expiration time")),
            ZeroOneAttr("pgpRevoked", _("Revoked"), default=False),
            ZeroOneAttr("pgpDisabled", _("Disabled"), default=False),
        )

        key_data = Section(
            _("Key material"),
            TextAttr("pgpKey", _("ASCII armored public key")),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            if ctx.creating and not ctx.errors:
                ensure_container(ctx.directory, dnlib.join(ctx.info.type.rdn, ctx.base))
            raw_key = ctx.values.get("pgpKey")
            if isinstance(raw_key, str) and raw_key.strip():
                parsed = parse_openpgp_key(raw_key)
                if parsed is not None:
                    if not ctx.values.get("pgpCertID"):
                        ctx.values["pgpCertID"] = parsed.cert_id
                    if not ctx.values.get("pgpUserID") and parsed.user_id:
                        ctx.values["pgpUserID"] = parsed.user_id
                    if not ctx.values.get("pgpKeyType") and parsed.key_type:
                        ctx.values["pgpKeyType"] = parsed.key_type
                    if not ctx.values.get("pgpKeyCreateTime") and parsed.created_at:
                        ctx.values["pgpKeyCreateTime"] = parsed.created_at

            cert_id = ctx.values.get("pgpCertID")
            if isinstance(cert_id, str):
                ctx.values["pgpCertID"] = normalize_hex(cert_id)


class PgpServerInfo(ObjectType):
    """PGP server information entry (``pgpServerInfo``)."""

    name = "pgp_server_info"
    icon = "settings"
    label = _("PGP server info")
    label_plural = _("PGP server info")
    nav = "secondary"
    nav_group = "settings"
    category = "configuration"
    acl_category = "configuration"
    required_object_classes = ("top",)
    filter = "(objectClass=pgpServerInfo)"
    main_attr = "cn"
    rdn = "ou=configs"
    columns = ("cn", "pgpSoftware", "pgpVersion")

    class Main(Tab):
        name = "main"
        acl_key = "pgpServerInfo"
        label = _("Server info")
        object_classes = ("pgpServerInfo", "top")

        properties = Section(
            _("Properties"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Name"), required=True),
            StringAttr("pgpSoftware", _("Software name")),
            StringAttr("pgpVersion", _("Software version")),
            StringAttr("pgpBaseKeySpaceDN", _("Base key branch DN")),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            if ctx.creating and not ctx.errors:
                ensure_container(ctx.directory, dnlib.join(ctx.info.type.rdn, ctx.base))


def plugin() -> Plugin:
    """Entry point of the GPG plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(PgpKey, PgpServerInfo),
        tabs=(TabAttachment("user", GpgAccountTab),),
        settings=GpgSettings(),
    )


__all__ = [
    "PLUGIN_NAME",
    "GpgAccountTab",
    "GpgSettings",
    "ParsedPgpKey",
    "PgpKey",
    "PgpServerInfo",
    "normalize_hex",
    "parse_openpgp_key",
    "plugin",
]
