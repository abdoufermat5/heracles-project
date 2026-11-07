"""DHCP plugin tests: CRUD at several depths, validation, mapping, delete, tree."""

from __future__ import annotations

from typing import Any

import pytest

import heracles_plugins.dhcp as dhcp
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.schema.legacy import OC

BASE = "dc=test"
PARIS = f"ou=paris,{BASE}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"top", b"domain"], "dc": [b"test"]})
    d.add(
        PARIS,
        {
            "objectClass": [b"top", b"organizationalUnit", OC.DEPARTMENT.encode()],
            "ou": [b"paris"],
        },
    )
    d.set_schema_object_classes([*d.schema_object_classes(), "dhcpservice"])
    return d


@pytest.fixture
def registry(directory: MemoryDirectory) -> TypeRegistry:
    reg = TypeRegistry()
    register_builtin_types(reg)
    status = reg.register_plugin(
        dhcp.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return reg


@pytest.fixture
def service(directory: MemoryDirectory, registry: TypeRegistry) -> ObjectService:
    return ObjectService(directory, registry)


def create_section(
    service: ObjectService,
    type_name: str,
    base: str,
    values: dict[str, Any],
) -> str:
    tabs: dict[str, Any] = {"main": {"values": values}}
    return service.create(type_name, base, tabs)


def section_errors(
    service: ObjectService,
    type_name: str,
    base: str,
    values: dict[str, Any],
) -> dict[str, str]:
    with pytest.raises(ObjectValidationError) as exc_info:
        create_section(service, type_name, base, values)
    return exc_info.value.fields


# ---------------------------------------------------------------------------
# 1. Plugin registration and ACL keys
# ---------------------------------------------------------------------------


def test_plugin_registration(directory: MemoryDirectory) -> None:
    reg = TypeRegistry()
    # Missing required class dhcpService
    status = reg.register_plugin(dhcp.plugin(), {"top", "person"})
    assert not status.enabled
    assert "dhcpService" in status.missing_object_classes
    status_ok = reg.register_plugin(dhcp.plugin(), {"dhcpservice"})
    assert status_ok.enabled


def test_acl_keys_and_categories(registry: TypeRegistry) -> None:
    for type_cls in dhcp.ALL_TYPES:
        info = registry.get(type_cls.name)
        assert info.acl_category == "dhcpConfiguration"
        expected_oc = dhcp.CLASS_BY_TYPE[type_cls.name]
        assert info.main_tab.acl_key == expected_oc
        assert info.acl_object(info.main_tab) == f"dhcpConfiguration/{expected_oc}"


# ---------------------------------------------------------------------------
# 2. CRUD at several depths
# ---------------------------------------------------------------------------


def test_crud_hierarchy_three_depths(service: ObjectService, directory: MemoryDirectory) -> None:
    # Depth 1: Configuration under department
    cfg_dn = create_section(
        service,
        "dhcp_configuration",
        PARIS,
        {
            "cn": "office-dhcp",
            "dhcpComments": "Main office DHCP",
            "dhcpOption": ["option routers 192.168.1.1", "domain-name example.com"],
            "dhcpStatements": ["default-lease-time 600", "max-lease-time 7200"],
        },
    )
    assert cfg_dn == f"cn=office-dhcp,ou=dhcp,{PARIS}"
    cfg_entry = directory.get(cfg_dn)
    assert cfg_entry is not None
    assert cfg_entry.has_object_class("dhcpService")
    # Option normalization check
    assert cfg_entry.texts("dhcpOption") == ["routers 192.168.1.1", 'domain-name "example.com"']

    # Depth 2: Shared network under configuration
    net_dn = create_section(
        service,
        "dhcp_shared_network",
        cfg_dn,
        {"cn": "lan-network", "dhcpComments": "Office LAN"},
    )
    assert net_dn == f"cn=lan-network,{cfg_dn}"
    net_entry = directory.get(net_dn)
    assert net_entry is not None
    assert net_entry.has_object_class("dhcpSharedNetwork")

    # Depth 3: Subnet under shared network
    subnet_dn = create_section(
        service,
        "dhcp_subnet",
        net_dn,
        {
            "cn": "192.168.1.0",
            "dhcpNetMask": 24,
            "dhcpRange": ["192.168.1.100 192.168.1.200"],
        },
    )
    assert subnet_dn == f"cn=192.168.1.0,{net_dn}"
    subnet_entry = directory.get(subnet_dn)
    assert subnet_entry is not None
    assert subnet_entry.has_object_class("dhcpSubnet")
    assert subnet_entry.text("dhcpNetMask") == "24"

    # Depth 4: Pool under subnet
    pool_dn = create_section(
        service,
        "dhcp_pool",
        subnet_dn,
        {
            "cn": "dynamic-pool",
            "dhcpRange": ["192.168.1.100 192.168.1.150"],
            "dhcpPermitList": ["client-class-1"],
        },
    )
    assert pool_dn == f"cn=dynamic-pool,{subnet_dn}"
    assert directory.get(pool_dn) is not None

    # Depth 4: Group under subnet
    group_dn = create_section(
        service,
        "dhcp_group",
        subnet_dn,
        {"cn": "printers", "dhcpComments": "Printers group"},
    )
    assert group_dn == f"cn=printers,{subnet_dn}"

    # Depth 5: Host under group
    host_dn = create_section(
        service,
        "dhcp_host",
        group_dn,
        {
            "cn": "printer-hp",
            "dhcpHWAddress": {"type": "ethernet", "mac": "00:11:22:33:44:55"},
            "fixed_address": "192.168.1.25",
        },
    )
    assert host_dn == f"cn=printer-hp,{group_dn}"
    host_entry = directory.get(host_dn)
    assert host_entry is not None
    assert host_entry.text("dhcpHWAddress") == "ethernet 00:11:22:33:44:55"
    assert host_entry.texts("dhcpStatements") == ["fixed-address 192.168.1.25"]

    # Verify load
    host_state = service.load("dhcp_host", host_dn)
    assert host_state.tabs["main"].values["fixed_address"] == "192.168.1.25"
    assert host_state.tabs["main"].values["dhcpHWAddress"] == {
        "type": "ethernet",
        "mac": "00:11:22:33:44:55",
    }

    # Verify update
    service.update(
        "dhcp_host",
        host_dn,
        {
            "main": {
                "values": {
                    "fixed_address": "192.168.1.26",
                    "dhcpComments": "Updated printer",
                }
            }
        },
    )
    updated_host = service.load("dhcp_host", host_dn)
    assert updated_host.tabs["main"].values["fixed_address"] == "192.168.1.26"
    assert updated_host.tabs["main"].values["dhcpComments"] == "Updated printer"
    host_entry_after = directory.get(host_dn)
    assert host_entry_after is not None
    assert host_entry_after.texts("dhcpStatements") == ["fixed-address 192.168.1.26"]


def test_crud_classes_and_subclasses(service: ObjectService) -> None:
    cfg_dn = create_section(service, "dhcp_configuration", PARIS, {"cn": "classes-dhcp"})

    # Class under configuration
    class_dn = create_section(
        service, "dhcp_class", cfg_dn, {"cn": "cisco-phones", "dhcpComments": "VoIP phones"}
    )
    assert class_dn == f"cn=cisco-phones,{cfg_dn}"

    # Subclass under class
    subclass_dn = create_section(
        service,
        "dhcp_subclass",
        class_dn,
        {"cn": "cisco-7940", "dhcpClassData": "vendor-class-identifier"},
    )
    assert subclass_dn == f"cn=cisco-7940,{class_dn}"
    assert service.load("dhcp_subclass", subclass_dn).tabs["main"].values["dhcpClassData"] == (
        "vendor-class-identifier"
    )


def test_crud_tsig_key_and_dns_zone(service: ObjectService) -> None:
    cfg_dn = create_section(service, "dhcp_configuration", PARIS, {"cn": "dns-dhcp"})

    # TSIG Key
    key_dn = create_section(
        service,
        "dhcp_tsig_key",
        cfg_dn,
        {
            "cn": "rndc-key",
            "dhcpKeyAlgorithm": "hmac-sha256",
            "dhcpKeySecret": "c2VjcmV0ZGF0YTEyMw==",
        },
    )
    assert service.load("dhcp_tsig_key", key_dn).tabs["main"].values["dhcpKeyAlgorithm"] == (
        "hmac-sha256"
    )

    # DNS Zone referencing TSIG Key
    zone_dn = create_section(
        service,
        "dhcp_dns_zone",
        cfg_dn,
        {
            "cn": "example.com.",
            "dhcpDnsZoneServer": "192.168.1.2",
            "dhcpKeyDN": key_dn,
        },
    )
    assert service.load("dhcp_dns_zone", zone_dn).tabs["main"].values["dhcpKeyDN"] == key_dn


def test_crud_failover_peer(service: ObjectService, directory: MemoryDirectory) -> None:
    cfg_dn = create_section(service, "dhcp_configuration", PARIS, {"cn": "failover-dhcp"})
    peer_dn = create_section(
        service,
        "dhcp_failover_peer",
        cfg_dn,
        {
            "cn": "peer1",
            "dhcpFailOverPrimaryServer": "dhcp1.example.com",
            "dhcpFailOverPrimaryPort": 647,
            "dhcpFailOverSecondaryServer": "dhcp2.example.com",
            "dhcpFailOverSecondaryPort": 647,
            "dhcpFailOverResponseDelay": 30,
            "dhcpFailOverUnackedUpdates": 10,
            "dhcpMaxClientLeadTime": 3600,
            "dhcpFailOverSplit": 128,
            "dhcpFailOverLoadBalanceTime": 3,
        },
    )
    peer_entry = directory.get(peer_dn)
    assert peer_entry is not None
    assert peer_entry.text("dhcpFailOverPrimaryPort") == "647"
    assert peer_entry.text("dhcpFailOverSplit") == "128"


# ---------------------------------------------------------------------------
# 3. Allowed-children enforcement
# ---------------------------------------------------------------------------


def test_allowed_children_enforcement(service: ObjectService) -> None:
    cfg_dn = create_section(service, "dhcp_configuration", PARIS, {"cn": "enforce-dhcp"})
    subnet_dn = create_section(
        service, "dhcp_subnet", cfg_dn, {"cn": "10.0.0.0", "dhcpNetMask": 24}
    )
    group_dn = create_section(service, "dhcp_group", subnet_dn, {"cn": "grp"})
    host_dn = create_section(service, "dhcp_host", group_dn, {"cn": "hst"})
    class_dn = create_section(service, "dhcp_class", cfg_dn, {"cn": "cls"})

    # dhcpPool NOT allowed directly under dhcpService
    err = section_errors(
        service,
        "dhcp_pool",
        cfg_dn,
        {"cn": "pool1", "dhcpRange": ["10.0.0.1 10.0.0.10"]},
    )
    assert "main.cn" in err
    assert "not allowed" in err["main.cn"]

    # dhcpSubClass NOT allowed under dhcpSubnet
    err = section_errors(service, "dhcp_subclass", subnet_dn, {"cn": "subcls1"})
    assert "main.cn" in err
    assert "not allowed" in err["main.cn"]

    # Leaf nodes reject children: host cannot have hosts or pools
    err = section_errors(service, "dhcp_host", host_dn, {"cn": "nested-host"})
    assert "main.cn" in err
    assert "not allowed" in err["main.cn"]

    # dhcpGroup only allows dhcpHost (not dhcpSubnet)
    err = section_errors(service, "dhcp_subnet", group_dn, {"cn": "10.0.1.0", "dhcpNetMask": 24})
    assert "main.cn" in err
    assert "not allowed" in err["main.cn"]

    # dhcpClass only allows dhcpSubClass (not dhcpHost)
    err = section_errors(service, "dhcp_host", class_dn, {"cn": "bad-host"})
    assert "main.cn" in err
    assert "not allowed" in err["main.cn"]

    # Creating under non-existent parent
    err = section_errors(
        service, "dhcp_subnet", f"cn=nope,{cfg_dn}", {"cn": "10.0.2.0", "dhcpNetMask": 24}
    )
    assert "main.cn" in err
    assert "does not exist" in err["main.cn"]

    # Creating under non-DHCP parent (e.g. department)
    err = section_errors(service, "dhcp_subnet", PARIS, {"cn": "10.0.3.0", "dhcpNetMask": 24})
    assert "main.cn" in err
    assert "not a valid DHCP section" in err["main.cn"]


# ---------------------------------------------------------------------------
# 4. Subnet and range validation
# ---------------------------------------------------------------------------


def test_subnet_validation(service: ObjectService) -> None:
    cfg_dn = create_section(service, "dhcp_configuration", PARIS, {"cn": "subnet-val-dhcp"})

    # Invalid IPv4 in subnet cn
    err = section_errors(service, "dhcp_subnet", cfg_dn, {"cn": "999.1.1.1", "dhcpNetMask": 24})
    assert "main.cn" in err

    err = section_errors(service, "dhcp_subnet", cfg_dn, {"cn": "not-an-ip", "dhcpNetMask": 24})
    assert "main.cn" in err

    # Host bits set for prefix length
    err = section_errors(service, "dhcp_subnet", cfg_dn, {"cn": "192.168.1.5", "dhcpNetMask": 24})
    assert "main.cn" in err
    assert "not a network address" in err["main.cn"]

    # Prefix length out of bounds
    err = section_errors(service, "dhcp_subnet", cfg_dn, {"cn": "192.168.1.0", "dhcpNetMask": 35})
    assert "main.dhcpNetMask" in err

    err = section_errors(service, "dhcp_subnet", cfg_dn, {"cn": "192.168.1.0", "dhcpNetMask": -1})
    assert "main.dhcpNetMask" in err


def test_range_validation(service: ObjectService) -> None:
    cfg_dn = create_section(service, "dhcp_configuration", PARIS, {"cn": "range-val-dhcp"})

    # Malformed range
    err = section_errors(
        service,
        "dhcp_subnet",
        cfg_dn,
        {"cn": "192.168.1.0", "dhcpNetMask": 24, "dhcpRange": ["single-ip"]},
    )
    assert "main.dhcpRange" in err

    # Invalid IP in range
    err = section_errors(
        service,
        "dhcp_subnet",
        cfg_dn,
        {"cn": "192.168.1.0", "dhcpNetMask": 24, "dhcpRange": ["192.168.1.10 bad-ip"]},
    )
    assert "main.dhcpRange" in err

    # Range start > end
    err = section_errors(
        service,
        "dhcp_subnet",
        cfg_dn,
        {"cn": "192.168.1.0", "dhcpNetMask": 24, "dhcpRange": ["192.168.1.100 192.168.1.50"]},
    )
    assert "main.dhcpRange" in err

    # Range outside subnet
    err = section_errors(
        service,
        "dhcp_subnet",
        cfg_dn,
        {"cn": "192.168.1.0", "dhcpNetMask": 24, "dhcpRange": ["10.0.0.1 10.0.0.50"]},
    )
    assert "main.dhcpRange" in err

    # Valid subnet and pool range
    subnet_dn = create_section(
        service,
        "dhcp_subnet",
        cfg_dn,
        {"cn": "192.168.1.0", "dhcpNetMask": 24, "dhcpRange": ["192.168.1.10 192.168.1.50"]},
    )
    assert subnet_dn

    # Pool range outside parent subnet
    err = section_errors(
        service,
        "dhcp_pool",
        subnet_dn,
        {"cn": "bad-pool", "dhcpRange": ["172.16.0.10 172.16.0.20"]},
    )
    assert "main.dhcpRange" in err


# ---------------------------------------------------------------------------
# 5. Host HW address & fixed address mapping
# ---------------------------------------------------------------------------


def test_host_hw_address_formats(service: ObjectService, directory: MemoryDirectory) -> None:
    cfg_dn = create_section(service, "dhcp_configuration", PARIS, {"cn": "host-test-dhcp"})
    subnet_dn = create_section(
        service, "dhcp_subnet", cfg_dn, {"cn": "10.10.10.0", "dhcpNetMask": 24}
    )

    # String format '<type> <mac>'
    host1_dn = create_section(
        service,
        "dhcp_host",
        subnet_dn,
        {"cn": "host1", "dhcpHWAddress": "ethernet 00:11:22:33:44:55"},
    )
    host1_entry = directory.get(host1_dn)
    assert host1_entry is not None
    assert host1_entry.text("dhcpHWAddress") == "ethernet 00:11:22:33:44:55"
    loaded1 = service.load("dhcp_host", host1_dn)
    assert loaded1.tabs["main"].values["dhcpHWAddress"] == {
        "type": "ethernet",
        "mac": "00:11:22:33:44:55",
    }

    # Dict format {'type': 'token-ring', 'mac': 'aa:bb:cc:dd:ee:ff'}
    host2_dn = create_section(
        service,
        "dhcp_host",
        subnet_dn,
        {"cn": "host2", "dhcpHWAddress": {"type": "token-ring", "mac": "aa:bb:cc:dd:ee:ff"}},
    )
    host2_entry = directory.get(host2_dn)
    assert host2_entry is not None
    assert host2_entry.text("dhcpHWAddress") == "token-ring aa:bb:cc:dd:ee:ff"
    # Invalid MAC
    err = section_errors(
        service,
        "dhcp_host",
        subnet_dn,
        {"cn": "bad-host-mac", "dhcpHWAddress": "ethernet not-a-mac"},
    )
    assert "main.dhcpHWAddress" in err

    # Invalid type
    err = section_errors(
        service,
        "dhcp_host",
        subnet_dn,
        {"cn": "bad-host-type", "dhcpHWAddress": "wlan 00:11:22:33:44:55"},
    )
    assert "main.dhcpHWAddress" in err


def test_host_fixed_address_mapping(service: ObjectService, directory: MemoryDirectory) -> None:
    cfg_dn = create_section(service, "dhcp_configuration", PARIS, {"cn": "fixed-ip-dhcp"})
    subnet_dn = create_section(
        service, "dhcp_subnet", cfg_dn, {"cn": "10.20.0.0", "dhcpNetMask": 16}
    )

    # Creation with fixed_address virtual field
    host_dn = create_section(
        service,
        "dhcp_host",
        subnet_dn,
        {"cn": "workstation", "fixed_address": "10.20.1.50"},
    )
    entry = directory.get(host_dn)
    assert entry is not None
    # Must NOT write fixed_address directly as an LDAP attribute
    assert entry.get("fixed_address") == []
    # Must store in dhcpStatements
    assert entry.texts("dhcpStatements") == ["fixed-address 10.20.1.50"]

    # Loaded back into virtual field
    loaded = service.load("dhcp_host", host_dn)
    assert loaded.tabs["main"].values["fixed_address"] == "10.20.1.50"

    # Update fixed_address
    service.update(
        "dhcp_host",
        host_dn,
        {"main": {"values": {"fixed_address": "10.20.1.99"}}},
    )
    entry_after_up = directory.get(host_dn)
    assert entry_after_up is not None
    assert entry_after_up.texts("dhcpStatements") == ["fixed-address 10.20.1.99"]

    # Clear fixed_address
    service.update(
        "dhcp_host",
        host_dn,
        {"main": {"values": {"fixed_address": ""}}},
    )
    entry_after_clear = directory.get(host_dn)
    assert entry_after_clear is not None
    assert entry_after_clear.texts("dhcpStatements") == []
    # Invalid fixed_address rejected
    err = section_errors(
        service,
        "dhcp_host",
        subnet_dn,
        {"cn": "bad-fixed", "fixed_address": "999.999.999.999"},
    )
    assert "main.fixed_address" in err


# ---------------------------------------------------------------------------
# 6. TSIG key validation
# ---------------------------------------------------------------------------


def test_tsig_key_validation(service: ObjectService) -> None:
    cfg_dn = create_section(service, "dhcp_configuration", PARIS, {"cn": "tsig-val-dhcp"})

    # Invalid algorithm
    err = section_errors(
        service,
        "dhcp_tsig_key",
        cfg_dn,
        {"cn": "k1", "dhcpKeyAlgorithm": "des", "dhcpKeySecret": "AAAA"},
    )
    assert "main.dhcpKeyAlgorithm" in err

    # Invalid base64
    err = section_errors(
        service,
        "dhcp_tsig_key",
        cfg_dn,
        {"cn": "k2", "dhcpKeyAlgorithm": "hmac-md5", "dhcpKeySecret": "not-valid-base64?!"},
    )
    assert "main.dhcpKeySecret" in err


# ---------------------------------------------------------------------------
# 7. Recursive deletion
# ---------------------------------------------------------------------------


def test_recursive_deletion(service: ObjectService, directory: MemoryDirectory) -> None:
    cfg_dn = create_section(service, "dhcp_configuration", PARIS, {"cn": "del-dhcp"})
    subnet_dn = create_section(
        service, "dhcp_subnet", cfg_dn, {"cn": "172.16.0.0", "dhcpNetMask": 24}
    )
    pool_dn = create_section(
        service, "dhcp_pool", subnet_dn, {"cn": "p1", "dhcpRange": ["172.16.0.10 172.16.0.20"]}
    )
    host_dn = create_section(
        service, "dhcp_host", subnet_dn, {"cn": "h1", "fixed_address": "172.16.0.50"}
    )

    assert directory.get(cfg_dn) is not None
    assert directory.get(subnet_dn) is not None
    assert directory.get(pool_dn) is not None
    assert directory.get(host_dn) is not None

    # Deleting subnet deletes its pool and host
    service.delete("dhcp_subnet", subnet_dn)
    assert directory.get(subnet_dn) is None
    assert directory.get(pool_dn) is None
    assert directory.get(host_dn) is None
    # But configuration remains
    assert directory.get(cfg_dn) is not None

    # Create another child and delete configuration
    sub2 = create_section(service, "dhcp_subnet", cfg_dn, {"cn": "172.16.1.0", "dhcpNetMask": 24})
    service.delete("dhcp_configuration", cfg_dn)
    assert directory.get(cfg_dn) is None
    assert directory.get(sub2) is None


# ---------------------------------------------------------------------------
# 8. Tree builder
# ---------------------------------------------------------------------------


def test_tree_builder(service: ObjectService, directory: MemoryDirectory) -> None:
    cfg_dn = create_section(
        service,
        "dhcp_configuration",
        PARIS,
        {"cn": "corp-dhcp", "dhcpComments": "Corporate DHCP"},
    )
    net_dn = create_section(service, "dhcp_shared_network", cfg_dn, {"cn": "corp-lan"})
    sub_dn = create_section(service, "dhcp_subnet", net_dn, {"cn": "10.0.0.0", "dhcpNetMask": 16})
    pool_dn = create_section(
        service, "dhcp_pool", sub_dn, {"cn": "pool-dyn", "dhcpRange": ["10.0.1.1 10.0.1.50"]}
    )
    host_dn = create_section(service, "dhcp_host", sub_dn, {"cn": "server1"})
    key_dn = create_section(
        service,
        "dhcp_tsig_key",
        cfg_dn,
        {"cn": "dns-key", "dhcpKeyAlgorithm": "hmac-sha512", "dhcpKeySecret": "AAAA"},
    )

    tree = dhcp.build_dhcp_tree(directory, cfg_dn)
    assert len(tree) == 1
    root = tree[0]

    # Root node checks
    assert root["dn"] == cfg_dn
    assert root["type"] == "dhcp_configuration"
    assert root["label"] == "corp-dhcp"
    assert "dhcp_subnet" in root["allowed_children"]
    assert "dhcp_shared_network" in root["allowed_children"]
    assert "dhcp_pool" not in root["allowed_children"]

    # Root children: lan network and tsig key
    children_by_type = {c["type"]: c for c in root["children"]}
    assert "dhcp_shared_network" in children_by_type
    assert "dhcp_tsig_key" in children_by_type
    assert children_by_type["dhcp_tsig_key"]["dn"] == key_dn
    # Shared network children
    lan_node = children_by_type["dhcp_shared_network"]
    assert len(lan_node["children"]) == 1
    sub_node = lan_node["children"][0]
    assert sub_node["type"] == "dhcp_subnet"
    assert sub_node["label"] == "10.0.0.0"

    # Subnet children: pool and host
    sub_child_types = {c["type"] for c in sub_node["children"]}
    assert sub_child_types == {"dhcp_pool", "dhcp_host"}
    assert {c["dn"] for c in sub_node["children"]} == {pool_dn, host_dn}
    # Sub-tree rooted at subnet
    sub_tree = dhcp.build_dhcp_tree(directory, sub_dn)
    assert len(sub_tree) == 1
    assert sub_tree[0]["type"] == "dhcp_subnet"
    assert len(sub_tree[0]["children"]) == 2

    # Non-existent DN
    assert dhcp.build_dhcp_tree(directory, f"cn=nope,{PARIS}") == []
