"""Web link plugin: web link tab on systems (workstation, server, component, printer)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from heracles.attributes import DisplayAttr, SelectAttr, StringAttr
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext

PLUGIN_NAME = "weblink"


@dataclass(slots=True)
class WeblinkSettings:
    """Settings of the Weblink plugin."""

    default_protocol: str = "https://"


def _compute_weblink(values: dict[str, Any]) -> str | None:
    """Compute the full URL from protocol and URL attributes."""
    url = str(values.get("hrcWebLinkURL") or "").strip()
    if not url:
        return None
    if "://" in url:
        return url
    protocol = str(values.get("hrcWebLinkProtocol") or "https://").strip()
    if not protocol.endswith("//"):
        protocol = f"{protocol}//" if protocol.endswith(":") else f"{protocol}://"
    return f"{protocol}{url.lstrip('/')}"


class WebLinkTab(Tab):
    """Web link tab attached to systems."""

    name = "weblink"
    acl_key = "webLink"
    label = _("Web link")
    object_classes = ("hrcWebLinkAccount",)
    optional = True

    link = Section(
        _("Web link"),
        SelectAttr(
            "hrcWebLinkProtocol",
            _("Protocol"),
            options=[
                ("http://", "HTTP (http://)"),
                ("https://", "HTTPS (https://)"),
            ],
            default="https://",
        ),
        StringAttr(
            "hrcWebLinkURL",
            _("Link URL"),
            description=_("Host, IP address, or URL path"),
        ),
        DisplayAttr("hrcWebLink", _("Web link"), compute=_compute_weblink, stored=True),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        if not ctx.values.get("hrcWebLinkURL") and ctx.values.get("hrcWebLink"):
            full = str(ctx.values["hrcWebLink"]).strip()
            if "://" in full:
                proto, _, rest = full.partition("://")
                ctx.values.setdefault("hrcWebLinkProtocol", f"{proto}://")
                ctx.values["hrcWebLinkURL"] = rest
            else:
                ctx.values["hrcWebLinkURL"] = full


# --------------------------------------------------------------- plugin entry


#: The link tab on every system type. Types absent from a registry (plugin off,
#: schema without them) are skipped by ``register_plugins``.
TABS: tuple[TabAttachment, ...] = (
    TabAttachment("workstation", WebLinkTab),
    TabAttachment("server", WebLinkTab),
    TabAttachment("component", WebLinkTab),
    TabAttachment("printer", WebLinkTab),
)


def plugin() -> Plugin:
    """Entry point of the Weblink plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(),
        tabs=TABS,
        required_object_classes=("hrcWebLinkAccount",),
        settings=WeblinkSettings(),
    )


__all__ = [
    "PLUGIN_NAME",
    "WebLinkTab",
    "WeblinkSettings",
    "plugin",
]
