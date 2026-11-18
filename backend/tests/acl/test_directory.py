"""LdapAclDirectory adapter and the test filter matcher."""

from __future__ import annotations

import pytest

from heracles.acl import LdapAclDirectory
from heracles.ldap.client import Entry, NoSuchObjectError, Scope
from tests.acl.fakes import MemoryClient, compile_filter
from tests.acl.world import BASE, World


def entry(**attrs: list[str]) -> Entry:
    return Entry("cn=x", {k: [v.encode() for v in vs] for k, vs in attrs.items()})


@pytest.mark.parametrize(
    ("flt", "expected"),
    [
        ("(cn=X)", True),
        ("(CN=x)", True),
        ("(cn=y)", False),
        ("(mail=*)", True),
        ("(phone=*)", False),
        ("(cn=*x*)", True),
        ("(cn=a*)", False),
        ("(&(cn=x)(mail=*))", True),
        ("(&(cn=x)(phone=*))", False),
        ("(|(cn=y)(mail=*))", True),
        ("(!(cn=y))", True),
        ("(!(cn=x))", False),
        ("(cn=\\78)", True),
    ],
)
def test_filter_matcher(flt: str, expected: bool) -> None:
    assert compile_filter(flt)(entry(cn=["x"], mail=["a@b"])) is expected


@pytest.mark.parametrize("flt", ["cn=x", "(cn)", "(&(cn=x)", "(cn=x)junk", "(!(cn=x)"])
def test_filter_matcher_rejects(flt: str) -> None:
    with pytest.raises((ValueError, IndexError)):
        compile_filter(flt)


def test_memory_client_search_scopes() -> None:
    c = MemoryClient(BASE)
    c.put(BASE, objectClass=["top"])
    c.put(f"ou=a,{BASE}", objectClass=["top"])
    c.put(f"cn=b,ou=a,{BASE}", objectClass=["top"])
    assert len(list(c.search(BASE, scope=Scope.SUBTREE))) == 3
    assert len(list(c.search(BASE, scope=Scope.ONE))) == 1
    assert len(list(c.search(BASE, scope=Scope.BASE))) == 1
    with pytest.raises(NoSuchObjectError):
        list(c.search("dc=none"))
    assert c.get("cn=none") is None


def test_adapter_lookups() -> None:
    w = World()
    alice = w.user("alice")
    group = w.group("g", [alice])
    posix = w.posix_group("p", ["alice"])
    role = w.occupation("o", [alice])
    d = LdapAclDirectory(w.client)
    assert d.groups_of_user(alice) == [group]
    assert d.posix_groups_by_uid("alice") == [posix]
    assert d.roles_of_user(alice) == [role]
    acl_role = w.acl_role("r", "0:all;r")
    assert d.role_templates(acl_role) == ["0:all;r"]
    assert d.role_templates(f"cn=none,{BASE}") == []
    w.assign(BASE, acl_role, ["*"])
    [found] = d.assignment_entries()
    assert found.dn == BASE and len(found.values) == 1
    assert d.user_matches_filter(alice, "(uid=alice)")
    assert not d.user_matches_filter(alice, "(uid=bob)")
    assert not d.user_matches_filter(f"uid=none,{BASE}", "(uid=*)")
    assert d.search_targets(BASE, "(uid=*)", 5) == [alice]
    assert d.search_targets(f"ou=none,{BASE}", "(uid=*)", 5) == []
    for i in range(4):
        w.user(f"u{i}")
    assert len(d.search_targets(BASE, "(uid=*)", 3)) == 3


def test_roles_of_user_and_resolver_ignore_dsa_service_accounts() -> None:
    w = World()
    alice = w.user("alice")
    role = w.occupation("ops", [alice])
    dsa_dn = f"cn=backup,ou=dsa,{BASE}"
    w.ensure(f"ou=dsa,{BASE}")
    w.client.put(
        dsa_dn,
        objectClass=["organizationalRole", "simpleSecurityObject"],
        cn=["backup"],
        roleOccupant=[alice],
    )
    dsa_upper_dn = f"cn=backup-upper,ou=dsa,{BASE}"
    w.client.put(
        dsa_upper_dn,
        objectClass=["organizationalRole", "SIMPLESECURITYOBJECT"],
        cn=["backup-upper"],
        roleOccupant=[alice],
    )
    admin_role = w.acl_role("admin", "0:all;rwcdm")
    w.assign(BASE, admin_role, [dsa_dn, dsa_upper_dn])

    d = LdapAclDirectory(w.client)
    assert d.roles_of_user(alice) == [role]
    assert w.resolve(alice).rules == {}
