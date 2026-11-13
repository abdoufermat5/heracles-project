"""Quota plugin: per-filesystem user quotas and server quota service."""

from __future__ import annotations

import re

from heracles.attributes import (
    CompositeAttr,
    IntAttr,
    ListAttr,
    SelectAttr,
    StringAttr,
    TextAttr,
    ValidationError,
)
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles_plugins._secrets import CleartextSecretAttr

PLUGIN_NAME = "quota"

_BLOCK_LIMIT_RE = re.compile(
    r"^(?:-1|none|unlimited|\d+(?:\.\d+)?\s*(?:[KMGTP]?i?B|B|Bytes|k|m|g|t|p)?)$",
    re.IGNORECASE,
)


class BlockLimitAttr(StringAttr):
    """Quota block limit accepting integer counts or size strings."""

    kind = "string"

    def from_json(self, data: object) -> str | None:
        if data is None or data == "":
            return None
        if isinstance(data, int | float) and not isinstance(data, bool):
            if isinstance(data, float) and not data.is_integer():
                raise ValidationError(_("Expected an integer block count."))
            val_int = int(data)
            if val_int < -1:
                raise ValidationError(_("Block count cannot be negative."))
            return str(val_int)
        if not isinstance(data, str):
            raise ValidationError(_("Expected a block count or size string."))
        stripped = data.strip()
        return stripped if stripped else None

    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        if _BLOCK_LIMIT_RE.fullmatch(value.strip()) is None:
            errors.append(_("Invalid block limit."))
        return errors


class QuotaEntryAttr(CompositeAttr):
    """One filesystem quota rule (device:blockSoft:blockHard:inodeSoft:inodeHard:server)."""

    def __init__(self, name: str = "entry", label: str = "") -> None:
        super().__init__(
            name,
            label or _("Quota entry"),
            fields=(
                StringAttr("hrcQuotaDevice", _("Device / mount point"), required=True),
                BlockLimitAttr("quotaBlockSoftLimit", _("Block soft limit")),
                BlockLimitAttr("quotaBlockHardLimit", _("Block hard limit")),
                IntAttr("quotaInodeSoftLimit", _("Inode soft limit"), min=0),
                IntAttr("quotaInodeHardLimit", _("Inode hard limit"), min=0),
                StringAttr("quotaServer", _("Server")),
            ),
            separator=":",
        )


class QuotaAccountTab(Tab):
    """User disk quota tab (systemQuotas)."""

    name = "quota"
    acl_key = "quotaAccount"
    label = _("Quotas")
    description = _("Disk usage limits for this account")
    optional = True
    object_classes = ("systemQuotas",)
    requires = ("posix",)

    quotas = Section(
        _("Filesystem quotas"),
        ListAttr(
            "quota",
            _("Quotas"),
            QuotaEntryAttr("entry", _("Quota rule")),
        ),
    )


class ServiceQuotaTab(Tab):
    """Server quota service tab (hrcQuotaService)."""

    name = "serviceQuota"
    acl_key = "serviceQuota"
    label = _("Quota service")
    optional = True
    object_classes = ("hrcQuotaService",)

    properties = Section(
        _("Properties"),
        StringAttr("hrcQuotaDevice", _("Device")),
        IntAttr("hrcQuotaBlockSize", _("Block size"), min=0, default=1024),
        StringAttr("hrcQuotaDesc", _("Description")),
    )
    warning_messages = Section(
        _("Warning messages"),
        SelectAttr(
            "hrcQuotaMsgCharsetSupport",
            _("Message charset"),
            options=[
                ("UTF-8", "UTF-8"),
                ("ISO-8859-1", "ISO-8859-1"),
                ("US-ASCII", "US-ASCII"),
            ],
            default="UTF-8",
        ),
        StringAttr("hrcQuotaMailCommand", _("Mail command")),
        StringAttr("hrcQuotaMsgFromSupport", _("From address")),
        StringAttr("hrcQuotaMsgContactSupport", _("Support contact")),
        StringAttr("hrcQuotaCarbonCopyMail", _("Carbon copy address")),
        StringAttr("hrcQuotaMsgSubjectSupport", _("Subject")),
        TextAttr("hrcQuotaMsgContentSupport", _("Message body")),
        StringAttr("hrcQuotaMsgSignatureSupport", _("Signature")),
    )
    ldap_access = Section(
        _("LDAP access"),
        StringAttr("hrcQuotaLdapServer", _("LDAP server")),
        StringAttr("hrcQuotaLdapServerUserDn", _("LDAP user DN")),
        CleartextSecretAttr(
            "hrcQuotaLdapServerUserPassword",
            _("LDAP password"),
            description=_("Leave empty to keep the current password"),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the quota plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(
            TabAttachment("user", QuotaAccountTab),
            TabAttachment("server", ServiceQuotaTab),
        ),
        required_object_classes=(),
    )


__all__ = [
    "PLUGIN_NAME",
    "BlockLimitAttr",
    "QuotaAccountTab",
    "QuotaEntryAttr",
    "ServiceQuotaTab",
    "plugin",
]
