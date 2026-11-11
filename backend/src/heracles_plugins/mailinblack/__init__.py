"""Mailinblack plugin: user email protection tab."""

from __future__ import annotations

from heracles.attributes import BooleanAttr
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "mailinblack"


class MailInBlackUserTab(Tab):
    """Mailinblack protection tab on users."""

    name = "mailinblack"
    acl_key = "mailInBlackUser"
    label = _("Mailinblack")
    description = _("Anti-spam quarantine service account")
    description = _("Mailinblack email protection")
    optional = True
    object_classes = ("hrcMailInBlackUser",)

    protection = Section(
        _("Protection"),
        BooleanAttr(
            "hrcMailInBlackProtect",
            _("Protect"),
            default=True,
            description=_("Protect this user with Mailinblack anti-spam and security"),
        ),
    )


def plugin() -> Plugin:
    """Entry point of the Mailinblack plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(TabAttachment("user", MailInBlackUserTab),),
    )


__all__ = [
    "PLUGIN_NAME",
    "MailInBlackUserTab",
    "plugin",
]
