import pytest

from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    DirectoryError,
    Modification,
    NoSuchObjectError,
    Scope,
    SizeLimitExceededError,
)
from heracles.ldap.memory import MemoryDirectory

LDIF = """\
dn: dc=heracles,dc=test
objectClass: top
objectClass: dcObject
objectClass: organization
dc: heracles
o: Heracles

dn: ou=people,dc=heracles,dc=test
objectClass: organizationalUnit
ou: people

dn: uid=alice,ou=people,dc=heracles,dc=test
objectClass: inetOrgPerson
uid: alice
cn: Alice
sn: A
userPassword: secret

dn: uid=bob,ou=people,dc=heracles,dc=test
objectClass: inetOrgPerson
uid: bob
cn: Bob
sn: B

dn: ou=groups,dc=heracles,dc=test
objectClass: organizationalUnit
ou: groups
"""


@pytest.fixture
def d() -> MemoryDirectory:
    return MemoryDirectory.from_ldif(LDIF)


def test_is_directory_client(d: MemoryDirectory) -> None:
    assert isinstance(d, DirectoryClient)
    assert d.base_dn == "dc=heracles,dc=test"


def test_from_ldif_is_order_independent() -> None:
    reversed_ldif = "\n\n".join(reversed(LDIF.strip().split("\n\n")))
    assert len(MemoryDirectory.from_ldif(reversed_ldif)) == 5


def test_search_scopes(d: MemoryDirectory) -> None:
    base = "dc=heracles,dc=test"
    assert [e.dn for e in d.search(base, scope=Scope.BASE)] == [base]
    one = {e.dn for e in d.search(base, scope=Scope.ONE)}
    assert one == {"ou=people,dc=heracles,dc=test", "ou=groups,dc=heracles,dc=test"}
    assert len(list(d.search(base))) == 5
    assert len(list(d.search("ou=people," + base, scope=Scope.ONE))) == 2


def test_search_filter_and_attrs(d: MemoryDirectory) -> None:
    (e,) = d.search(
        "dc=heracles,dc=test", "(&(objectClass=inetOrgPerson)(uid=ALICE))", attrs=["CN"]
    )
    assert e.attrs == {"cn": [b"Alice"]}
    allattrs = d.get("uid=alice,ou=people,dc=heracles,dc=test")
    assert allattrs is not None and allattrs.text("sn") == "A"


def test_search_missing_base_raises_eagerly(d: MemoryDirectory) -> None:
    with pytest.raises(NoSuchObjectError):
        d.search("ou=nope,dc=heracles,dc=test")


def test_size_limit(d: MemoryDirectory) -> None:
    base = "dc=heracles,dc=test"
    assert len(list(d.search(base, size_limit=5))) == 5
    with pytest.raises(SizeLimitExceededError):
        d.search(base, size_limit=4)


def test_results_are_copies(d: MemoryDirectory) -> None:
    e = d.get("uid=alice,ou=people,dc=heracles,dc=test")
    assert e is not None
    e.attrs["cn"].append(b"Mutated")
    again = d.get("UID=Alice, ou=people,dc=heracles,dc=test")
    assert again is not None and again.get("cn") == [b"Alice"]


def test_get_missing(d: MemoryDirectory) -> None:
    assert d.get("uid=zed,ou=people,dc=heracles,dc=test") is None


def test_add_rules(d: MemoryDirectory) -> None:
    d.add("uid=c,ou=people,dc=heracles,dc=test", {"objectClass": [b"inetOrgPerson"], "cn": [b"C"]})
    stored = d.get("uid=c,ou=people,dc=heracles,dc=test")
    assert stored is not None and stored.get("uid") == [b"c"]  # RDN value added
    with pytest.raises(AlreadyExistsError):
        d.add("UID=C,ou=people,dc=heracles,dc=test", {"cn": [b"C"]})
    with pytest.raises(NoSuchObjectError):
        d.add("cn=x,ou=missing,dc=heracles,dc=test", {"cn": [b"x"]})


def test_modify_ops(d: MemoryDirectory) -> None:
    dn = "uid=alice,ou=people,dc=heracles,dc=test"
    d.modify(
        dn,
        [
            Modification("add", "mail", [b"a@x", b"b@x"]),
            Modification("replace", "sn", [b"Z"]),
            Modification("delete", "mail", [b"a@x"]),
            Modification("delete", "userPassword"),
        ],
    )
    e = d.get(dn)
    assert e is not None
    assert e.get("mail") == [b"b@x"]
    assert e.get("sn") == [b"Z"]
    assert e.get("userPassword") == []
    d.modify(dn, [Modification("replace", "mail")])
    again = d.get(dn)
    assert again is not None and again.get("mail") == []


def test_modify_is_atomic(d: MemoryDirectory) -> None:
    dn = "uid=alice,ou=people,dc=heracles,dc=test"
    with pytest.raises(DirectoryError):
        d.modify(dn, [Modification("replace", "sn", [b"Z"]), Modification("delete", "nosuch")])
    e = d.get(dn)
    assert e is not None and e.get("sn") == [b"A"]


def test_modify_errors(d: MemoryDirectory) -> None:
    dn = "uid=alice,ou=people,dc=heracles,dc=test"
    with pytest.raises(NoSuchObjectError):
        d.modify("uid=zed,ou=people,dc=heracles,dc=test", [])
    with pytest.raises(DirectoryError):
        d.modify(dn, [Modification("add", "cn", [b"Alice"])])  # duplicate value
    with pytest.raises(DirectoryError):
        d.modify(dn, [Modification("delete", "sn", [b"other"])])
    with pytest.raises(DirectoryError):
        d.modify(dn, [Modification("delete", "uid")])  # removes RDN value


def test_delete(d: MemoryDirectory) -> None:
    with pytest.raises(DirectoryError):
        d.delete("ou=people,dc=heracles,dc=test")
    d.delete("uid=bob,ou=people,dc=heracles,dc=test")
    d.delete("ou=people,dc=heracles,dc=test", recursive=True)
    assert "uid=alice,ou=people,dc=heracles,dc=test" not in d
    assert len(d) == 2
    with pytest.raises(NoSuchObjectError):
        d.delete("ou=people,dc=heracles,dc=test")


def test_rename_in_place_moves_subtree(d: MemoryDirectory) -> None:
    new = d.rename("ou=people,dc=heracles,dc=test", "ou=users")
    assert new == "ou=users,dc=heracles,dc=test"
    assert d.get("ou=people,dc=heracles,dc=test") is None
    ou = d.get(new)
    assert ou is not None and ou.get("ou") == [b"users"]
    assert d.get("uid=alice,ou=users,dc=heracles,dc=test") is not None
    assert len(list(d.search(new, scope=Scope.ONE))) == 2


def test_rename_new_superior_and_rdn_value_swap(d: MemoryDirectory) -> None:
    new = d.rename(
        "uid=alice,ou=people,dc=heracles,dc=test", "uid=alicia", "ou=groups,dc=heracles,dc=test"
    )
    assert new == "uid=alicia,ou=groups,dc=heracles,dc=test"
    e = d.get(new)
    assert e is not None and e.get("uid") == [b"alicia"]
    with pytest.raises(AlreadyExistsError):
        d.rename(
            "uid=bob,ou=people,dc=heracles,dc=test", "uid=alicia", "ou=groups,dc=heracles,dc=test"
        )
    with pytest.raises(NoSuchObjectError):
        d.rename("uid=bob,ou=people,dc=heracles,dc=test", "uid=b", "ou=nope,dc=heracles,dc=test")
    with pytest.raises(NoSuchObjectError):
        d.rename("uid=zz,ou=people,dc=heracles,dc=test", "uid=y")
    with pytest.raises(DirectoryError):
        d.rename("ou=people,dc=heracles,dc=test", "ou=p", "uid=bob,ou=people,dc=heracles,dc=test")


def test_check_password(d: MemoryDirectory) -> None:
    alice = "uid=alice,ou=people,dc=heracles,dc=test"
    bob = "uid=bob,ou=people,dc=heracles,dc=test"
    assert d.check_password(alice, "secret")  # plain userPassword
    assert not d.check_password(alice, "wrong")
    assert not d.check_password(alice, "")
    assert not d.check_password(bob, "anything")
    d.set_password(bob, "pw")
    assert d.check_password(bob, "pw")
    new = d.rename(bob, "uid=robert")
    assert d.check_password(new, "pw")
    assert not d.check_password("uid=ghost,dc=heracles,dc=test", "pw")


def test_schema_object_classes(d: MemoryDirectory) -> None:
    classes = d.schema_object_classes()
    assert "inetorgperson" in classes and all(c == c.lower() for c in classes)
    d.set_schema_object_classes(["Foo", "BAR"])
    assert d.schema_object_classes() == {"foo", "bar"}
    assert MemoryDirectory("dc=x", object_classes=["A"]).schema_object_classes() == {"a"}


def test_to_ldif_round_trip(d: MemoryDirectory) -> None:
    clone = MemoryDirectory.from_ldif(d.to_ldif())
    assert clone.dns() == d.dns()
    assert "uid=alice" in d.to_ldif("ou=people,dc=heracles,dc=test")
    assert "ou=groups" not in d.to_ldif("ou=people,dc=heracles,dc=test")


def test_escaped_comma_in_dn() -> None:
    d = MemoryDirectory("dc=x")
    d.add("dc=x", {"objectClass": [b"dcObject"]})
    d.add(r"cn=Doe\, John,dc=x", {"objectClass": [b"person"]})
    assert len(list(d.search("dc=x", scope=Scope.ONE))) == 1
    assert len(list(d.search("dc=x", r"(cn=Doe, John)"))) == 1
