"""Authoritative DNS wire protocol, exercised over real UDP and TCP sockets."""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rdata
import dns.rdatatype
import pytest
from dns.rdtypes.ANY.MX import MX
from dns.rdtypes.ANY.PTR import PTR
from dns.rdtypes.ANY.SOA import SOA
from dns.rdtypes.ANY.TXT import TXT
from dns.rdtypes.IN.A import A

from heracles.ldap.memory import MemoryDirectory
from heracles_plugins.dns.server import DnsServer

HOST = "127.0.0.1"
BASE = "dc=example,dc=test"
DNS_OU = f"ou=dns,{BASE}"
FORWARD = "example.com"
REVERSE = "2.0.192.in-addr.arpa"
FORWARD_DN = f"zoneName={FORWARD},{DNS_OU}"
REVERSE_DN = f"zoneName={REVERSE},{DNS_OU}"
ZONE_TTL = 300
SOA_TEXT = "ns1.example.com. hostmaster.example.com. 2026010101 3600 600 86400 300"


def zone_entry(zone: str, **attrs: str) -> dict[str, list[bytes]]:
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
        f"relativeDomainName=quoted,{FORWARD_DN}",
        child_entry(FORWARD, "quoted", tXTRecord='say "hi" \\ done'),
    )
    d.add(
        f"relativeDomainName=long,{FORWARD_DN}",
        child_entry(FORWARD, "long", tXTRecord="x" * 300),
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
def server(directory: MemoryDirectory) -> Iterator[DnsServer]:
    instance = DnsServer(directory, HOST, 0)
    instance.start()
    try:
        yield instance
    finally:
        instance.stop()


def udp_query(server: DnsServer, name: str, rdtype: str) -> dns.message.Message:
    query = dns.message.make_query(name, rdtype)
    return dns.query.udp(query, HOST, port=server.bound_port, timeout=2)


def tcp_query(server: DnsServer, name: str, rdtype: str) -> dns.message.Message:
    query = dns.message.make_query(name, rdtype)
    return dns.query.tcp(query, HOST, port=server.bound_port, timeout=2)


def test_start_binds_an_ephemeral_udp_port(server: DnsServer) -> None:
    assert server.bound_port > 0


def test_udp_answers_a_with_zone_ttl(server: DnsServer) -> None:
    response = udp_query(server, "www.example.com", "A")
    assert response.rcode() == dns.rcode.NOERROR
    assert response.flags & dns.flags.AA
    assert len(response.answer) == 1

    rrset = response.answer[0]
    assert rrset.name == dns.name.from_text("www.example.com.")
    assert rrset.rdtype == dns.rdatatype.A
    assert rrset.ttl == ZONE_TTL

    record = cast("dns.rdata.Rdata", rrset[0])
    assert isinstance(record, A)
    assert record.address == "192.0.2.10"


def test_udp_answers_mx(server: DnsServer) -> None:
    response = udp_query(server, "example.com", "MX")
    rrset = response.answer[0]
    assert rrset.rdtype == dns.rdatatype.MX

    record = cast("dns.rdata.Rdata", rrset[0])
    assert isinstance(record, MX)
    assert record.preference == 10
    assert record.exchange == dns.name.from_text("mail.example.com.")


def test_udp_answers_pseudo_spf_record_as_txt(server: DnsServer) -> None:
    response = udp_query(server, "example.com", "TXT")
    rrset = response.answer[0]
    assert rrset.rdtype == dns.rdatatype.TXT

    record = cast("dns.rdata.Rdata", rrset[0])
    assert isinstance(record, TXT)
    assert record.strings == (b"v=spf1 -all",)


def test_udp_answers_txt_with_quote_and_backslash(server: DnsServer) -> None:
    response = udp_query(server, "quoted.example.com", "TXT")
    rrset = response.answer[0]
    assert rrset.rdtype == dns.rdatatype.TXT

    record = cast("dns.rdata.Rdata", rrset[0])
    assert isinstance(record, TXT)
    assert record.strings == (b'say "hi" \\ done',)


def test_udp_splits_long_txt_into_255_byte_chunks(server: DnsServer) -> None:
    response = udp_query(server, "long.example.com", "TXT")
    rrset = response.answer[0]
    assert rrset.rdtype == dns.rdatatype.TXT

    record = cast("dns.rdata.Rdata", rrset[0])
    assert isinstance(record, TXT)
    assert record.strings == (b"x" * 255, b"x" * 45)
    assert b"".join(record.strings) == b"x" * 300


def test_udp_answers_ptr_in_reverse_zone(server: DnsServer) -> None:
    response = udp_query(server, "10.2.0.192.in-addr.arpa", "PTR")
    rrset = response.answer[0]
    assert rrset.name == dns.name.from_text("10.2.0.192.in-addr.arpa.")
    assert rrset.rdtype == dns.rdatatype.PTR

    record = cast("dns.rdata.Rdata", rrset[0])
    assert isinstance(record, PTR)
    assert record.target == dns.name.from_text("www.example.com.")


def test_udp_nxdomain_carries_soa_in_authority(server: DnsServer) -> None:
    # The forward zone has a wildcard, the reverse zone has none.
    response = udp_query(server, "99.2.0.192.in-addr.arpa", "PTR")
    assert response.rcode() == dns.rcode.NXDOMAIN
    assert response.flags & dns.flags.AA
    assert not response.answer

    authority = [rrset for rrset in response.authority if rrset.rdtype == dns.rdatatype.SOA]
    assert len(authority) == 1
    assert authority[0].name == dns.name.from_text("2.0.192.in-addr.arpa.")

    record = cast("dns.rdata.Rdata", authority[0][0])
    assert isinstance(record, SOA)
    assert record.mname == dns.name.from_text("ns1.example.com.")
    assert record.serial == 2026010101


def test_udp_nodata_carries_soa_in_authority(server: DnsServer) -> None:
    response = udp_query(server, "www.example.com", "MX")
    assert response.rcode() == dns.rcode.NOERROR
    assert not response.answer
    assert [rrset.rdtype for rrset in response.authority] == [dns.rdatatype.SOA]


def test_tcp_returns_the_same_answer(server: DnsServer) -> None:
    response = tcp_query(server, "www.example.com", "A")
    assert response.rcode() == dns.rcode.NOERROR
    assert response.flags & dns.flags.AA
    assert len(response.answer) == 1

    record = cast("dns.rdata.Rdata", response.answer[0][0])
    assert isinstance(record, A)
    assert record.address == "192.0.2.10"


def test_handle_answers_a_query_without_sockets(server: DnsServer) -> None:
    query = dns.message.make_query("www.example.com", "A")
    response = dns.message.from_wire(server.handle(query.to_wire()))
    assert response.flags & dns.flags.AA
    assert response.answer[0].ttl == ZONE_TTL

    record = cast("dns.rdata.Rdata", response.answer[0][0])
    assert isinstance(record, A)
    assert record.address == "192.0.2.10"


def test_handle_malformed_wire_returns_formerr(server: DnsServer) -> None:
    response = dns.message.from_wire(server.handle(b"\x01\x02\x03\x04"))
    assert response.rcode() == dns.rcode.FORMERR
