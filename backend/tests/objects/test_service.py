from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from heracles.attributes import set_default_password_hasher
from heracles.ldap.client import Modification, Scope
from heracles.objects import (
    EventContext,
    NullEvents,
    ObjectConflictError,
    ObjectNotFoundError,
    ObjectService,
    ObjectValidationError,
    PermissionDeniedError,
    TypeRegistry,
)
from tests.objects.conftest import BASE, JDOE, PARIS, PARIS_PEOPLE, PEOPLE
from tests.objects.fakes import FakeDirectory


@pytest.fixture(autouse=True)
def hasher() -> Iterator[None]:
    set_default_password_hasher(lambda p: "{TEST}" + p)
    yield
    set_default_password_hasher(None)


def new_user(**values: Any) -> dict[str, Any]:
    base = {"sn": "Smith", "givenName": "Anna", "uid": "asmith"}
    return {"main": {"active": True, "values": {**base, **values}}}


# ---------------------------------------------------------------- load


def test_load(service: ObjectService, jdoe: str) -> None:
    state = service.load("user", jdoe)
    main = state.tabs["main"]
    assert main.active and not state.tabs["posix"].active
    assert main.values["uid"] == "jdoe"
    assert main.values["cn"] == "John Doe"
    assert main.values["userPassword"] is None
    assert main.values["base"] == BASE
    assert state.original["main"].values == main.values
    assert state.tabs["posix"].values == {}


def test_load_json(service: ObjectService, jdoe: str) -> None:
    js: Any = service.state_json(service.load("user", jdoe))
    assert js["dn"] == jdoe and js["type"] == "user"
    assert js["tabs"]["main"]["values"]["sn"] == "Doe"
    assert js["tabs"]["main"]["values"]["userPassword"] is None
    assert js["tabs"]["posix"] == {"active": False, "values": {}}


def test_load_errors(service: ObjectService, directory: FakeDirectory, jdoe: str) -> None:
    with pytest.raises(ObjectNotFoundError):
        service.load("user", f"uid=nobody,{PEOPLE}")
    with pytest.raises(ObjectNotFoundError):
        service.load("group", jdoe)  # not a groupOfNames


def test_load_department_of_nested(service: ObjectService, directory: FakeDirectory) -> None:
    dn = f"uid=p,{PARIS_PEOPLE}"
    directory.put(dn, objectClass=["inetOrgPerson", "organizationalPerson", "person"], uid="p")
    assert service.load("user", dn).tabs["main"].values["base"] == PARIS


# -------------------------------------------------------------- create


def test_create_user(service: ObjectService, directory: FakeDirectory) -> None:
    dn = service.create("user", BASE, new_user(userPassword="pw", mail="a@x.org"))
    assert dn == f"uid=asmith,{PEOPLE}"
    entry = directory.entries[dn.lower()]
    assert entry.attrs == {
        "objectClass": [b"inetOrgPerson", b"organizationalPerson", b"person"],
        "sn": [b"Smith"],
        "givenName": [b"Anna"],
        "cn": [b"Anna Smith"],
        "mail": [b"a@x.org"],
        "uid": [b"asmith"],
        "userPassword": [b"{TEST}pw"],
    }


def test_create_in_sub_department(service: ObjectService) -> None:
    dn = service.create("user", PARIS, new_user())
    assert dn == f"uid=asmith,{PARIS_PEOPLE}"


def test_create_with_optional_tab(service: ObjectService, directory: FakeDirectory) -> None:
    tabs = new_user()
    tabs["posix"] = {"active": True, "values": {"uidNumber": 1000, "homeDirectory": "/home/a"}}
    dn = service.create("user", BASE, tabs)
    attrs = directory.entries[dn.lower()].attrs
    assert attrs["objectClass"][-2:] == [b"posixAccount", b"shadowAccount"]
    assert attrs["uidNumber"] == [b"1000"]
    assert attrs["loginShell"] == [b"/bin/bash"]  # default applied


def test_create_rdn_escaping(service: ObjectService, directory: FakeDirectory) -> None:
    group = {"main": {"active": True, "values": {"cn": "a b ", "member": [JDOE_DN]}}}
    directory.put(JDOE_DN, objectClass=["inetOrgPerson", "organizationalPerson", "person"])
    dn = service.create("group", BASE, group)
    assert dn == f"cn=a b\\ ,ou=groups,{BASE}"


JDOE_DN = JDOE


def test_create_validation_errors(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        service.create(
            "user",
            BASE,
            {
                "main": {"values": {"sn": "", "uid": "bad uid", "mail": "x", "bogus": 1}},
                "nope": {},
            },
        )
    fields = exc.value.fields
    assert fields["main.sn"] == "This field is required."
    assert fields["main.givenName"] == "This field is required."
    assert fields["main.uid"] == "Invalid format."
    assert fields["main.mail"] == "Invalid email address."
    assert fields["main.bogus"] == "Unknown attribute."
    assert fields["nope"] == "Unknown tab."


def test_create_requires_tab_and_required_fields(service: ObjectService) -> None:
    tabs = new_user()
    tabs["ssh"] = {"active": True, "values": {}}
    with pytest.raises(ObjectValidationError) as exc:
        service.create("user", BASE, tabs)
    assert "ssh" in exc.value.fields

    tabs = new_user()
    tabs["posix"] = {"active": True, "values": {"uidNumber": -1}}
    with pytest.raises(ObjectValidationError) as exc:
        service.create("user", BASE, tabs)
    assert exc.value.fields["posix.uidNumber"] == "Must be at least 0."
    assert exc.value.fields["posix.homeDirectory"] == "This field is required."


def test_create_requires_main_active(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        service.create("user", BASE, {"main": {"active": False}})
    assert exc.value.fields["main"] == "The main tab cannot be deactivated."


def test_create_uniqueness(service: ObjectService, jdoe: str) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        service.create("user", BASE, new_user(uid="JDOE"))
    assert exc.value.fields == {"main.uid": "Already in use."}
    # uniqueness is scoped to the target department subtree
    service.create("user", PARIS, new_user(uid="jdoe"))


def test_create_reference_must_exist(service: ObjectService) -> None:
    group = {"main": {"values": {"cn": "devs", "member": [f"uid=ghost,{PEOPLE}"]}}}
    with pytest.raises(ObjectValidationError) as exc:
        service.create("group", BASE, group)
    assert "does not exist" in exc.value.fields["main.member"]


def test_create_group_and_role(service: ObjectService, directory: FakeDirectory, jdoe: str) -> None:
    gdn = service.create("group", BASE, {"main": {"values": {"cn": "devs", "member": [jdoe]}}})
    assert directory.entries[gdn.lower()].attrs["member"] == [jdoe.encode()]
    rdn = service.create("role", BASE, {"main": {"values": {"cn": "boss", "roleOccupant": [jdoe]}}})
    assert rdn == f"cn=boss,ou=roles,{BASE}" or rdn.startswith("cn=boss,ou=roles")


def test_create_department(service: ObjectService, directory: FakeDirectory) -> None:
    dn = service.create(
        "department", BASE, {"main": {"values": {"ou": "Lyon", "description": "Lyon office"}}}
    )
    assert dn == f"ou=Lyon,{BASE}"
    assert directory.entries[dn.lower()].attrs["objectClass"] == [
        b"organizationalUnit",
        b"gosaDepartment",
    ]
    with pytest.raises(ObjectValidationError):
        service.create("department_c", BASE, {"main": {"values": {"c": "FRA", "description": "x"}}})


def test_create_conflict(service: ObjectService, directory: FakeDirectory) -> None:
    directory.put(f"uid=asmith,{PEOPLE}", objectClass="x")  # uniqueness filter does not see it
    with pytest.raises(ObjectConflictError):
        service.create("user", BASE, new_user())


# -------------------------------------------------------------- update


def mods(directory: FakeDirectory) -> list[list[Modification]]:
    return directory.modifications()


def test_update_single_modify(service: ObjectService, directory: FakeDirectory, jdoe: str) -> None:
    state = service.update(
        "user",
        jdoe,
        {"main": {"values": {"sn": "Dupont", "mail": None, "telephoneNumber": "+33 1 23 45"}}},
    )
    assert mods(directory) == [
        [
            Modification("replace", "sn", [b"Dupont"]),
            Modification("replace", "cn", [b"John Dupont"]),
            Modification("delete", "mail"),
            Modification("replace", "telephoneNumber", [b"+33 1 23 45"]),
        ]
    ]
    assert state.tabs["main"].values["cn"] == "John Dupont"
    assert state.dn == jdoe


def test_update_noop(service: ObjectService, directory: FakeDirectory, jdoe: str) -> None:
    service.update("user", jdoe, {"main": {"values": {"sn": "Doe", "mail": "j@x.org"}}})
    service.update("user", jdoe, {})
    assert mods(directory) == []


def test_update_password(service: ObjectService, directory: FakeDirectory, jdoe: str) -> None:
    service.update("user", jdoe, {"main": {"values": {"userPassword": None}}})
    assert mods(directory) == []
    service.update("user", jdoe, {"main": {"values": {"userPassword": "new"}}})
    assert mods(directory)[-1] == [Modification("replace", "userPassword", [b"{TEST}new"])]
    service.update("user", jdoe, {"main": {"values": {"userPassword": ""}}})
    assert mods(directory)[-1] == [Modification("delete", "userPassword")]
    assert service.load("user", jdoe).tabs["main"].values["userPassword"] is None


def test_update_validation(service: ObjectService, directory: FakeDirectory, jdoe: str) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        service.update("user", jdoe, {"main": {"values": {"sn": None, "cn": "hack"}}})
    assert exc.value.fields == {"main.sn": "This field is required."}
    assert mods(directory) == []


def test_activate_tab(service: ObjectService, directory: FakeDirectory, jdoe: str) -> None:
    state = service.update(
        "user",
        jdoe,
        {"posix": {"active": True, "values": {"uidNumber": 1001, "homeDirectory": "/home/jdoe"}}},
    )
    assert mods(directory) == [
        [
            Modification("add", "objectClass", [b"posixAccount", b"shadowAccount"]),
            Modification("replace", "uidNumber", [b"1001"]),
            Modification("replace", "homeDirectory", [b"/home/jdoe"]),
            Modification("replace", "loginShell", [b"/bin/bash"]),
        ]
    ]
    assert state.tabs["posix"].active
    assert state.tabs["posix"].values["uidNumber"] == 1001


def test_activate_tab_missing_required(service: ObjectService, jdoe: str) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        service.update("user", jdoe, {"posix": {"active": True}})
    assert set(exc.value.fields) == {"posix.uidNumber", "posix.homeDirectory"}


def test_deactivate_tab(service: ObjectService, directory: FakeDirectory, jdoe: str) -> None:
    service.update(
        "user",
        jdoe,
        {"posix": {"active": True, "values": {"uidNumber": 1, "homeDirectory": "/h"}}},
    )
    directory.log.clear()
    state = service.update("user", jdoe, {"posix": {"active": False}})
    assert mods(directory) == [
        [
            Modification("delete", "uidNumber"),
            Modification("delete", "homeDirectory"),
            Modification("delete", "loginShell"),
            Modification("delete", "objectClass", [b"posixAccount", b"shadowAccount"]),
        ]
    ]
    assert not state.tabs["posix"].active and state.tabs["posix"].values == {}
    entry = directory.entries[jdoe.lower()]
    assert not entry.has_object_class("posixAccount")


def test_ssh_requires_posix(service: ObjectService, jdoe: str) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        service.update("user", jdoe, {"ssh": {"active": True, "values": {"sshPublicKey": "k"}}})
    assert exc.value.fields["ssh"] == "Requires the 'posix' tab."
    service.update(
        "user",
        jdoe,
        {
            "posix": {"active": True, "values": {"uidNumber": 1, "homeDirectory": "/h"}},
            "ssh": {"active": True, "values": {"sshPublicKey": "k"}},
        },
    )


def test_values_on_inactive_tab_rejected(service: ObjectService, jdoe: str) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        service.update("user", jdoe, {"posix": {"values": {"uidNumber": 1}}})
    assert exc.value.fields["posix"] == "The tab is not active."


def test_rename_on_main_attr_change(
    service: ObjectService, directory: FakeDirectory, jdoe: str
) -> None:
    state = service.update("user", jdoe, {"main": {"values": {"uid": "jdupont", "sn": "Dupont"}}})
    assert mods(directory) == [
        [
            Modification("replace", "sn", [b"Dupont"]),
            Modification("replace", "cn", [b"John Dupont"]),
        ]
    ]
    assert [e for e in directory.log if e[0] == "rename"] == [
        ("rename", (jdoe, "uid=jdupont", None))
    ]
    assert state.dn == f"uid=jdupont,{PEOPLE}"
    assert state.tabs["main"].values["uid"] == "jdupont"


def test_rename_conflict_detected(service: ObjectService, jdoe: str) -> None:
    service.create("user", BASE, new_user(uid="other"))
    with pytest.raises(ObjectValidationError) as exc:
        service.update("user", jdoe, {"main": {"values": {"uid": "other"}}})
    assert exc.value.fields == {"main.uid": "Already in use."}


def test_move_to_other_department(
    service: ObjectService, directory: FakeDirectory, jdoe: str
) -> None:
    state = service.update("user", jdoe, {"main": {"values": {"base": PARIS}}})
    assert mods(directory) == []
    assert [e for e in directory.log if e[0] == "rename"] == [
        ("rename", (jdoe, "uid=jdoe", PARIS_PEOPLE))
    ]
    assert state.dn == f"uid=jdoe,{PARIS_PEOPLE}"
    assert state.tabs["main"].values["base"] == PARIS


def test_move_and_rename_together(
    service: ObjectService, directory: FakeDirectory, jdoe: str
) -> None:
    state = service.update("user", jdoe, {"main": {"values": {"base": PARIS, "uid": "jd"}}})
    assert [e for e in directory.log if e[0] == "rename"] == [
        ("rename", (jdoe, "uid=jd", PARIS_PEOPLE))
    ]
    assert state.dn == f"uid=jd,{PARIS_PEOPLE}"


def test_update_unknown(service: ObjectService) -> None:
    with pytest.raises(ObjectNotFoundError):
        service.update("user", f"uid=none,{PEOPLE}", {})


# -------------------------------------------------------------- delete


def test_delete(service: ObjectService, directory: FakeDirectory, jdoe: str) -> None:
    service.delete("user", jdoe)
    assert jdoe.lower() not in directory.entries
    with pytest.raises(ObjectNotFoundError):
        service.delete("user", jdoe)


# -------------------------------------------------------------- events


class Recorder(NullEvents):
    def __init__(self) -> None:
        self.calls: list[tuple[str, EventContext]] = []

    def pre_create(self, ctx: EventContext) -> None:
        self.calls.append(("pre_create", ctx))

    def post_create(self, ctx: EventContext) -> None:
        self.calls.append(("post_create", ctx))

    def pre_modify(self, ctx: EventContext) -> None:
        self.calls.append(("pre_modify", ctx))

    def post_modify(self, ctx: EventContext) -> None:
        self.calls.append(("post_modify", ctx))

    def pre_delete(self, ctx: EventContext) -> None:
        self.calls.append(("pre_delete", ctx))

    def post_delete(self, ctx: EventContext) -> None:
        self.calls.append(("post_delete", ctx))


def test_events(directory: FakeDirectory, registry: TypeRegistry) -> None:
    rec = Recorder()
    service = ObjectService(directory, registry, events=rec)
    dn = service.create("user", BASE, new_user())
    service.update("user", dn, {"main": {"values": {"sn": "Other"}}})
    service.delete("user", dn)
    assert [c[0] for c in rec.calls] == [
        "pre_create",
        "post_create",
        "pre_modify",
        "post_modify",
        "pre_delete",
        "post_delete",
    ]
    pre_modify = rec.calls[2][1]
    assert pre_modify.before is not None and pre_modify.after is not None
    assert pre_modify.changes[0] == Modification("replace", "sn", [b"Other"])


def test_pre_event_can_veto(directory: FakeDirectory, registry: TypeRegistry) -> None:
    class Veto(NullEvents):
        def pre_create(self, ctx: EventContext) -> None:
            raise RuntimeError("no")

    service = ObjectService(directory, registry, events=Veto())
    with pytest.raises(RuntimeError):
        service.create("user", BASE, new_user())
    assert f"uid=asmith,{PEOPLE}".lower() not in directory.entries


# -------------------------------------------------------------- policy


class Policy:
    def __init__(
        self,
        *,
        read: set[str] | None = None,
        write: set[str] | None = None,
        create: bool = True,
        delete: bool = True,
    ) -> None:
        self.read, self.write, self.create, self.delete = read, write, create, delete

    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        return self.read is None or attr in self.read

    def can_write(self, dn: str, tab: str, attr: str) -> bool:
        return self.write is None or f"{tab}.{attr}" in self.write

    def can_create(self, type_name: str, base: str) -> bool:
        return self.create

    def can_delete(self, dn: str, type_name: str) -> bool:
        return self.delete


def test_policy_hides_unreadable(
    directory: FakeDirectory, registry: TypeRegistry, jdoe: str
) -> None:
    service = ObjectService(directory, registry, policy=Policy(read={"uid", "sn"}))
    state = service.load("user", jdoe)
    assert state.tabs["main"].values == {"uid": "jdoe", "sn": "Doe"}


def test_policy_denies(directory: FakeDirectory, registry: TypeRegistry, jdoe: str) -> None:
    service = ObjectService(
        directory, registry, policy=Policy(write={"main.sn"}, create=False, delete=False)
    )
    with pytest.raises(PermissionDeniedError):
        service.create("user", BASE, new_user())
    with pytest.raises(PermissionDeniedError):
        service.delete("user", jdoe)
    with pytest.raises(PermissionDeniedError):
        service.update("user", jdoe, {"main": {"values": {"mail": "z@x.org"}}})
    with pytest.raises(PermissionDeniedError):
        service.update(
            "user",
            jdoe,
            {"posix": {"active": True, "values": {"uidNumber": 1, "homeDirectory": "/h"}}},
        )
    assert mods(directory) == []
    service.update("user", jdoe, {"main": {"values": {"sn": "Ok"}}})
    assert len(mods(directory)) == 1


# -------------------------------------------------------------- listing


def seed_users(directory: FakeDirectory, n: int = 5) -> None:
    for i in range(n):
        directory.put(
            f"uid=u{i},{PEOPLE}",
            objectClass=["inetOrgPerson", "organizationalPerson", "person"],
            uid=f"u{i}",
            cn=f"User {i}",
            sn="User",
            mail=f"u{i}@x.org",
        )


def test_list_basic(service: ObjectService, directory: FakeDirectory) -> None:
    seed_users(directory)
    page = service.list("user", BASE)
    assert page.total == 5 and page.next_cursor is None
    assert page.items[0].values == {"uid": "u0", "cn": "User 0", "mail": "u0@x.org"}
    assert directory.searches[-1] == (PEOPLE, "(objectClass=inetOrgPerson)", Scope.ONE)
    assert page.to_json()["items"][0] == {  # type: ignore[index]
        "dn": f"uid=u0,{PEOPLE}",
        "values": {"uid": "u0", "cn": "User 0", "mail": "u0@x.org"},
        "locked": False,
    }


def test_list_paging_and_sort(service: ObjectService, directory: FakeDirectory) -> None:
    seed_users(directory)
    first = service.list("user", BASE, limit=2)
    assert [i.values["uid"] for i in first.items] == ["u0", "u1"]
    assert first.next_cursor
    second = service.list("user", BASE, limit=2, cursor=first.next_cursor)
    assert [i.values["uid"] for i in second.items] == ["u2", "u3"]
    last = service.list("user", BASE, limit=2, cursor=second.next_cursor)
    assert [i.values["uid"] for i in last.items] == ["u4"] and last.next_cursor is None
    desc = service.list("user", BASE, limit=1, descending=True)
    assert desc.items[0].values["uid"] == "u4"
    assert service.list("user", BASE, cursor="%%%").items[0].values["uid"] == "u0"


def test_list_query_filter(service: ObjectService, directory: FakeDirectory) -> None:
    seed_users(directory)
    page = service.list("user", BASE, query="user 3")
    assert [i.values["uid"] for i in page.items] == ["u3"]
    flt = directory.searches[-1][1]
    assert flt == (
        "(&(objectClass=inetOrgPerson)"
        "(&(|(uid=*user*)(cn=*user*)(sn=*user*)(givenName=*user*)(mail=*user*))"
        "(|(uid=*3*)(cn=*3*)(sn=*3*)(givenName=*3*)(mail=*3*))))"
    )


def test_list_query_escaping(service: ObjectService, directory: FakeDirectory) -> None:
    seed_users(directory)
    evil = "a*)(uid=*\\\x00"
    page = service.list("user", BASE, query=evil)
    assert not page.items
    flt = directory.searches[-1][1]
    assert "*)(uid=*" not in flt.replace("\\2a\\29\\28uid=\\2a", "")
    assert r"a\2a\29\28uid=\2a\5c\00" in flt
    assert flt.count("(") == flt.count(")")


def test_list_scope_sub_and_missing_container(
    service: ObjectService, directory: FakeDirectory
) -> None:
    seed_users(directory, 2)
    directory.put(
        f"uid=p1,{PARIS_PEOPLE}",
        objectClass=["inetOrgPerson", "organizationalPerson", "person"],
        uid="p1",
    )
    assert service.list("user", BASE, Scope.SUBTREE).total == 3
    assert service.list("user", PARIS).total == 1
    assert not service.list("user", f"ou=nowhere,{BASE}").items
    assert service.list("group", BASE).total == 0


def test_list_departments(service: ObjectService) -> None:
    page = service.list("department", BASE)
    assert [i.dn for i in page.items] == [PARIS]
    assert page.items[0].values == {"ou": "Paris", "description": "Paris office"}


def test_list_policy_filters_rows(directory: FakeDirectory, registry: TypeRegistry) -> None:
    seed_users(directory, 2)
    service = ObjectService(directory, registry, policy=Policy(read={"uid", "cn"}))
    page = service.list("user", BASE)
    assert page.items[0].values == {"uid": "u0", "cn": "User 0"}
    deny = ObjectService(directory, registry, policy=Policy(read={"cn"}))
    assert not deny.list("user", BASE).items
