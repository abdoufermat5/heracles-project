"""FreeRADIUS plugin: RADIUS account profile tab on users and groups."""

from __future__ import annotations

from heracles.attributes import (
    DateAttr,
    IntAttr,
    ObjectRefAttr,
    StringAttr,
)
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "freeradius"


class FreeradiusAccountTab(Tab):
    """RADIUS account profile on a user (radiusprofile)."""

    name = "freeradius"
    acl_key = "freeradiusAccount"
    label = _("RADIUS")
    optional = True
    object_classes = ("radiusprofile",)

    network = Section(
        _("Network and protocol"),
        StringAttr("radiusFramedProtocol", _("Framed protocol")),
        StringAttr("radiusFramedIPAddress", _("Framed IP address")),
        StringAttr("radiusFramedIPNetmask", _("Framed IP netmask")),
        IntAttr("radiusFramedMTU", _("Framed MTU"), min=0),
        StringAttr("radiusFramedCompression", _("Framed compression")),
        StringAttr("radiusServiceType", _("Service type")),
    )
    timeouts = Section(
        _("Timeouts and limits"),
        IntAttr("radiusSessionTimeout", _("Session timeout (seconds)"), min=0),
        IntAttr("radiusIdleTimeout", _("Idle timeout (seconds)"), min=0),
        IntAttr("radiusPortLimit", _("Port limit"), min=0),
        DateAttr("radiusExpiration", _("Expiration date")),
    )
    tunnel = Section(
        _("Tunnel attributes"),
        StringAttr("radiusTunnelMediumType", _("Tunnel medium type")),
        StringAttr("radiusTunnelType", _("Tunnel type")),
        StringAttr("radiusTunnelPrivateGroupId", _("Tunnel private group ID")),
        ObjectRefAttr("radiusGroupName", _("RADIUS group"), ref_type="group"),
    )
    custom = Section(
        _("RADIUS attributes"),
        StringAttr("radiusControlAttribute", _("Control attribute")),
        StringAttr("radiusReplyAttribute", _("Reply attribute")),
        StringAttr("radiusRequestAttribute", _("Request attribute")),
    )


class FreeradiusGroupTab(Tab):
    """RADIUS profile on a group (radiusprofile)."""

    name = "freeradius"
    acl_key = "freeradiusGroup"
    label = _("RADIUS")
    optional = True
    object_classes = ("radiusprofile",)

    tunnel = Section(
        _("Tunnel attributes"),
        StringAttr("radiusTunnelMediumType", _("Tunnel medium type")),
        StringAttr("radiusTunnelType", _("Tunnel type")),
        StringAttr("radiusTunnelPrivateGroupId", _("Tunnel private group ID")),
    )


def plugin() -> Plugin:
    """Entry point of the FreeRADIUS plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        tabs=(
            TabAttachment("user", FreeradiusAccountTab),
            TabAttachment("group", FreeradiusGroupTab),
        ),
        required_object_classes=(),
    )


__all__ = [
    "PLUGIN_NAME",
    "FreeradiusAccountTab",
    "FreeradiusGroupTab",
    "plugin",
]
