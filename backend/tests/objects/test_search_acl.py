"""``q=`` never matches an attribute the caller cannot read (no search oracle)."""

from __future__ import annotations

from heracles.attributes import StringAttr
from heracles.ldap.client import Scope
from heracles.objects import AllowAll, ObjectService, ObjectType, Section, Tab, TypeRegistry
from tests.objects.conftest import BASE, PEOPLE
from tests.objects.fakes import FakeDirectory

USERS = {
    "uid=alice": ("Alice", "Doe", "alice@hidden.test"),
    "uid=bob": ("Bob", "Smith", "bob@visible.test"),
}


class Hidden(AllowAll):
    def __init__(self, *names: str) -> None:
        self.names = {n.lower() for n in names}

    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        return attr.lower() not in self.names


def _users(directory: FakeDirectory) -> None:
    for dn, (given, family, mail) in USERS.items():
        directory.put(
            f"{dn},{PEOPLE}",
            objectClass=["inetOrgPerson", "organizationalPerson", "person"],
            uid=dn.partition("=")[2],
            givenName=given,
            sn=family,
            cn=f"{given} {family}",
            mail=mail,
        )


def _rows(service: ObjectService, query: str) -> list[str]:
    page = service.list("user", BASE, Scope.SUBTREE, query=query)
    return [row.dn for row in page.items]


def test_query_ignores_an_unreadable_search_attribute(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    _users(directory)
    service = ObjectService(directory, registry, policy=Hidden("mail"))

    assert _rows(service, "hidden.test") == []
    assert [dn.partition(",")[0] for dn in _rows(service, "Alice")] == ["uid=alice"]


def test_query_cannot_see_anything_when_no_search_attribute_is_readable(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    _users(directory)
    service = ObjectService(
        directory, registry, policy=Hidden("uid", "cn", "sn", "givenName", "mail")
    )

    assert _rows(service, "Alice") == []


class Thing(ObjectType):
    name = "thing"
    label = "Thing"
    category = "directory"
    filter = "(objectClass=thing)"
    main_attr = "cn"
    name_attr = "cn"
    rdn = "ou=things"
    columns = ("cn",)
    search_attrs = ("description",)

    class Main(Tab):
        name = "main"
        label = "Thing"
        object_classes = ("thing",)
        main = Section(
            "Thing",
            StringAttr("cn", "Name", required=True),
            StringAttr("description", "Description"),
        )


def test_falls_back_to_the_rdn_attribute_when_it_is_readable(
    directory: FakeDirectory, registry: TypeRegistry
) -> None:
    things = f"ou=things,{BASE}"
    directory.put(things, objectClass=["organizationalUnit"], ou="things")
    directory.put(f"cn=alpha,{things}", objectClass=["thing"], cn="alpha", description="beta words")
    registry.register_type(Thing)
    service = ObjectService(directory, registry, policy=Hidden("description"))

    assert [dn.partition(",")[0] for dn in _rows_things(service, things, "alpha")] == ["cn=alpha"]
    assert _rows_things(service, things, "beta") == []


def _rows_things(service: ObjectService, base: str, query: str) -> list[str]:
    page = service.list("thing", base, Scope.SUBTREE, query=query)
    return [row.dn for row in page.items]
