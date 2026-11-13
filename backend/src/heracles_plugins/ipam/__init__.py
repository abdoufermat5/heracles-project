"""IPAM plugin: IP address management (VLANs and Subnets)."""

from __future__ import annotations

from dataclasses import dataclass

from heracles.attributes import (
    BooleanAttr,
    DateAttr,
    IntAttr,
    ObjectRefAttr,
    StringAttr,
    TextAttr,
)
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.objects import ObjectType, Plugin, Reference, Section, Tab
from heracles.objects.hooks import TabContext
from heracles_plugins.ipam.cidr import CidrAttr, find_used_ips, next_free_ip

PLUGIN_NAME = "ipam"


@dataclass(slots=True)
class IpamSettings:
    """Settings of the IPAM plugin."""

    subnet_rdn: str = "ou=ipam"
    vlan_rdn: str = "ou=ipam"


# ---------------------------------------------------------------------- VLAN


class IpamVlanTab(Tab):
    """Main tab of an IPAM VLAN."""

    name = "main"
    acl_key = "ipamVlan"
    label = _("VLAN")
    object_classes = ("hrcIpamVlan",)

    identity = Section(
        _("Properties"),
        StringAttr("cn", _("Name"), required=True, max_length=64),
        TextAttr("description", _("Description")),
        BooleanAttr("hrcIpamActive", _("Active"), default=True),
        StringAttr("o", _("Organization")),
        IntAttr("hrcIpamVlanInnerId", _("VLAN ID"), min=1, max=4094),
        IntAttr("hrcIpamVlanQinQId", _("QinQ VLAN ID"), min=1, max=4094),
        StringAttr("hrcIpamApplicant", _("Applicant")),
    )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        ensure_container(ctx.directory, dnlib.join(ctx.info.type.rdn, ctx.base))


class IpamVlan(ObjectType):
    """An IPAM VLAN."""

    name = "ipamVlan"
    acl_category = "ipamVlan"
    label = _("IPAM VLAN")
    label_plural = _("IPAM VLANs")
    icon = "layers"
    category = "network"
    filter = "(objectClass=hrcIpamVlan)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=ipam"
    columns = ("cn", "hrcIpamVlanInnerId", "description")
    search_attrs = ("cn", "description", "hrcIpamVlanInnerId", "hrcIpamVlanQinQId")
    references = (Reference("ipamSubnet", "hrcIpamVlanDN"),)

    Main = IpamVlanTab


# -------------------------------------------------------------------- Subnet


class IpamSubnetTab(Tab):
    """Main tab of an IPAM Subnet."""

    name = "main"
    acl_key = "ipamSubnet"
    label = _("Subnet")
    object_classes = ("hrcIpamSubnet",)

    identity = Section(
        _("Properties"),
        StringAttr("cn", _("Name"), required=True, max_length=64),
        CidrAttr("hrcIpamSubnetCIDR", _("Subnet CIDR"), required=True),
        TextAttr("description", _("Description")),
        BooleanAttr("hrcIpamActive", _("Active"), default=True),
        StringAttr("o", _("Organization")),
        StringAttr("hrcIpamType", _("Type")),
        StringAttr("hrcIpamApplicant", _("Applicant")),
        DateAttr("hrcIpamAllocationDate", _("Allocation date")),
        DateAttr("hrcIpamReleaseDate", _("Release date")),
        ObjectRefAttr("hrcIpamVlanDN", _("VLAN"), ref_type="ipamVlan"),
    )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        ensure_container(ctx.directory, dnlib.join(ctx.info.type.rdn, ctx.base))


class IpamSubnet(ObjectType):
    """An IPAM Subnet."""

    name = "ipamSubnet"
    acl_category = "ipamSubnet"
    label = _("IPAM Subnet")
    label_plural = _("IPAM Subnets")
    icon = "network"
    category = "network"
    filter = "(objectClass=hrcIpamSubnet)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=ipam"
    columns = ("cn", "hrcIpamSubnetCIDR", "description")
    search_attrs = ("cn", "description", "hrcIpamSubnetCIDR")

    Main = IpamSubnetTab


# --------------------------------------------------------------- plugin entry


def plugin() -> Plugin:
    """Entry point of the IPAM plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(IpamVlan, IpamSubnet),
        required_object_classes=("hrcIpamVlan", "hrcIpamSubnet"),
        settings=IpamSettings(),
    )


__all__ = [
    "PLUGIN_NAME",
    "CidrAttr",
    "IpamSettings",
    "IpamSubnet",
    "IpamSubnetTab",
    "IpamVlan",
    "IpamVlanTab",
    "find_used_ips",
    "next_free_ip",
    "plugin",
]
