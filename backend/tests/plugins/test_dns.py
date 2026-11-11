"""DNS plugin: zones, records, serials, reverse zones and PTR maintenance."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

import heracles_plugins.dns as dns
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.dns import DnsSettings
from heracles_plugins.dns.records import (
    Record,
    build_dkim,
    build_dmarc,
    build_spf,
    next_serial,
    normalize_host,
    normalize_mail,
    reverse_relative,
    validate_record,
    validate_records,
)

BASE = "dc=test"
DNS_OU = f"ou=dns,{BASE}"
ZONE = "example.com"
ZONE_DN = f"zoneName={ZONE},{DNS_OU}"
TODAY = date(2026, 11, 7)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dns, "today", lambda: TODAY)


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.set_schema_object_classes([*d.schema_object_classes(), "dNSZone", "hrcDNSView", "hrcDNSAcl"])
    return d


def make_service(directory: MemoryDirectory, final_dot: bool = True) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        dns.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    registry.settings["dns"] = DnsSettings(final_dot=final_dot)
    return ObjectService(directory, registry)


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    return make_service(directory)


def rec(name: str, rtype: str, value: str) -> dict[str, str]:
    return {"name": name, "type": rtype, "value": value}


def zone_values(**extra: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "zoneName": ZONE,
        "soaPrimary": "ns1.example.com",
        "soaMail": "hostmaster@example.com",
    }
    values.update(extra)
    return values


def new_zone(
    service: ObjectService,
    records: list[dict[str, str]] | None = None,
    reverse: list[str] | None = None,
    **extra: Any,
) -> str:
    values = zone_values(**extra)
    if records is not None:
        values["dnsRecord"] = records
    if reverse is not None:
        values["reverseZones"] = reverse
    return service.create("dns_zone", BASE, {"main": {"values": values}})


def patch(service: ObjectService, dn: str, **values: Any) -> None:
    service.update("dns_zone", dn, {"main": {"values": values}})


def attrs(directory: MemoryDirectory, dn: str) -> dict[str, list[str]]:
    entry = directory.get(dn)
    assert entry is not None, dn
    return {k: sorted(v.decode() for v in vals) for k, vals in entry.attrs.items()}


def soa(directory: MemoryDirectory, dn: str = ZONE_DN) -> list[str]:
    entry = directory.get(dn)
    assert entry is not None
    return entry.texts("sOARecord")[0].split()


BASIC = [
    rec("@", "NS", "ns1.example.com"),
    rec("@", "MX", "10 mail.example.com"),
    rec("ns1", "A", "192.0.2.1"),
    rec("www", "A", "192.0.2.10"),
    rec("www", "AAAA", "2001:db8::10"),
]


# ------------------------------------------------------------- plugin wiring


def test_plugin_registers_view_and_acl_only_with_their_classes() -> None:
    plain = MemoryDirectory(BASE)
    plain.set_schema_object_classes(["dNSZone"])
    registry = TypeRegistry()
    registry.register_plugin(dns.plugin(), {"dnszone"})
    assert [t.name for t in registry.list()] == ["dns_zone"]

    registry = TypeRegistry()
    registry.register_plugin(dns.plugin(), {"dnszone", "hrcdnsview", "hrcdnsacl"})
    assert [t.name for t in registry.list()] == ["dns_zone", "dns_view", "dns_acl"]

    registry = TypeRegistry()
    status = registry.register_plugin(dns.plugin(), {"hrcdnsview"})
    assert not status.enabled
    assert registry.list() == []


def test_acl_keys(service: ObjectService) -> None:
    zone = service.registry.get("dns_zone")
    assert zone.acl_object(zone.main_tab) == "dnsZone/dnsZone"
    view = service.registry.get("dns_view")
    assert view.acl_object(view.main_tab) == "dnsView/dnsView"
    acl = service.registry.get("dns_acl")
    assert acl.acl_object(acl.main_tab) == "dnsAcl/dnsAcl"
    attribute = zone.find_attribute("dnsRecord")
    assert attribute is not None
    assert not attribute.stored


# ------------------------------------------------------------------ creation


def test_create_zone_gives_apex_and_children(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_zone(service, BASIC)
    assert dn == ZONE_DN
    apex = attrs(directory, ZONE_DN)
    assert apex["objectClass"] == ["dNSZone"]
    assert apex["zoneName"] == [ZONE]
    assert apex["relativeDomainName"] == ["@"]
    assert apex["sOARecord"] == [
        "ns1.example.com. hostmaster.example.com. 2026110701 10800 3600 604800 3600"
    ]
    assert apex["nSRecord"] == ["ns1.example.com."]
    assert apex["mXRecord"] == ["10 mail.example.com."]
    assert "aRecord" not in apex
    www = attrs(directory, f"relativeDomainName=www,{ZONE_DN}")
    assert www == {
        "objectClass": ["dNSZone"],
        "zoneName": [ZONE],
        "relativeDomainName": ["www"],
        "aRecord": ["192.0.2.10"],
        "aAAARecord": ["2001:db8::10"],
    }
    ns1 = attrs(directory, f"relativeDomainName=ns1,{ZONE_DN}")
    assert ns1["aRecord"] == ["192.0.2.1"]
    assert directory.get(DNS_OU) is not None


def test_apex_a_records_and_roundtrip(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_zone(service, [rec("@", "A", "192.0.2.5"), rec("@", "TXT", "hello world")])
    assert attrs(directory, dn)["aRecord"] == ["192.0.2.5"]
    state = service.load("dns_zone", dn)
    values = state.tabs["main"].values
    assert values["soaPrimary"] == "ns1.example.com."
    assert values["soaMail"] == "hostmaster.example.com."
    assert values["soaSerial"] == "2026110701"
    assert values["dnsRecord"] == [rec("@", "A", "192.0.2.5"), rec("@", "TXT", "hello world")]


def test_listing_excludes_reverse_zones(service: ObjectService) -> None:
    new_zone(service, BASIC, reverse=["2.0.192.in-addr.arpa"])
    page = service.list("dns_zone", BASE, scope=dns_scope())
    assert [r.dn for r in page.items] == [ZONE_DN]


def dns_scope() -> Any:
    from heracles.ldap.client import Scope

    return Scope.SUBTREE


def test_zone_requires_soa(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as err:
        service.create("dns_zone", BASE, {"main": {"values": {"zoneName": ZONE}}})
    assert {"main.soaPrimary", "main.soaMail"} <= err.value.fields.keys()


def test_soa_mail_conversion() -> None:
    assert normalize_mail("hostmaster@example.com") == "hostmaster.example.com"
    assert normalize_mail("john.doe@example.com") == "john\\.doe.example.com"
    assert normalize_mail("hostmaster.example.com.") == "hostmaster.example.com."


# -------------------------------------------------------------------- serial


def test_next_serial_rules() -> None:
    assert next_serial(None, TODAY) == "2026110701"
    assert next_serial("2026110601", TODAY) == "2026110701"
    assert next_serial("2026110701", TODAY) == "2026110702"
    assert next_serial("2026110709", TODAY) == "2026110710"
    assert next_serial("1", TODAY) == "2026110701"
    assert next_serial("2026120101", TODAY) == "2026120102"  # never goes backwards


def test_serial_bumps_on_record_and_soa_changes(
    service: ObjectService, directory: MemoryDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dns, "today", lambda: date(2026, 11, 6))
    dn = new_zone(service, BASIC)
    assert soa(directory)[2] == "2026110601"
    monkeypatch.setattr(dns, "today", lambda: TODAY)
    patch(service, dn, dnsRecord=[*BASIC, rec("api", "A", "192.0.2.20")])
    assert soa(directory)[2] == "2026110701"
    patch(service, dn, soaRefresh=7200)
    assert soa(directory)[2:5] == ["2026110702", "7200", "3600"]
    patch(service, dn, dNSTTL=300)  # not a zone content change
    assert soa(directory)[2] == "2026110702"
    patch(service, dn, dnsRecord=[*BASIC, rec("api", "A", "192.0.2.20")])  # same records
    assert soa(directory)[2] == "2026110702"


# ------------------------------------------------------------ record changes


def test_record_add_edit_delete(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_zone(service, BASIC)
    api_dn = f"relativeDomainName=api,{ZONE_DN}"
    patch(service, dn, dnsRecord=[*BASIC, rec("api", "A", "192.0.2.20")])
    assert attrs(directory, api_dn)["aRecord"] == ["192.0.2.20"]

    edited = [*BASIC, rec("api", "A", "192.0.2.21"), rec("api", "TXT", "v2")]
    patch(service, dn, dnsRecord=edited)
    assert attrs(directory, api_dn)["aRecord"] == ["192.0.2.21"]
    assert attrs(directory, api_dn)["tXTRecord"] == ["v2"]

    patch(service, dn, dnsRecord=[r for r in edited if r["name"] != "api"])
    assert directory.get(api_dn) is None
    assert directory.get(f"relativeDomainName=www,{ZONE_DN}") is not None

    patch(service, dn, dnsRecord=[rec("www", "A", "192.0.2.10")])
    apex = attrs(directory, ZONE_DN)
    assert "nSRecord" not in apex
    assert "mXRecord" not in apex
    assert directory.get(f"relativeDomainName=ns1,{ZONE_DN}") is None
    assert "aAAARecord" not in attrs(directory, f"relativeDomainName=www,{ZONE_DN}")

    patch(service, dn, dnsRecord=None)
    assert directory.get(f"relativeDomainName=www,{ZONE_DN}") is None


def test_unreadable_other_data_is_kept(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_zone(service, BASIC)
    www = f"relativeDomainName=www,{ZONE_DN}"
    from heracles.ldap.client import Modification

    directory.modify(www, [Modification("add", "dNSTTL", [b"60"])])
    patch(service, dn, dnsRecord=[*BASIC[:3], rec("www", "A", "192.0.2.11")])
    assert attrs(directory, www)["dNSTTL"] == ["60"]
    assert attrs(directory, www)["aRecord"] == ["192.0.2.11"]


# ----------------------------------------------------------- final dot option


def test_final_dot_on(service: ObjectService, directory: MemoryDirectory) -> None:
    new_zone(
        service,
        [
            rec("@", "NS", "ns1.example.com"),
            rec("@", "MX", "10 mail.example.com"),
            rec("alias", "CNAME", "www.example.com"),
            rec("_sip._tcp", "SRV", "10 5 5060 sip.example.com"),
        ],
    )
    assert attrs(directory, ZONE_DN)["nSRecord"] == ["ns1.example.com."]
    assert attrs(directory, ZONE_DN)["mXRecord"] == ["10 mail.example.com."]
    assert attrs(directory, f"relativeDomainName=alias,{ZONE_DN}")["cNAMERecord"] == [
        "www.example.com."
    ]
    srv = attrs(directory, f"relativeDomainName=_sip._tcp,{ZONE_DN}")
    assert srv["sRVRecord"] == ["10 5 5060 sip.example.com."]


def test_final_dot_off(directory: MemoryDirectory) -> None:
    service = make_service(directory, final_dot=False)
    new_zone(
        service,
        [
            rec("@", "NS", "ns1.example.com."),
            rec("@", "MX", "10 mail.example.com."),
            rec("alias", "CNAME", "www.example.com."),
        ],
        reverse=["2.0.192.in-addr.arpa"],
    )
    assert soa(directory)[:2] == ["ns1.example.com", "hostmaster.example.com"]
    assert attrs(directory, ZONE_DN)["nSRecord"] == ["ns1.example.com"]
    assert attrs(directory, ZONE_DN)["mXRecord"] == ["10 mail.example.com"]
    assert attrs(directory, f"relativeDomainName=alias,{ZONE_DN}")["cNAMERecord"] == [
        "www.example.com"
    ]


def test_normalize_host() -> None:
    assert normalize_host("ns1.example.com", True) == "ns1.example.com."
    assert normalize_host("ns1.example.com.", False) == "ns1.example.com"
    assert normalize_host("ns1", True) == "ns1"
    assert normalize_host(".", False) == "."


def test_ptr_follows_final_dot(directory: MemoryDirectory) -> None:
    service = make_service(directory, final_dot=False)
    new_zone(service, BASIC, reverse=["2.0.192.in-addr.arpa"])
    ptr = attrs(directory, f"relativeDomainName=10,zoneName=2.0.192.in-addr.arpa,{ZONE_DN}")
    assert ptr["pTRRecord"] == ["www.example.com"]


# ------------------------------------------------------------ reverse zones


V4_REV = "2.0.192.in-addr.arpa"
V6_REV = "8.b.d.0.1.0.0.2.ip6.arpa"
V4_REV_DN = f"zoneName={V4_REV},{ZONE_DN}"
V6_REV_DN = f"zoneName={V6_REV},{ZONE_DN}"


def test_reverse_zone_entry_and_ptr_ipv4(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    new_zone(service, BASIC, reverse=[V4_REV])
    reverse = attrs(directory, V4_REV_DN)
    assert reverse["objectClass"] == ["dNSZone"]
    assert reverse["zoneName"] == [V4_REV]
    assert reverse["relativeDomainName"] == ["@"]
    assert reverse["sOARecord"] == attrs(directory, ZONE_DN)["sOARecord"]
    assert reverse["nSRecord"] == ["ns1.example.com."]
    ptr10 = attrs(directory, f"relativeDomainName=10,{V4_REV_DN}")
    assert ptr10 == {
        "objectClass": ["dNSZone"],
        "zoneName": [V4_REV],
        "relativeDomainName": ["10"],
        "pTRRecord": ["www.example.com."],
    }
    assert attrs(directory, f"relativeDomainName=1,{V4_REV_DN}")["pTRRecord"] == [
        "ns1.example.com."
    ]


def test_ptr_ipv6(service: ObjectService, directory: MemoryDirectory) -> None:
    new_zone(service, BASIC, reverse=[V6_REV])
    relative = ".".join(["0", "1", *["0"] * 22])
    assert reverse_relative("2001:db8::10", V6_REV) == relative
    ptr = attrs(directory, f"relativeDomainName={relative},{V6_REV_DN}")
    assert ptr["pTRRecord"] == ["www.example.com."]
    assert directory.get(f"relativeDomainName=10,{V4_REV_DN}") is None


def test_a_record_changes_maintain_ptr(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_zone(service, BASIC, reverse=[V4_REV])
    ptr10 = f"relativeDomainName=10,{V4_REV_DN}"
    patch(service, dn, dnsRecord=[*BASIC, rec("blog", "A", "192.0.2.10")])
    assert attrs(directory, ptr10)["pTRRecord"] == ["blog.example.com.", "www.example.com."]
    patch(service, dn, dnsRecord=[r for r in BASIC if r != rec("www", "A", "192.0.2.10")])
    assert directory.get(ptr10) is None
    assert directory.get(f"relativeDomainName=1,{V4_REV_DN}") is not None
    patch(service, dn, dnsRecord=[rec("ns1", "A", "192.0.2.2"), *BASIC[:2]])
    assert directory.get(f"relativeDomainName=1,{V4_REV_DN}") is None
    assert attrs(directory, f"relativeDomainName=2,{V4_REV_DN}")["pTRRecord"] == [
        "ns1.example.com."
    ]


def test_foreign_ptr_is_preserved(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_zone(service, BASIC, reverse=[V4_REV])
    foreign = f"relativeDomainName=99,{V4_REV_DN}"
    directory.add(
        foreign,
        {
            "objectClass": [b"dNSZone"],
            "zoneName": [V4_REV.encode()],
            "relativeDomainName": [b"99"],
            "pTRRecord": [b"other.example.org."],
        },
    )
    patch(service, dn, dnsRecord=BASIC[:3])
    assert attrs(directory, foreign)["pTRRecord"] == ["other.example.org."]


def test_reverse_zone_add_and_remove(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_zone(service, BASIC)
    assert directory.get(V4_REV_DN) is None
    patch(service, dn, reverseZones=[V4_REV])
    assert directory.get(V4_REV_DN) is not None
    assert directory.get(f"relativeDomainName=10,{V4_REV_DN}") is not None
    state = service.load("dns_zone", dn)
    assert state.tabs["main"].values["reverseZones"] == [V4_REV]
    patch(service, dn, reverseZones=[V4_REV, V6_REV])
    assert directory.get(V6_REV_DN) is not None
    patch(service, dn, reverseZones=[V6_REV])
    assert directory.get(V4_REV_DN) is None
    assert directory.get(f"relativeDomainName=10,{V4_REV_DN}") is None
    assert directory.get(V6_REV_DN) is not None
    patch(service, dn, reverseZones=None)
    assert directory.get(V6_REV_DN) is None


def test_reverse_zones_follow_soa_and_ns(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_zone(service, BASIC, reverse=[V4_REV])
    patch(service, dn, soaPrimary="ns9.example.com", soaMinimum=900)
    assert attrs(directory, V4_REV_DN)["sOARecord"] == attrs(directory, ZONE_DN)["sOARecord"]
    assert soa(directory, V4_REV_DN)[0] == "ns9.example.com."
    assert soa(directory, V4_REV_DN)[2] == "2026110702"
    patch(service, dn, dnsRecord=[*BASIC, rec("@", "NS", "ns2.example.com")])
    assert attrs(directory, V4_REV_DN)["nSRecord"] == ["ns1.example.com.", "ns2.example.com."]
    patch(service, dn, dnsRecord=[r for r in BASIC if r["type"] != "NS"])
    assert "nSRecord" not in attrs(directory, V4_REV_DN)
    assert soa(directory, V4_REV_DN)[2] == soa(directory)[2]


def test_reverse_zone_name_validation(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as err:
        new_zone(service, BASIC, reverse=["example.org"])
    assert "main.reverseZones" in err.value.fields


def test_zone_rename_updates_children(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_zone(service, BASIC, reverse=[V4_REV])
    patch(service, dn, zoneName="example.net")
    new_dn = f"zoneName=example.net,{DNS_OU}"
    assert attrs(directory, f"relativeDomainName=www,{new_dn}")["zoneName"] == ["example.net"]
    ptr = attrs(directory, f"relativeDomainName=10,zoneName={V4_REV},{new_dn}")
    assert ptr["pTRRecord"] == ["www.example.net."]


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    ("rtype", "value", "ok"),
    [
        ("A", "192.0.2.1", True),
        ("A", "2001:db8::1", False),
        ("A", "300.1.1.1", False),
        ("AAAA", "2001:db8::1", True),
        ("AAAA", "192.0.2.1", False),
        ("MX", "10 mail.example.com.", True),
        ("MX", "mail.example.com", False),
        ("MX", "x mail.example.com", False),
        ("MX", "70000 mail.example.com", False),
        ("SRV", "10 5 5060 sip.example.com.", True),
        ("SRV", "10 5 sip.example.com", False),
        ("SRV", "10 5 99999 sip.example.com", False),
        ("CNAME", "www.example.com.", True),
        ("CNAME", "not a host", False),
        ("NS", "ns1.example.com.", True),
        ("PTR", "host.example.com.", True),
        ("TXT", "v=spf1 -all", True),
        ("TXT", "   ", False),
        ("CAA", '0 issue "letsencrypt.org"', True),
        ("CAA", "issue letsencrypt.org", False),
        ("SSHFP", "4 2 ABCDEF0123", True),
        ("SSHFP", "4 2 xyz", False),
        ("DS", "12345 13 2 ABCDEF", True),
        ("NAPTR", '100 10 "u" "E2U+sip" "!^.*$!sip:x@y!" .', True),
        ("HINFO", '"PC" "Linux"', True),
        ("HINFO", "PC", False),
        ("SPF", "v=spf1 mx -all", True),
        ("SPF", "hello", False),
        ("NOPE", "x", False),
    ],
)
def test_value_validation(rtype: str, value: str, ok: bool) -> None:
    assert (validate_record("host", rtype, value) is None) is ok


def test_pseudo_type_names() -> None:
    assert validate_record("s1._domainkey", "DKIM", build_dkim("MIGf")) is None
    assert validate_record("mail", "DKIM", build_dkim("MIGf")) is not None
    assert validate_record("_dmarc", "DMARC", build_dmarc("reject", "mailto:a@b.c", 100)) is None
    assert validate_record("dmarc", "DMARC", build_dmarc()) is not None
    assert build_spf(["mx", "ip4:192.0.2.0/24"]) == "v=spf1 mx ip4:192.0.2.0/24 ~all"


def test_pseudo_records_are_stored_as_txt(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    records = [
        rec("@", "SPF", build_spf(["mx"], "-all")),
        rec("s1._domainkey", "DKIM", build_dkim("MIGfMA0")),
        rec("_dmarc", "DMARC", build_dmarc("quarantine")),
        rec("plain", "TXT", "just text"),
    ]
    dn = new_zone(service, records)
    assert attrs(directory, ZONE_DN)["tXTRecord"] == ["v=spf1 mx -all"]
    assert attrs(directory, f"relativeDomainName=_dmarc,{ZONE_DN}")["tXTRecord"] == [
        "v=DMARC1; p=quarantine"
    ]
    loaded = service.load("dns_zone", dn).tabs["main"].values["dnsRecord"]
    assert {r["type"] for r in loaded} == {"SPF", "DKIM", "DMARC", "TXT"}


@pytest.mark.parametrize(
    "bad",
    [
        rec("www", "A", "not-an-ip"),
        rec("bad name", "A", "192.0.2.1"),
        rec("www", "MX", "mail.example.com"),
        rec("www", "WAT", "x"),
        rec("", "A", "192.0.2.1"),
    ],
)
def test_invalid_record_rejected(service: ObjectService, bad: dict[str, str]) -> None:
    with pytest.raises(ObjectValidationError) as err:
        new_zone(service, [*BASIC, bad])
    assert "main.dnsRecord" in err.value.fields


def test_error_names_record_position(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as err:
        new_zone(service, [rec("a", "A", "192.0.2.1"), rec("b", "A", "nope")])
    assert err.value.fields["main.dnsRecord"].startswith("Record 2:")


def test_cname_conflict(service: ObjectService, directory: MemoryDirectory) -> None:
    with pytest.raises(ObjectValidationError) as err:
        new_zone(service, [rec("www", "CNAME", "web.example.com"), rec("www", "A", "192.0.2.1")])
    assert "CNAME" in err.value.fields["main.dnsRecord"]
    with pytest.raises(ObjectValidationError):
        new_zone(service, [rec("www", "CNAME", "a.example.com"), rec("WWW", "TXT", "x")])
    with pytest.raises(ObjectValidationError):
        new_zone(
            service, [rec("www", "CNAME", "a.example.com"), rec("www", "CNAME", "b.example.com")]
        )
    with pytest.raises(ObjectValidationError):
        new_zone(service, [rec("@", "CNAME", "a.example.com")])
    assert directory.get(ZONE_DN) is None
    new_zone(service, [rec("www", "CNAME", "a.example.com"), rec("web", "A", "192.0.2.1")])


def test_validate_records_pure() -> None:
    assert validate_records([Record("a", "A", "192.0.2.1"), Record("b", "CNAME", "x.")]) == []
    assert validate_records([Record("a", "CNAME", "x."), Record("a", "MX", "1 y.")])


def test_duplicate_records_are_merged(service: ObjectService, directory: MemoryDirectory) -> None:
    new_zone(service, [rec("www", "A", "192.0.2.1"), rec("www", "A", "192.0.2.1")])
    assert attrs(directory, f"relativeDomainName=www,{ZONE_DN}")["aRecord"] == ["192.0.2.1"]


def test_zone_name_unique(service: ObjectService) -> None:
    new_zone(service, BASIC)
    with pytest.raises(ObjectValidationError):
        new_zone(service, BASIC)


# --------------------------------------------------------------------- delete


def test_zone_delete_is_recursive(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_zone(service, BASIC, reverse=[V4_REV, V6_REV])
    assert len(directory) > 8
    service.delete("dns_zone", dn)
    assert [d for d in directory.dns() if d.endswith(DNS_OU) and d != DNS_OU] == []


def test_delete_keeps_other_zones(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = new_zone(service, BASIC)
    service.create(
        "dns_zone",
        BASE,
        {
            "main": {
                "values": zone_values(zoneName="other.org", dnsRecord=[rec("a", "A", "192.0.2.3")])
            }
        },
    )
    service.delete("dns_zone", dn)
    assert directory.get(f"relativeDomainName=a,zoneName=other.org,{DNS_OU}") is not None


# ----------------------------------------------------------- views and ACLs


def test_acl_and_view_roundtrip(service: ObjectService, directory: MemoryDirectory) -> None:
    acl_dn = service.create(
        "dns_acl",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "internal",
                    "hrcDNSAclMatchList": ["10.0.0.0/8", "!192.0.2.1", "localhost"],
                }
            }
        },
    )
    assert acl_dn == f"cn=internal,{DNS_OU}"
    zone_dn = new_zone(service, BASIC)
    view_dn = service.create(
        "dns_view",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "inside",
                    "hrcDNSViewMatchClientsAcl": [acl_dn],
                    "hrcDNSViewMatchDestinationsAcl": [acl_dn],
                    "hrcDNSViewMatchRecursiveOnly": True,
                    "hrcDNSZoneDn": [zone_dn],
                }
            }
        },
    )
    entry = attrs(directory, view_dn)
    assert entry["objectClass"] == ["hrcDNSView"]
    assert entry["hrcDNSViewMatchRecursiveOnly"] == ["TRUE"]
    assert entry["hrcDNSZoneDn"] == [zone_dn]
    assert attrs(directory, acl_dn)["hrcDNSAclMatchList"] == [
        "!192.0.2.1",
        "10.0.0.0/8",
        "localhost",
    ]
    # views and ACLs are not zones
    assert [r.dn for r in service.list("dns_zone", BASE).items] == [zone_dn]
    assert [r.dn for r in service.list("dns_view", BASE).items] == [view_dn]


def test_view_rejects_unknown_references(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError):
        service.create(
            "dns_view",
            BASE,
            {"main": {"values": {"cn": "v", "hrcDNSViewMatchClientsAcl": [f"cn=x,{DNS_OU}"]}}},
        )
