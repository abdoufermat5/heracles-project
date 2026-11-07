import pytest

from heracles.ldap.client import Entry
from heracles.ldap.filter import (
    And,
    Equal,
    FilterError,
    GreaterOrEqual,
    LessOrEqual,
    Not,
    Or,
    Present,
    Substring,
    escape_filter_value,
    matches,
    parse_filter,
)

ENTRY = Entry(
    "uid=jdoe,ou=people,dc=x",
    {
        "objectClass": [b"inetOrgPerson", b"top"],
        "uid": [b"jdoe"],
        "cn": [b"John Doe"],
        "sn": [b"Doe"],
        "uidNumber": [b"1005"],
        "mail": [b"John.Doe@Example.org", b"jd@example.org"],
        "member": [b"uid=a, ou=people,dc=x"],
        "description": [b"caf\xc3\xa9 (test)*"],
    },
)


def test_parse_structure() -> None:
    node = parse_filter("(&(a=1)(|(b=2)(!(c=3)))(d=*)(e=x*y*z))")
    assert node == And(
        (
            Equal("a", "1"),
            Or((Equal("b", "2"), Not(Equal("c", "3")))),
            Present("d"),
            Substring("e", "x", ("y",), "z"),
        )
    )


def test_parse_ordering_and_approx() -> None:
    assert parse_filter("(n>=5)") == GreaterOrEqual("n", "5")
    assert parse_filter("(n<=5)") == LessOrEqual("n", "5")
    assert parse_filter("(cn~=bob)") == Equal("cn", "bob")


def test_parse_substring_variants() -> None:
    assert parse_filter("(cn=*a*)") == Substring("cn", None, ("a",), None)
    assert parse_filter("(cn=a*)") == Substring("cn", "a", (), None)
    assert parse_filter("(cn=*z)") == Substring("cn", None, (), "z")


def test_parse_escapes() -> None:
    assert parse_filter(r"(cn=a\2ab\28c\29\5c)") == Equal("cn", "a*b(c)\\")
    assert parse_filter(r"(cn=caf\c3\a9)") == Equal("cn", "café")
    # An escaped star is a literal, not a wildcard.
    assert parse_filter(r"(cn=a\2a)") == Equal("cn", "a*")


@pytest.mark.parametrize(
    "bad",
    ["(", "(a=1", "(&)", "(a)", "(a=1))", "(cn=\\zz)", "(:dn:=x)", "(=x)", "(a=(b))", "(cn=\\ff)"],
)
def test_parse_errors(bad: str) -> None:
    with pytest.raises(FilterError):
        parse_filter(bad)


def test_bare_item_is_tolerated() -> None:
    assert parse_filter("cn=foo") == Equal("cn", "foo")


@pytest.mark.parametrize(
    ("flt", "expected"),
    [
        ("(uid=JDOE)", True),
        ("(UID=jdoe)", True),
        ("(uid=other)", False),
        ("(objectClass=*)", True),
        ("(telephoneNumber=*)", False),
        ("(!(telephoneNumber=*))", True),
        ("(&(uid=jdoe)(sn=doe))", True),
        ("(&(uid=jdoe)(sn=smith))", False),
        ("(|(uid=x)(sn=doe))", True),
        ("(cn=john*)", True),
        ("(cn=*DOE)", True),
        ("(cn=*hn D*)", True),
        ("(cn=j*n*e)", True),
        ("(cn=j*e*n)", False),
        ("(cn=*ohn*oe*)", True),
        ("(mail=jd@*)", True),
        ("(uidNumber>=1000)", True),
        ("(uidNumber>=2000)", False),
        ("(uidNumber<=1005)", True),
        ("(uidNumber<=999)", False),
        ("(uidNumber>=999)", True),  # numeric, not lexical
        ("(cn~=john doe)", True),
        ("(member=UID=a,OU=people,DC=x)", True),
        (r"(description=caf\c3\a9 \28test\29\2a)", True),
        (r"(description=*\2a)", True),
    ],
)
def test_matches(flt: str, expected: bool) -> None:
    assert matches(ENTRY, flt) is expected


def test_matches_accepts_ast() -> None:
    assert matches(ENTRY, Equal("uid", "jdoe"))


def test_substring_overlap_is_not_double_counted() -> None:
    entry = Entry("cn=a,dc=x", {"cn": [b"ab"]})
    assert not matches(entry, "(cn=ab*b)")
    assert matches(entry, "(cn=a*b)")


def test_escape_round_trip() -> None:
    raw = "a*b(c)d\\e\x00"
    escaped = escape_filter_value(raw)
    assert "*" not in escaped and "(" not in escaped and ")" not in escaped
    assert parse_filter(f"(cn={escaped})") == Equal("cn", raw)
    assert escape_filter_value("plain") == "plain"
