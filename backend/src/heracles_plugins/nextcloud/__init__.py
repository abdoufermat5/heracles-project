"""Nextcloud plugin: storage quota and home folder on user accounts."""

from __future__ import annotations

import re
from typing import Any

from heracles.attributes import JSON, Attribute, StringAttr, ValidationError
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "nextcloud"

_BYTE_SIZE_RE = re.compile(
    r"^(?:-1|none|unlimited|default|\d+(?:\.\d+)?\s*(?:[KMGTP]?i?B|B|Bytes)?)$",
    re.IGNORECASE,
)


def virtual[A: Attribute[Any]](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False
    return attr


class BytesSizeAttr(StringAttr):
    """Size in bytes or human-readable storage format (e.g. '10 GB', '500 MB', 'unlimited')."""

    kind = "string"

    def from_json(self, data: object) -> str | None:
        if data is None or data == "":
            return None
        if isinstance(data, int | float) and not isinstance(data, bool):
            if isinstance(data, float) and not data.is_integer():
                raise ValidationError(_("Expected an integer byte count."))
            val_int = int(data)
            if val_int < -1:
                raise ValidationError(_("Byte count cannot be negative."))
            return str(val_int)
        if not isinstance(data, str):
            raise ValidationError(_("Expected a storage size string or byte count."))
        stripped = data.strip()
        return stripped if stripped else None

    def to_json(self, value: str | None) -> JSON:
        return value

    def _validate(self, value: str) -> list[str]:
        errors = self._check_text(value)
        if _BYTE_SIZE_RE.fullmatch(value.strip()) is None:
            errors.append(_("Invalid storage size (e.g. '10 GB', '500 MB', 'unlimited')."))
        return errors


class NextcloudAccountTab(Tab):
    """Nextcloud user account tab (storage quota and home folder)."""

    name = "nextcloud"
    acl_key = "nextcloudAccount"
    label = _("Nextcloud")
    description = _("File sharing and sync account")
    optional = True
    object_classes = ("hrcNextCloudAccount",)

    storage = Section(
        _("Nextcloud storage"),
        BytesSizeAttr(
            "hrcNextCloudQuota",
            _("Quota"),
            description=_("Storage quota (e.g. '10 GB', '500 MB', 'unlimited')"),
        ),
        StringAttr(
            "hrcNextCloudHomeFolder",
            _("Home folder"),
            description=_("Path or template for the user's home folder"),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Nextcloud plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("user", NextcloudAccountTab),),
        required_object_classes=(),
    )


__all__ = [
    "PLUGIN_NAME",
    "BytesSizeAttr",
    "NextcloudAccountTab",
    "plugin",
]
