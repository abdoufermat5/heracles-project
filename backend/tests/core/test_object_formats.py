"""Object attribute formats: values accepted and refused, descriptors, API enforcement."""

from __future__ import annotations

from typing import Any, cast

import pytest

import heracles_plugins.dns as dns
import heracles_plugins.posix as posix
import heracles_plugins.ssh as ssh
import heracles_plugins.sudo as sudo
import heracles_plugins.systems as systems
from heracles.attributes import CompositeAttr, ListAttr, ObjectRefAttr, StringAttr, UrlAttr
from heracles.core.formats import check
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import (
    ObjectService,
    ObjectType,
    ObjectValidationError,
    Section,
    Tab,
    TypeRegistry,
)
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.ssh import parse_key

BASE = "dc=test"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEN4afpmpx6UcN3RZPI3PaZEelen0CCXeFfX96TNN8Fw fixture"

GOOD = {
    "ssh_key": [KEY, f'command="ls" {KEY}', f"disabled-{KEY}"],
    "ip": ["192.168.1.10", "::1", "2001:db8::1", "::ffff:192.0.2.1"],
    "ipv4": ["10.0.0.1", "255.255.255.255"],
    "ipv6": ["2001:db8::1", "1:2:3:4:5:6:7:8"],
    "mac": ["aa:bb:cc:dd:ee:ff", "AA-BB-CC-DD-EE-FF", "aabbccddeeff"],
    "host_or_ip": ["bmc.example.com", "10.1.1.1", "2001:db8::5"],
    "sid": ["S-1-5-21-1-2-3"],
    "rdn_value": ["Alice B", "a+b"],
    "sudo_user": ["alice", "%wheel", "%#100", "#1000", "+admins", "ALL", "!bob"],
    "sudo_runas_group": ["ALL", "staff", "#10"],
    "sudo_host": ["ALL", "web*", "10.0.0.0/8", "192.168.0.0/255.255.255.0", "+lan", "!db1"],
    "sudo_command": ["ALL", "/bin/ls -l", "sudoedit /etc/hosts", "SERVICES", "!/bin/su"],
    "dns_host": ["ns1.example.com.", "_srv.example.com", "."],
    "dns_mailbox": ["hostmaster.example.com.", "admin@example.com"],
    "dns_pref_host": ["10 mail.example.com."],
    "dns_srv": ["10 5 5060 sip.example.com."],
    "dns_caa": ['0 issue "letsencrypt.org"'],
}
BAD = {
    "ssh_key": ["hello", "ssh-rsa hello", "ssh-ed25519", "ssh-ed25519 AAAA===="],
    "ip": ["1.2.3", "256.1.1.1", "01.2.3.4", "fe80::1%eth0", "1:2:3:4:5:6:7:8:9", ":::"],
    "ipv4": ["::1", "10.0.0"],
    "ipv6": ["10.0.0.1", "1::2::3"],
    "mac": ["aa:bb:cc", "gg:bb:cc:dd:ee:ff"],
    "host_or_ip": ["not a host"],
    "sid": ["S-2-5", "S-1-5"],
    "rdn_value": [" Alice", "Alice ", "a\nb"],
    "sudo_user": ["has space", "%"],
    "sudo_runas_group": ["%staff"],
    "sudo_host": ["10.0.0.0/33", "<>"],
    "sudo_command": ["ls", "/bin/ls\nALL"],
    "dns_host": ["bad host"],
    "dns_mailbox": ["with space.example.com"],
    "dns_pref_host": ["mail.example.com"],
    "dns_srv": ["10 5 sip.example.com"],
    "dns_caa": ["issue letsencrypt.org"],
}


@pytest.mark.parametrize("fmt", sorted(GOOD))
def test_accepts_and_refuses(fmt: str) -> None:
    for value in GOOD[fmt]:
        assert check(fmt, value) is None, f"{fmt} should accept {value!r}"
    for value in BAD[fmt]:
        assert check(fmt, value) is not None, f"{fmt} should refuse {value!r}"
    assert check(fmt, "") is None


def test_ssh_key_format_agrees_with_the_plugin_parser() -> None:
    for value in [*GOOD["ssh_key"], *BAD["ssh_key"]]:
        assert (check("ssh_key", value) is None) is (parse_key(value) is not None), value


# ------------------------------------------------------------- descriptors


def constraints_of(registry: TypeRegistry, type_name: str, tab: str, attr: str) -> dict[str, Any]:
    info = registry.get(type_name)
    found = (info.tab(tab) or pytest.fail(tab)).attribute(attr) or pytest.fail(attr)
    return cast("dict[str, Any]", found.describe()["constraints"])


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    for ou in ("people", "groups", "sudoers", "dns", "systems"):
        d.add(f"ou={ou},{BASE}", {"objectClass": [b"organizationalUnit"], "ou": [ou.encode()]})
    d.set_schema_object_classes(
        [
            *d.schema_object_classes(),
            "dNSZone",
            "hrcDNSView",
            "hrcDNSAcl",
            "ieee802Device",
            "device",
        ]
    )
    return d


@pytest.fixture
def registry(directory: MemoryDirectory) -> TypeRegistry:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    for plugin in (posix.plugin(), ssh.plugin(), sudo.plugin(), dns.plugin(), systems.plugin()):
        assert registry.register_plugin(plugin, classes).enabled
    return registry


@pytest.fixture
def service(directory: MemoryDirectory, registry: TypeRegistry) -> ObjectService:
    return ObjectService(directory, registry)


def test_descriptors_carry_the_formats(registry: TypeRegistry) -> None:
    assert constraints_of(registry, "user", "posix", "homeDirectory") == {"format": "abs_path"}
    ssh_attr = (registry.get("user").tab("ssh") or pytest.fail()).attribute("sshPublicKey")
    assert ssh_attr is not None
    assert cast("dict[str, Any]", ssh_attr.describe()["item"])["constraints"] == {
        "format": "ssh_key"
    }
    assert constraints_of(registry, "user", "main", "manager") == {"format": "dn"}
    zone = registry.get("dns_zone").tab("main") or pytest.fail()
    records = zone.attribute("dnsRecord") or pytest.fail()
    assert isinstance(records, ListAttr)
    record = cast("CompositeAttr", cast("Any", records).item)
    value = next(f for f in record.fields if f.name == "value").describe()
    by = cast("dict[str, Any]", value["constraints"])["format_by"]
    assert by["field"] == "type"
    assert by["formats"]["A"] == "ipv4"
    assert constraints_of(registry, "dns_zone", "main", "soaPrimary")["format"] == "dns_host"
    assert constraints_of(registry, "sudo", "main", "sudoHost") == {}


def test_main_attribute_must_be_a_legal_rdn_value() -> None:
    class Thing(ObjectType):
        name = "thing_rdn_test"
        main_attr = "cn"
        name_attr = "cn"

        class Main(Tab):
            name = "main"
            props = Section("Properties", StringAttr("cn", "Name", required=True))

    cn = Thing.Main.attribute("cn") or pytest.fail()
    assert cn.describe()["constraints"] == {"format": "rdn_value"}
    assert cn.validate(" padded ") != []
    assert cn.validate("padded") == []


def test_dn_reference_syntax_is_checked() -> None:
    ref = ObjectRefAttr("manager", "Manager", ref_type="user")
    assert ref.validate("not a dn") != []
    assert ref.validate("cn=a,dc=test") == []


# ---------------------------------------------------------- API enforcement


def user(service: ObjectService, tabs: dict[str, Any] | None = None, uid: str = "jdoe") -> str:
    main = {"main": {"values": {"uid": uid, "givenName": "J", "sn": "Doe"}}}
    return service.create("user", BASE, {**main, **(tabs or {})})


def refused(service: ObjectService, tabs: dict[str, Any]) -> dict[str, str]:
    with pytest.raises(ObjectValidationError) as info:
        user(service, tabs)
    return dict(info.value.fields)


def test_login_shell_bash_is_refused(service: ObjectService) -> None:
    fields = refused(service, {"posix": {"active": True, "values": {"loginShell": "bash"}}})
    assert "posix.loginShell" in fields


def test_home_directory_must_be_absolute(service: ObjectService) -> None:
    fields = refused(service, {"posix": {"active": True, "values": {"homeDirectory": "home/x"}}})
    assert fields["posix.homeDirectory"] == "Expected an absolute path, such as /bin/bash."


def test_ids_below_the_minimum_are_refused_when_typed(service: ObjectService) -> None:
    values = {"force_ids": True, "uidNumber": 5, "gidNumber": 2000}
    fields = refused(service, {"posix": {"active": True, "values": values}})
    assert "posix.uidNumber" in fields


def test_ssh_key_hello_is_refused(service: ObjectService) -> None:
    posix_tab: dict[str, Any] = {"active": True, "values": {}}
    fields = refused(
        service,
        {"posix": posix_tab, "ssh": {"active": True, "values": {"sshPublicKey": ["hello"]}}},
    )
    assert "ssh.sshPublicKey" in fields


def test_sudo_values_follow_their_syntax(service: ObjectService) -> None:
    def create(**values: Any) -> dict[str, str]:
        with pytest.raises(ObjectValidationError) as info:
            service.create("sudo", BASE, {"main": {"values": {"cn": "r", **values}}})
        return dict(info.value.fields)

    assert "main.sudoHost" in create(sudoHost=["not a host!"])
    assert "main.sudoUser" in create(sudoUser=["has space"])
    assert "main.sudoCommand" in create(sudoCommand=["ls"])


def test_dns_record_value_follows_its_type(service: ObjectService) -> None:
    zone = {
        "zoneName": "example.com",
        "soaPrimary": "ns1.example.com.",
        "soaMail": "hostmaster.example.com.",
    }

    def create(record: dict[str, str]) -> dict[str, str]:
        values = {**zone, "dnsRecord": [record]}
        with pytest.raises(ObjectValidationError) as info:
            service.create("dns_zone", BASE, {"main": {"values": values}})
        return dict(info.value.fields)

    fields = create({"name": "www", "type": "A", "value": "mail.example.com"})
    assert "IPv4" in fields["main.dnsRecord"]
    assert "main.dnsRecord" in create({"name": "@", "type": "MX", "value": "mail.example.com"})
    bad_soa = {**zone, "soaPrimary": "not a host"}
    with pytest.raises(ObjectValidationError) as info:
        service.create("dns_zone", BASE, {"main": {"values": bad_soa}})
    assert "main.soaPrimary" in info.value.fields


def test_web_urls_need_a_host() -> None:
    url = UrlAttr("labeledURI", "Website")
    assert url.validate("https://example.com/a?b=1") == []
    assert url.validate("mailto:admin@example.com") == []
    assert url.validate("http://") != []
    assert url.validate("https:///path") != []
    assert url.validate("example.com") != []
