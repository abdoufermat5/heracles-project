"""DHCP plugin: ISC DHCP configuration and section tree stored in LDAP."""

from __future__ import annotations

from heracles.objects import Plugin
from heracles_plugins.dhcp.attributes import (
    Base64StringAttr,
    HwAddressAttr,
    MacAddressAttr,
    virtual,
)
from heracles_plugins.dhcp.router import build_router
from heracles_plugins.dhcp.tree import build_dhcp_tree
from heracles_plugins.dhcp.types import (
    ALL_TYPES,
    DhcpClass,
    DhcpConfiguration,
    DhcpDnsZone,
    DhcpFailOverPeer,
    DhcpGroup,
    DhcpHost,
    DhcpPool,
    DhcpSharedNetwork,
    DhcpSubClass,
    DhcpSubnet,
    DhcpTSigKey,
)
from heracles_plugins.dhcp.validation import (
    ALLOWED_CHILDREN_BY_CLASS,
    CLASS_BY_TYPE,
    TYPE_BY_CLASS,
    find_dhcp_class,
    normalize_dhcp_options,
    validate_ipv4,
    validate_mac,
    validate_range,
    validate_subnet_network,
)

PLUGIN_NAME = "dhcp"


def plugin() -> Plugin:
    """Entry point of the DHCP plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=ALL_TYPES,
        api_routers=(build_router,),
        required_object_classes=("dhcpService",),
    )


__all__ = [
    "ALLOWED_CHILDREN_BY_CLASS",
    "ALL_TYPES",
    "CLASS_BY_TYPE",
    "PLUGIN_NAME",
    "TYPE_BY_CLASS",
    "Base64StringAttr",
    "DhcpClass",
    "DhcpConfiguration",
    "DhcpDnsZone",
    "DhcpFailOverPeer",
    "DhcpGroup",
    "DhcpHost",
    "DhcpPool",
    "DhcpSharedNetwork",
    "DhcpSubClass",
    "DhcpSubnet",
    "DhcpTSigKey",
    "HwAddressAttr",
    "MacAddressAttr",
    "build_dhcp_tree",
    "build_router",
    "find_dhcp_class",
    "normalize_dhcp_options",
    "plugin",
    "validate_ipv4",
    "validate_mac",
    "validate_range",
    "validate_subnet_network",
    "virtual",
]
