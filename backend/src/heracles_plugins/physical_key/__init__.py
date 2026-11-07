"""Physical key plugin: badge and hardware key identifiers on users (``fdPhysicalKey``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from heracles.attributes import (
    SelectAttr,
    StringAttr,
)
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext

PLUGIN_NAME = "physical_key"

PHYSICAL_KEY_TYPES: Final[tuple[tuple[str, str], ...]] = (
    ("rfid", _("RFID badge")),
    ("nfc", _("NFC tag")),
    ("mifare", _("Mifare card")),
    ("hid", _("HID proximity card")),
    ("fido2", _("FIDO2 security key")),
    ("yubikey", _("YubiKey")),
    ("barcode", _("Barcode")),
    ("magstripe", _("Magnetic stripe")),
    ("other", _("Other")),
)


@dataclass(slots=True)
class PhysicalKeySettings:
    """Settings of the physical key plugin."""

    default_type: str = "rfid"


def settings_of(ctx: TabContext) -> PhysicalKeySettings:
    """Read physical key settings from context."""
    value = ctx.settings.get(PLUGIN_NAME)
    return value if isinstance(value, PhysicalKeySettings) else PhysicalKeySettings()


class PhysicalKeyAccountTab(Tab):
    """User account tab managing physical badge / hardware key identifiers."""

    name = "physical_key"
    acl_key = "PhysicalKeyAccount"
    label = _("Physical key")
    optional = True
    object_classes = ("fdPhysicalKey",)

    key_info = Section(
        _("Physical key"),
        SelectAttr(
            "fdPhysicalKeyType",
            _("Key type"),
            options=PHYSICAL_KEY_TYPES,
        ),
        StringAttr(
            "fdPhysicalKeyValue",
            _("Identifier / Badge number"),
            description=_("Hex, decimal or serial identifier of the badge or token"),
        ),
    )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        if ctx.creating and not ctx.values.get("fdPhysicalKeyType"):
            settings = settings_of(ctx)
            if settings.default_type:
                ctx.values["fdPhysicalKeyType"] = settings.default_type


def plugin() -> Plugin:
    """Entry point of the physical key plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("user", PhysicalKeyAccountTab),),
        settings=PhysicalKeySettings(),
    )


__all__ = [
    "PHYSICAL_KEY_TYPES",
    "PLUGIN_NAME",
    "PhysicalKeyAccountTab",
    "PhysicalKeySettings",
    "plugin",
]
