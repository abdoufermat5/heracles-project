import base64

import pytest

from heracles.ldap.client import Entry
from heracles.ldap.ldif import LdifError, dump_ldif, parse_ldif

SAMPLE = """\
version: 1
# a comment
dn: dc=x
objectClass: top
objectClass: dcObject
dc: x

dn: cn=Long,dc=x
cn: Long
description: aaaaaaaaaa
 bbbbbbbbbb
 cccccccccc
displayName:: Q2Fmw6k=
empty:
"""


def test_parse_basic() -> None:
    entries = parse_ldif(SAMPLE)
    assert [e.dn for e in entries] == ["dc=x", "cn=Long,dc=x"]
    assert entries[0].attrs["objectClass"] == [b"top", b"dcObject"]
    assert entries[1].text("description") == "aaaaaaaaaabbbbbbbbbbcccccccccc"
    assert entries[1].text("displayName") == "Café"
    assert entries[1].get("empty") == [b""]


def test_parse_merges_attr_case_insensitively() -> None:
    (entry,) = parse_ldif("dn: cn=a\ncn: a\nCN: b\n")
    assert entry.attrs == {"cn": [b"a", b"b"]}


def test_round_trip_special_values() -> None:
    entry = Entry(
        "cn=Zoë,dc=x",
        {
            "cn": [b"Zo\xc3\xab"],
            "a": [b" leading", b"trailing ", b":colon", b"<lt", b"new\nline", b"\x00\xff"],
            "long": [b"x" * 300],
            "binary": [bytes(range(256))],
            "plain": [b"ok"],
        },
    )
    text = dump_ldif([entry, Entry("dc=y", {"dc": [b"y"]})])
    assert all(len(line) <= 76 for line in text.splitlines())
    assert "dn:: " in text
    out = parse_ldif(text)
    assert out[0] == entry
    assert out[1].dn == "dc=y"


def test_dump_uses_base64_for_non_ascii() -> None:
    text = dump_ldif([Entry("dc=x", {"cn": ["é".encode()]})])
    assert f"cn:: {base64.b64encode('é'.encode()).decode()}" in text


def test_empty() -> None:
    assert parse_ldif("") == []
    assert dump_ldif([]) == ""


@pytest.mark.parametrize(
    "bad",
    [
        "cn: a\n",
        "dn: dc=x\ncn:: !!!\n",
        "dn: dc=x\nnocolon\n",
        "dn: dc=x\nchangetype: add\n",
        "dn: dc=x\ndn: dc=y\n",
        "dn: dc=x\njpeg:< file:///x\n",
    ],
)
def test_errors(bad: str) -> None:
    with pytest.raises(LdifError):
        parse_ldif(bad)
