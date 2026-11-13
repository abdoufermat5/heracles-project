"""IPMI plugin: IPMI BMC client tab on servers and workstations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from heracles.attributes import PasswordAttr, StringAttr
from heracles.i18n import _
from heracles.objects import Plugin, Section, Tab, TabAttachment

PLUGIN_NAME = "ipmi"


@dataclass(slots=True)
class IpmiSettings:
    """Settings of the IPMI plugin."""


def _cleartext_hasher(password: str) -> str:
    return password


class CleartextPasswordAttr(PasswordAttr):
    """Write-only password stored in cleartext (as required by IPMI BMC protocol)."""

    def __init__(self, name: str, label: str, **kwargs: Any) -> None:
        kwargs.setdefault("hasher", _cleartext_hasher)
        super().__init__(name, label, **kwargs)


class IpmiClientTab(Tab):
    """IPMI client tab attached to servers and workstations."""

    name = "ipmi"
    acl_key = "ipmiClient"
    label = _("IPMI")
    object_classes = ("hrcIpmiClient",)
    optional = True

    bmc = Section(
        _("BMC connection"),
        StringAttr(
            "hrcIpmiIP",
            _("IP address"),
            description=_("IP address or host name of the BMC"),
        ),
        StringAttr(
            "hrcIpmiLogin",
            _("Login"),
            description=_("IPMI management user"),
        ),
        CleartextPasswordAttr(
            "hrcIpmiPassword",
            _("Password"),
            description=_("IPMI management password"),
        ),
    )


# --------------------------------------------------------------- plugin entry


#: The BMC client tab on every system type. Types absent from a registry
#: (plugin off, schema without them) are skipped by ``register_plugins``.
TABS: tuple[TabAttachment, ...] = (
    TabAttachment("server", IpmiClientTab),
    TabAttachment("workstation", IpmiClientTab),
)


def plugin() -> Plugin:
    """Entry point of the IPMI plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(),
        tabs=TABS,
        required_object_classes=("hrcIpmiClient",),
        settings=IpmiSettings(),
    )


__all__ = [
    "PLUGIN_NAME",
    "CleartextPasswordAttr",
    "IpmiClientTab",
    "IpmiSettings",
    "plugin",
]
