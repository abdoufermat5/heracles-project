"""Answers taken from the zones the DNS plugin stores in the directory (no sockets)."""

from __future__ import annotations

import pytest

from heracles.ldap.memory import MemoryDirectory
from heracles_plugins.dns.answer import DEFAULT_TTL, Answer, Zone, load_zones, resolve, zone_for
from heracles_plugins.dns.records import Record

BASE = "dc=example,dc=test"
DNS_OU = f"ou=dns,{BASE}"
FORWARD = "example.com"
REVERSE = "2.0.192.in-addr.arpa"
FORWARD_DN = f"zoneName={FORWARD},{DNS_OU}"
REVERSE_DN = f"zoneName={REVERSE},{DNS_OU}"
ZONE_TTL = 300
SOA_TEXT = "ns1.example.com. hostmaster.example.com. 2026010101 3600 600 86400 300"


def zone_entry(zone: str, **attrs: str) -> dict[str, list[bytes]]:
    """Apex entry of a zone, with ``attrs`` as single-valued attributes."""
    values: dict[str, list[bytes]] = {
        "objectClass": [b"top", b"dNSZone"],
        "relativeDomainName": [b"@"],
        "zoneName": [zone.encode()],
        "dNSTTL": [str(ZONE_TTL).encode()],
        "sOARecord": [SOA_TEXT.encode()],
    }
    values.update({name: [value.encode()] for name, value in attrs.items()})
    return values


def child_entry(zone: str, name: str, **attrs: str) -> dict[str, list[bytes]]:
    values: dict[str, list[bytes]] = {
        "objectClass": [b"top", b"dNSZone"],
        "relativeDomainName": [name.encode()],
        "zoneName": [zone.encode()],
    }
    values.update({attr: [value.encode()] for attr, value in attrs.items()})
    return values


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"top", b"domain"], "dc": [b"example"]})
    d.add(DNS_OU, {"objectClass": [b"top", b"organizationalUnit"], "ou": [b"dns"]})
    d.add(
        FORWARD_DN,
        zone_entry(
            FORWARD,
            nSRecord="ns1.example.com.",
            mXRecord="10 mail.example.com.",
            tXTRecord="v=spf1 -all",
        ),
    )
    d.add(
        f"relativeDomainName=www,{FORWARD_DN}",
        child_entry(FORWARD, "www", aRecord="192.0.2.10", aAAARecord="2001:db8::10"),
    )
    d.add(
        f"relativeDomainName=alias,{FORWARD_DN}",
        child_entry(FORWARD, "alias", cNAMERecord="www.example.com."),
    )
    d.add(
        f"relativeDomainName=*,{FORWARD_DN}",
        child_entry(FORWARD, "*", aRecord="192.0.2.99"),
    )
    d.add(REVERSE_DN, zone_entry(REVERSE))
    d.add(
        f"relativeDomainName=10,{REVERSE_DN}",
        child_entry(REVERSE, "10", pTRRecord="www.example.com."),
    )
    return d


@pytest.fixture
def zones(directory: MemoryDirectory) -> list[Zone]:
    return load_zones(directory)


# ------------------------------------------------------------------- load_zones


def test_load_zones_reads_forward_and_reverse_apexes(zones: list[Zone]) -> None:
    by_name = {zone.name: zone for zone in zones}
    assert set(by_name) == {FORWARD, REVERSE}

    forward = by_name[FORWARD]
    assert forward.ttl == ZONE_TTL
    assert forward.soa == SOA_TEXT

    reverse = by_name[REVERSE]
    assert reverse.ttl == ZONE_TTL
    assert reverse.soa == SOA_TEXT


def test_load_zones_groups_records_by_relative_name(zones: list[Zone]) -> None:
    forward = next(zone for zone in zones if zone.name == FORWARD)

    apex = {(record.name, record.type, record.value) for record in forward.records["@"]}
    assert ("@", "NS", "ns1.example.com.") in apex
    assert ("@", "MX", "10 mail.example.com.") in apex
    # The pseudo type stored as TXT keeps its SPF classification.
    assert ("@", "SPF", "v=spf1 -all") in apex

    assert {(record.type, record.value) for record in forward.records["www"]} == {
        ("A", "192.0.2.10"),
        ("AAAA", "2001:db8::10"),
    }
    assert forward.records["alias"] == (Record("alias", "CNAME", "www.example.com."),)
    assert forward.records["*"] == (Record("*", "A", "192.0.2.99"),)


def test_load_zones_reads_reverse_children(zones: list[Zone]) -> None:
    reverse = next(zone for zone in zones if zone.name == REVERSE)
    assert reverse.records["10"] == (Record("10", "PTR", "www.example.com."),)


def test_load_zones_tolerates_a_missing_base() -> None:
    assert load_zones(MemoryDirectory(BASE)) == []


def test_load_zones_defaults_ttl_when_absent() -> None:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"top", b"domain"], "dc": [b"example"]})
    d.add(DNS_OU, {"objectClass": [b"top", b"organizationalUnit"], "ou": [b"dns"]})
    d.add(
        f"zoneName=default.test,{DNS_OU}",
        {
            "objectClass": [b"top", b"dNSZone"],
            "relativeDomainName": [b"@"],
            "zoneName": [b"default.test"],
        },
    )
    assert [zone.ttl for zone in load_zones(d)] == [DEFAULT_TTL]


# ----------------------------------------------------------------------- resolve


def test_resolve_a(zones: list[Zone]) -> None:
    answer = resolve(zones, "www.example.com", "A")
    assert answer.nxdomain is False
    assert answer.zone == FORWARD
    assert answer.records == (Record("www", "A", "192.0.2.10"),)


def test_resolve_aaaa(zones: list[Zone]) -> None:
    answer = resolve(zones, "www.example.com", "AAAA")
    assert answer.records == (Record("www", "AAAA", "2001:db8::10"),)


def test_resolve_mx_at_apex(zones: list[Zone]) -> None:
    answer = resolve(zones, "example.com", "MX")
    assert answer.records == (Record("@", "MX", "10 mail.example.com."),)


def test_resolve_txt_at_apex_returns_spf_record(zones: list[Zone]) -> None:
    answer = resolve(zones, "example.com", "TXT")
    assert answer.records == (Record("@", "SPF", "v=spf1 -all"),)


def test_resolve_soa_at_apex_returns_sOARecord_text(zones: list[Zone]) -> None:
    answer = resolve(zones, "example.com", "SOA")
    assert answer.records == (Record("@", "SOA", SOA_TEXT),)


def test_resolve_soa_without_zone_soa_is_nodata() -> None:
    zone = Zone(
        name="empty.test",
        ttl=300,
        soa="",
        records={"www": (Record("www", "A", "192.0.2.1"),)},
    )
    answer = resolve([zone], "empty.test", "SOA")
    assert answer.records == ()
    assert answer.nxdomain is False


def test_resolve_cname_follows_target(zones: list[Zone]) -> None:
    answer = resolve(zones, "alias.example.com", "A")
    assert len(answer.records) == 2
    assert answer.records[0] == Record("alias", "CNAME", "www.example.com.")
    assert Record("www", "A", "192.0.2.10") in answer.records


def test_resolve_cname_query_does_not_follow(zones: list[Zone]) -> None:
    answer = resolve(zones, "alias.example.com", "CNAME")
    assert answer.records == (Record("alias", "CNAME", "www.example.com."),)


def test_resolve_unknown_name_is_nxdomain_with_soa(zones: list[Zone]) -> None:
    # The forward zone has a wildcard, the reverse zone has none.
    answer = resolve(zones, "99.2.0.192.in-addr.arpa", "PTR")
    assert answer.records == ()
    assert answer.nxdomain is True
    assert answer.zone == REVERSE
    assert answer.soa == Record("@", "SOA", SOA_TEXT)


def test_resolve_any_returns_every_record_at_name(zones: list[Zone]) -> None:
    answer = resolve(zones, "www.example.com", "ANY")
    assert {(record.name, record.type, record.value) for record in answer.records} == {
        ("www", "A", "192.0.2.10"),
        ("www", "AAAA", "2001:db8::10"),
    }


def test_resolve_absent_type_is_nodata(zones: list[Zone]) -> None:
    answer = resolve(zones, "www.example.com", "MX")
    assert answer.records == ()
    assert answer.nxdomain is False
    assert answer.zone == FORWARD
    assert answer.soa == Record("@", "SOA", SOA_TEXT)


def test_resolve_wildcard_rewrites_name(zones: list[Zone]) -> None:
    answer = resolve(zones, "anything.example.com", "A")
    assert answer.nxdomain is False
    assert answer.records == (Record("anything", "A", "192.0.2.99"),)


def test_resolve_ignores_case_and_trailing_dot(zones: list[Zone]) -> None:
    answer = resolve(zones, "WWW.Example.COM.", "A")
    assert answer.records == (Record("www", "A", "192.0.2.10"),)


def test_resolve_ptr_in_reverse_zone(zones: list[Zone]) -> None:
    answer = resolve(zones, "10.2.0.192.in-addr.arpa", "PTR")
    assert answer.zone == REVERSE
    assert answer.records == (Record("10", "PTR", "www.example.com."),)


def test_resolve_without_matching_zone(zones: list[Zone]) -> None:
    answer = resolve(zones, "mail.example.org", "A")
    assert answer == Answer(records=(), nxdomain=True, zone=None)
    assert answer.soa is None


# ---------------------------------------------------------------------- zone_for


def test_zone_for_prefers_longest_origin() -> None:
    parent = Zone(name="example.com", ttl=300, soa="", records={})
    child = Zone(name="sub.example.com", ttl=60, soa="", records={})

    assert zone_for([parent, child], "a.b.sub.example.com") is child
    assert zone_for([child, parent], "a.b.sub.example.com.") is child
    assert zone_for([parent, child], "SUB.EXAMPLE.COM.") is child
    assert zone_for([parent, child], "example.com") is parent


def test_zone_for_requires_a_label_boundary() -> None:
    zone = Zone(name="example.com", ttl=300, soa="", records={})
    assert zone_for([zone], "notexample.com") is None
    assert zone_for([zone], "example.org") is None
