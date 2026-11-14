"""Mail protection plugin: user email protection tab."""

from __future__ import annotations

from heracles.attributes import BooleanAttr
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "mail_protection"


class MailProtectionUserTab(Tab):
    """Mail protection tab on users."""

    name = "mail_protection"
    acl_key = "mailProtectionUser"
    label = _("Mail protection")
    description = _("Anti-spam and email protection")
    optional = True
    object_classes = ("hrcMailProtectionUser",)

    protection = Section(
        _("Protection"),
        BooleanAttr(
            "hrcMailProtectionProtect",
            _("Protect"),
            default=True,
            description=_("Protect this user with Mail protection anti-spam and security"),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Mail protection plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("user", MailProtectionUserTab),),
    )


__all__ = [
    "PLUGIN_NAME",
    "MailProtectionUserTab",
    "plugin",
]
