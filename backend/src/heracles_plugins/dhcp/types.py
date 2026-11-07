"""ObjectTypes and Tabs for DHCP configurations and sections."""

from __future__ import annotations

import contextlib
import ipaddress
from collections.abc import Sequence
from typing import cast

from heracles.attributes import IntAttr, ListAttr, ObjectRefAttr, StringAttr
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import NoSuchObjectError, Scope
from heracles.objects import ObjectType, Section, Tab
from heracles.objects.hooks import TabContext
from heracles_plugins.dhcp.attributes import (
    Base64StringAttr,
    HwAddressAttr,
    dhcp_comments_attr,
    dhcp_options_attr,
    dhcp_range_attr,
    dhcp_statements_attr,
    virtual,
)
from heracles_plugins.dhcp.validation import (
    ALLOWED_CHILDREN_BY_CLASS,
    TYPE_BY_CLASS,
    find_dhcp_class,
    normalize_dhcp_options,
    validate_ipv4,
    validate_range,
    validate_subnet_network,
)

ACL_CATEGORY = "dhcpConfiguration"
CATEGORY = "network"
ICON = "network"


# ---------------------------------------------------------------------------
# Base Tab with delete & allowed-children hooks
# ---------------------------------------------------------------------------


class DhcpSectionTab(Tab):
    """Base tab for DHCP sections providing recursive delete and validation."""

    @classmethod
    def before_delete(cls, ctx: TabContext) -> None:
        """Recursively delete all child entries before this section is deleted."""
        if ctx.dn is None:
            return
        try:
            children = ctx.directory.search(ctx.dn, "(objectClass=*)", Scope.ONE, attrs=["1.1"])
            for child in children:
                with contextlib.suppress(NoSuchObjectError):
                    ctx.directory.delete(child.dn, recursive=True)
        except NoSuchObjectError:
            pass

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        """Normalize options and verify parent-child constraints."""
        options = ctx.values.get("dhcpOption")
        if isinstance(options, Sequence) and not isinstance(options, str | bytes):
            raw_opts = cast("Sequence[object]", options)
            ctx.values["dhcpOption"] = normalize_dhcp_options([str(o) for o in raw_opts])
        # dhcp_configuration is the top-level section under ou=dhcp
        if cls.object_classes == ("dhcpService",):
            if ctx.creating:
                container = dnlib.join("ou=dhcp", ctx.base)
                ensure_container(ctx.directory, container)
            return

        cls._check_parent_allowed(ctx)

    @classmethod
    def _check_parent_allowed(cls, ctx: TabContext) -> None:
        parent_dn = ctx.base if ctx.creating else dnlib.parent(ctx.dn or "")
        if not parent_dn:
            ctx.error(ctx.info.type.main_attr, _("Section must have a parent entry."))
            return
        parent_entry = ctx.directory.get(parent_dn)
        if parent_entry is None:
            ctx.error(
                ctx.info.type.main_attr,
                _("Parent entry does not exist: {dn}").format(dn=parent_dn),
            )
            return
        parent_oc = find_dhcp_class(parent_entry)
        if parent_oc is None:
            ctx.error(
                ctx.info.type.main_attr,
                _("Parent entry is not a valid DHCP section: {dn}").format(dn=parent_dn),
            )
            return
        this_oc = cls.object_classes[0] if cls.object_classes else ""
        allowed = ALLOWED_CHILDREN_BY_CLASS.get(parent_oc, frozenset())
        if this_oc not in allowed:
            this_type = TYPE_BY_CLASS.get(this_oc.lower(), this_oc)
            parent_type = TYPE_BY_CLASS.get(parent_oc.lower(), parent_oc)
            ctx.error(
                ctx.info.type.main_attr,
                _("Section of type '{child}' is not allowed under '{parent}'.").format(
                    child=this_type, parent=parent_type
                ),
            )


# ---------------------------------------------------------------------------
# 1. DHCP Configuration (dhcpService)
# ---------------------------------------------------------------------------


class DhcpConfiguration(ObjectType):
    """Top-level DHCP service configuration."""

    name = "dhcp_configuration"
    label = _("DHCP configuration")
    label_plural = _("DHCP configurations")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpService)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=dhcp"
    columns = ("cn", "dhcpComments")
    search_attrs = ("cn", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpService"
        label = _("Configuration")
        object_classes = ("dhcpService",)

        general = Section(
            _("General"),
            StringAttr("cn", _("Name"), required=True),
            ObjectRefAttr(
                "dhcpPrimaryDN",
                _("Primary server DN"),
                ref_type="dhcp_configuration",
            ),
            ObjectRefAttr(
                "dhcpSecondaryDN",
                _("Secondary server DN"),
                ref_type="dhcp_configuration",
            ),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )


# ---------------------------------------------------------------------------
# 2. Shared Network (dhcpSharedNetwork)
# ---------------------------------------------------------------------------


class DhcpSharedNetwork(ObjectType):
    """Shared network grouping subnets."""

    name = "dhcp_shared_network"
    label = _("Shared network")
    label_plural = _("Shared networks")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpSharedNetwork)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ""
    columns = ("cn", "dhcpComments")
    search_attrs = ("cn", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpSharedNetwork"
        label = _("Shared network")
        object_classes = ("dhcpSharedNetwork",)

        general = Section(
            _("General"),
            StringAttr("cn", _("Name"), required=True),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )


# ---------------------------------------------------------------------------
# 3. Subnet (dhcpSubnet)
# ---------------------------------------------------------------------------


class DhcpSubnet(ObjectType):
    """DHCP subnet definition."""

    name = "dhcp_subnet"
    label = _("Subnet")
    label_plural = _("Subnets")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpSubnet)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ""
    columns = ("cn", "dhcpNetMask", "dhcpComments")
    search_attrs = ("cn", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpSubnet"
        label = _("Subnet")
        object_classes = ("dhcpSubnet",)

        network = Section(
            _("Network"),
            StringAttr("cn", _("Network address"), required=True),
            IntAttr(
                "dhcpNetMask",
                _("Netmask prefix length"),
                min=0,
                max=32,
                required=True,
            ),
            dhcp_range_attr(),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            super().prepare(ctx)
            cn = ctx.values.get("cn")
            mask = ctx.values.get("dhcpNetMask")
            subnet: ipaddress.IPv4Network | None = None
            if isinstance(cn, str) and cn.strip():
                err = validate_ipv4(cn)
                if err is not None:
                    ctx.error("cn", err)
                elif isinstance(mask, int) and 0 <= mask <= 32:
                    net_err = validate_subnet_network(cn, mask)
                    if net_err is not None:
                        ctx.error("cn", net_err)
                    else:
                        subnet = ipaddress.IPv4Network(f"{cn.strip()}/{mask}", strict=False)

            if mask is not None and isinstance(mask, int) and not (0 <= mask <= 32):
                ctx.error("dhcpNetMask", _("Prefix length must be between 0 and 32."))

            ranges = ctx.values.get("dhcpRange")
            if isinstance(ranges, Sequence) and not isinstance(ranges, str | bytes):
                raw_ranges = cast("Sequence[object]", ranges)
                for r in raw_ranges:
                    if isinstance(r, str):
                        r_err = validate_range(r, subnet)
                        if r_err is not None:
                            ctx.error("dhcpRange", r_err)
                            break


# ---------------------------------------------------------------------------
# 4. Pool (dhcpPool)
# ---------------------------------------------------------------------------


class DhcpPool(ObjectType):
    """DHCP dynamic address pool."""

    name = "dhcp_pool"
    label = _("Pool")
    label_plural = _("Pools")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpPool)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ""
    columns = ("cn", "dhcpComments")
    search_attrs = ("cn", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpPool"
        label = _("Pool")
        object_classes = ("dhcpPool",)

        pool = Section(
            _("Pool"),
            StringAttr("cn", _("Name"), required=True),
            dhcp_range_attr(),
            ListAttr[str](
                "dhcpPermitList",
                _("Permit list"),
                StringAttr("permit", _("Permit")),
            ),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            super().prepare(ctx)
            ranges = ctx.values.get("dhcpRange")
            if isinstance(ranges, Sequence) and not isinstance(ranges, str | bytes):
                parent_dn = ctx.base if ctx.creating else dnlib.parent(ctx.dn or "")
                parent_net: ipaddress.IPv4Network | None = None
                if parent_dn:
                    parent_entry = ctx.directory.get(parent_dn)
                    if parent_entry is not None and parent_entry.has_object_class("dhcpSubnet"):
                        p_cn = parent_entry.text("cn")
                        p_mask = parent_entry.text("dhcpNetMask")
                        if p_cn and p_mask and p_mask.strip().isdigit():
                            try:
                                parent_net = ipaddress.IPv4Network(
                                    f"{p_cn.strip()}/{p_mask.strip()}", strict=False
                                )
                            except ValueError:
                                parent_net = None
                raw_pool_ranges = cast("Sequence[object]", ranges)
                for r in raw_pool_ranges:
                    if isinstance(r, str):
                        r_err = validate_range(r, parent_net)
                        if r_err is not None:
                            ctx.error("dhcpRange", r_err)
                            break


# ---------------------------------------------------------------------------
# 5. Group (dhcpGroup)
# ---------------------------------------------------------------------------


class DhcpGroup(ObjectType):
    """DHCP group section."""

    name = "dhcp_group"
    label = _("Group")
    label_plural = _("Groups")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpGroup)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ""
    columns = ("cn", "dhcpComments")
    search_attrs = ("cn", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpGroup"
        label = _("Group")
        object_classes = ("dhcpGroup",)

        general = Section(
            _("General"),
            StringAttr("cn", _("Name"), required=True),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )


# ---------------------------------------------------------------------------
# 6. Host (dhcpHost)
# ---------------------------------------------------------------------------


class DhcpHost(ObjectType):
    """DHCP host reservation."""

    name = "dhcp_host"
    label = _("Host")
    label_plural = _("Hosts")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpHost)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ""
    columns = ("cn", "dhcpHWAddress", "dhcpComments")
    search_attrs = ("cn", "dhcpHWAddress", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpHost"
        label = _("Host")
        object_classes = ("dhcpHost",)

        host = Section(
            _("Host"),
            StringAttr("cn", _("Hostname"), required=True),
            HwAddressAttr("dhcpHWAddress", _("Hardware address")),
            virtual(StringAttr("fixed_address", _("Fixed IP address"))),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )

        @classmethod
        def on_load(cls, ctx: TabContext) -> None:
            stmts = ctx.values.get("dhcpStatements")
            if isinstance(stmts, Sequence) and not isinstance(stmts, str | bytes):
                raw_stmts = cast("Sequence[object]", stmts)
                for s in raw_stmts:
                    if isinstance(s, str) and s.strip().startswith("fixed-address "):
                        ctx.values["fixed_address"] = s.strip()[len("fixed-address ") :].strip()
                        break

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            super().prepare(ctx)
            fixed_ip = ctx.values.get("fixed_address")
            raw_stmts = ctx.values.get("dhcpStatements")
            raw_seq = (
                cast("Sequence[object]", raw_stmts)
                if isinstance(raw_stmts, Sequence) and not isinstance(raw_stmts, str | bytes)
                else ()
            )
            statements: list[str] = [str(s) for s in raw_seq]
            # Map fixed_address -> dhcpStatements
            if ctx.was_touched("fixed_address") or (ctx.creating and fixed_ip is not None):
                if isinstance(fixed_ip, str) and fixed_ip.strip():
                    ip_err = validate_ipv4(fixed_ip.strip())
                    if ip_err is not None:
                        ctx.error("fixed_address", ip_err)
                    else:
                        norm_ip = str(ipaddress.IPv4Address(fixed_ip.strip()))
                        statements = [
                            s for s in statements if not s.strip().startswith("fixed-address ")
                        ]
                        statements.append(f"fixed-address {norm_ip}")
                        ctx.values["dhcpStatements"] = statements
                elif fixed_ip is None or fixed_ip == "":
                    statements = [
                        s for s in statements if not s.strip().startswith("fixed-address ")
                    ]
                    ctx.values["dhcpStatements"] = statements
            else:
                # If fixed_address was not touched, populate it from dhcpStatements
                for s in statements:
                    if s.strip().startswith("fixed-address "):
                        raw_ip = s.strip()[len("fixed-address ") :].strip()
                        ip_err = validate_ipv4(raw_ip)
                        if ip_err is not None:
                            ctx.error("dhcpStatements", ip_err)
                        else:
                            ctx.values["fixed_address"] = str(ipaddress.IPv4Address(raw_ip))
                        break


# ---------------------------------------------------------------------------
# 7. Class (dhcpClass)
# ---------------------------------------------------------------------------


class DhcpClass(ObjectType):
    """DHCP class section."""

    name = "dhcp_class"
    label = _("Class")
    label_plural = _("Classes")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpClass)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ""
    columns = ("cn", "dhcpComments")
    search_attrs = ("cn", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpClass"
        label = _("Class")
        object_classes = ("dhcpClass",)

        general = Section(
            _("General"),
            StringAttr("cn", _("Name"), required=True),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )


# ---------------------------------------------------------------------------
# 8. SubClass (dhcpSubClass)
# ---------------------------------------------------------------------------


class DhcpSubClass(ObjectType):
    """DHCP subclass section."""

    name = "dhcp_subclass"
    label = _("Subclass")
    label_plural = _("Subclasses")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpSubClass)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ""
    columns = ("cn", "dhcpComments")
    search_attrs = ("cn", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpSubClass"
        label = _("Subclass")
        object_classes = ("dhcpSubClass",)

        general = Section(
            _("General"),
            StringAttr("cn", _("Name"), required=True),
            StringAttr("dhcpClassData", _("Class data")),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )


# ---------------------------------------------------------------------------
# 9. TSIG Key (dhcpTSigKey)
# ---------------------------------------------------------------------------


class DhcpTSigKey(ObjectType):
    """DHCP TSIG key."""

    name = "dhcp_tsig_key"
    label = _("TSIG key")
    label_plural = _("TSIG keys")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpTSigKey)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ""
    columns = ("cn", "dhcpKeyAlgorithm", "dhcpComments")
    search_attrs = ("cn", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpTSigKey"
        label = _("TSIG key")
        object_classes = ("dhcpTSigKey",)

        key = Section(
            _("Key"),
            StringAttr("cn", _("Key name"), required=True),
            StringAttr(
                "dhcpKeyAlgorithm",
                _("Algorithm"),
                required=True,
                pattern=r"^(hmac-md5|hmac-sha1|hmac-sha256|hmac-sha512)$",
            ),
            Base64StringAttr("dhcpKeySecret", _("Key secret"), required=True),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )


# ---------------------------------------------------------------------------
# 10. DNS Zone (dhcpDnsZone)
# ---------------------------------------------------------------------------


class DhcpDnsZone(ObjectType):
    """DHCP DNS zone configuration."""

    name = "dhcp_dns_zone"
    label = _("DNS zone")
    label_plural = _("DNS zones")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpDnsZone)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ""
    columns = ("cn", "dhcpDnsZoneServer", "dhcpComments")
    search_attrs = ("cn", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpDnsZone"
        label = _("DNS zone")
        object_classes = ("dhcpDnsZone",)

        zone = Section(
            _("DNS zone"),
            StringAttr("cn", _("Zone name"), required=True),
            StringAttr("dhcpDnsZoneServer", _("DNS server")),
            ObjectRefAttr(
                "dhcpKeyDN",
                _("TSIG key DN"),
                ref_type="dhcp_tsig_key",
            ),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )


# ---------------------------------------------------------------------------
# 11. Failover Peer (dhcpFailOverPeer)
# ---------------------------------------------------------------------------


class DhcpFailOverPeer(ObjectType):
    """DHCP failover peer configuration."""

    name = "dhcp_failover_peer"
    label = _("Failover peer")
    label_plural = _("Failover peers")
    icon = ICON
    category = CATEGORY
    acl_category = ACL_CATEGORY
    filter = "(objectClass=dhcpFailOverPeer)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ""
    columns = ("cn", "dhcpFailOverPrimaryServer", "dhcpComments")
    search_attrs = ("cn", "dhcpComments")

    class Main(DhcpSectionTab):
        name = "main"
        acl_key = "dhcpFailOverPeer"
        label = _("Failover peer")
        object_classes = ("dhcpFailOverPeer",)

        peer = Section(
            _("Peer"),
            StringAttr("cn", _("Peer name"), required=True),
            StringAttr("dhcpFailOverPrimaryServer", _("Primary server")),
            IntAttr(
                "dhcpFailOverPrimaryPort",
                _("Primary port"),
                min=1,
                max=65535,
            ),
            StringAttr("dhcpFailOverSecondaryServer", _("Secondary server")),
            IntAttr(
                "dhcpFailOverSecondaryPort",
                _("Secondary port"),
                min=1,
                max=65535,
            ),
            IntAttr(
                "dhcpFailOverResponseDelay",
                _("Response delay (seconds)"),
                min=0,
            ),
            IntAttr(
                "dhcpFailOverUnackedUpdates",
                _("Unacked updates"),
                min=0,
            ),
            IntAttr(
                "dhcpMaxClientLeadTime",
                _("Max client lead time (seconds)"),
                min=0,
            ),
            IntAttr(
                "dhcpFailOverSplit",
                _("Split"),
                min=0,
                max=256,
            ),
            StringAttr("dhcpHashBucketAssignment", _("Hash bucket assignment")),
            IntAttr(
                "dhcpFailOverLoadBalanceTime",
                _("Load balance time (seconds)"),
                min=0,
            ),
        )
        configuration = Section(
            _("Parameters"),
            dhcp_options_attr(),
            dhcp_statements_attr(),
            dhcp_comments_attr(),
        )


ALL_TYPES: tuple[type[ObjectType], ...] = (
    DhcpConfiguration,
    DhcpSharedNetwork,
    DhcpSubnet,
    DhcpPool,
    DhcpGroup,
    DhcpHost,
    DhcpClass,
    DhcpSubClass,
    DhcpTSigKey,
    DhcpDnsZone,
    DhcpFailOverPeer,
)
