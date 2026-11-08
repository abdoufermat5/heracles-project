from __future__ import annotations

from typing import Any

import pytest

from heracles.attributes import IntAttr, StringAttr
from heracles.core.containers import ensure_container
from heracles.ldap.client import Modification, Scope
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import (
    ObjectService,
    ObjectValidationError,
    PermissionDeniedError,
    Section,
    Tab,
    TypeRegistry,
)
from heracles.objects.builtin import register_builtin_types
from heracles.objects.errors import ObjectNotFoundError
from heracles.objects.templates import (
    apply_template,
    create_template,
    delete_template,
    get_template,
    list_templates,
    template_fields,
    template_json,
    update_template,
)
from heracles.schema import legacy

BASE = "dc=example,dc=com"
PARIS = f"ou=paris,{BASE}"
STAFF = f"cn=staff,ou=templates,ou=people,{BASE}"


class PosixTab(Tab):
    name = "posix"
    optional = True
    object_classes = ("posixAccount",)
    main = Section(
        "Unix",
        IntAttr("uidNumber", "UID number"),
        StringAttr("homeDirectory", "Home", required=True),
        StringAttr("loginShell", "Shell", default="/bin/bash"),
    )


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"dcObject", b"organization"], "dc": [b"example"], "o": [b"x"]})
    d.add(
        PARIS,
        {
            "objectClass": [b"organizationalUnit", legacy.OC.DEPARTMENT.encode()],
            "ou": [b"paris"],
            "description": [b"Paris"],
        },
    )
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    registry.attach_tab("user", PosixTab)
    return ObjectService(directory, registry)


STAFF_TABS: dict[str, Any] = {
    "main": {
        "values": {
            "uid": "%s[0,1]l|givenName%%l|sn%",
            "mail": "%uid%@example.org",
            "description": "Staff member",
            "employeeType": "staff",
        }
    },
    "posix": {
        "active": True,
        "values": {"homeDirectory": "/home/%uid%", "uidNumber": "%cn[uid,2000]|x%"},
    },
}


def make_staff(service: ObjectService, base: str = BASE) -> str:
    return create_template(service, "user", base, "staff", STAFF_TABS).info.dn


def test_create_template_storage_format(service: ObjectService, directory: MemoryDirectory) -> None:
    dn = make_staff(service)
    assert dn == STAFF
    entry = directory.get(dn)
    assert entry is not None
    assert entry.texts("objectClass") == ["top", legacy.OC.TEMPLATE]
    fields = entry.texts(legacy.TEMPLATE_FIELD_ATTR)
    assert fields == sorted(fields)
    assert "uid:%s[0,1]l|givenName%%l|sn%" in fields
    assert "objectClass:inetOrgPerson" in fields
    assert "objectClass:posixAccount" in fields
    assert "mail:%uid%@example.org" in fields
    assert directory.get(f"ou=templates,ou=people,{BASE}") is not None


def test_existing_entry_is_loaded_and_colons_survive(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    ensure_container(directory, f"ou=templates,ou=people,{BASE}")
    directory.add(
        STAFF,
        {
            "objectClass": [b"top", legacy.OC.TEMPLATE.encode()],
            "cn": [b"staff"],
            legacy.TEMPLATE_FIELD_ATTR: [
                b"objectClass:inetOrgPerson",
                b"objectClass:organizationalPerson",
                b"objectClass:person",
                b"description:a: b\nc",
                b"sn:%sn%",
            ],
        },
    )
    tpl = get_template(service, "user", STAFF)
    assert tpl.values("description") == ["a: b\nc"]
    body = template_json(service, tpl)
    assert body["name"] == "staff"
    assert body["tabs"]["main"]["values"]["description"] == "a: b\nc"  # type: ignore[index]
    assert body["tabs"]["posix"]["active"] is False  # type: ignore[index]


def test_templates_never_appear_in_listings(service: ObjectService) -> None:
    make_staff(service)
    page = service.list("user", BASE)
    assert page.total == 0
    assert service.list("user", BASE, scope=Scope.SUBTREE).total == 0


def test_list_update_delete(service: ObjectService, directory: MemoryDirectory) -> None:
    make_staff(service)
    create_template(
        service, "user", PARIS, "intern", {"main": {"values": {"employeeType": "intern"}}}
    )
    create_template(service, "group", BASE, "projects", {"main": {"values": {"description": "p"}}})
    names = [(t.name, t.base) for t in list_templates(service, "user")]
    assert names == [("intern", PARIS), ("staff", BASE)]
    assert [t.name for t in list_templates(service, "user", PARIS)] == ["intern"]
    assert [t.name for t in list_templates(service, "group")] == ["projects"]

    updated = update_template(
        service,
        "user",
        STAFF,
        {"main": {"values": {"employeeType": "", "o": "Acme"}}, "posix": {"active": False}},
    )
    assert updated.values("employeeType") == []
    assert updated.values("o") == ["Acme"]
    assert updated.values("homeDirectory") == []
    assert "posixAccount" not in updated.values("objectClass")
    renamed = update_template(service, "user", STAFF, {}, name="employees")
    assert renamed.info.dn == f"cn=employees,ou=templates,ou=people,{BASE}"
    assert directory.get(STAFF) is None
    delete_template(service, "user", renamed.info.dn)
    assert [t.name for t in list_templates(service, "user")] == ["intern"]
    with pytest.raises(ObjectNotFoundError):
        get_template(service, "user", renamed.info.dn)


def test_template_validation(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError) as exc:
        create_template(service, "user", BASE, "bad", {"main": {"values": {"uid": "50% off"}}})
    assert "main.uid" in exc.value.fields
    with pytest.raises(ObjectValidationError) as exc:
        create_template(
            service,
            "user",
            BASE,
            "loop",
            {"main": {"values": {"uid": "%mail%", "mail": "%uid%"}}},
        )
    assert any("Circular" in v for v in exc.value.fields.values())
    with pytest.raises(ObjectValidationError) as exc:
        create_template(service, "user", BASE, "x", {"main": {"values": {"nope": "1"}}})
    assert exc.value.fields == {"main.nope": "Unknown attribute."}
    with pytest.raises(ObjectValidationError):
        create_template(service, "user", BASE, " ", {})
    with pytest.raises(ObjectValidationError):
        create_template(service, "department", BASE, "t", {})


def test_template_fields(service: ObjectService) -> None:
    dn = make_staff(service)
    fields = template_fields(service, "user", dn)
    assert fields["main"] == ["sn", "givenName"]
    assert "posix" not in fields  # homeDirectory is defined by the template
    create_template(service, "user", BASE, "bare", {"main": {"values": {"o": "x"}}})
    bare = template_fields(service, "user", f"cn=bare,ou=templates,ou=people,{BASE}")
    assert bare == {"main": ["sn", "givenName", "uid"]}


def test_apply_template_resolves_and_creates(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = make_staff(service)
    values = {"main": {"givenName": "John", "sn": "Doe"}}
    resolved = apply_template(service, "user", dn, values)
    assert resolved["main"]["uid"] == "jdoe"
    assert resolved["main"]["mail"] == "jdoe@example.org"
    assert resolved["main"]["description"] == "Staff member"
    assert resolved["main"]["givenName"] == "John"
    assert resolved["posix"]["homeDirectory"] == "/home/jdoe"
    assert resolved["posix"]["uidNumber"] == 2000
    tabs = {name: {"active": True, "values": vals} for name, vals in resolved.items()}
    created = service.create("user", PARIS, tabs)
    assert created == f"uid=jdoe,ou=people,{PARIS}"
    state = service.load("user", created)
    assert state.tabs["posix"].active
    assert state.tabs["main"].values["cn"] == "John Doe"


def test_unique_naming_attribute_candidates(service: ObjectService) -> None:
    dn = create_template(
        service, "user", BASE, "u", {"main": {"values": {"uid": "%s[0,1-3]l|givenName%%l|sn%"}}}
    ).info.dn
    values = {"main": {"givenName": "John", "sn": "Doe"}}
    first = apply_template(service, "user", dn, values)["main"]["uid"]
    assert first == "jdoe"
    service.create(
        "user", BASE, {"main": {"values": {"uid": "jdoe", "sn": "Doe", "givenName": "J"}}}
    )
    assert apply_template(service, "user", dn, values)["main"]["uid"] == "jodoe"
    service.create(
        "user", BASE, {"main": {"values": {"uid": "jodoe", "sn": "Doe", "givenName": "Jo"}}}
    )
    service.create(
        "user", BASE, {"main": {"values": {"uid": "johdoe", "sn": "Doe", "givenName": "Joh"}}}
    )
    # every candidate is taken: numeric suffix on the first one
    assert apply_template(service, "user", dn, values)["main"]["uid"] == "jdoe1"


def test_user_values_override_and_missing_fields(service: ObjectService) -> None:
    dn = make_staff(service)
    out = apply_template(
        service, "user", dn, {"main": {"givenName": "A", "sn": "B", "uid": "custom", "mail": ""}}
    )
    assert out["main"]["uid"] == "custom"
    assert out["main"]["mail"] == "custom@example.org"
    with pytest.raises(ObjectValidationError) as exc:
        apply_template(service, "user", dn, {"main": {"sn": "Doe"}})
    assert exc.value.fields == {"main.givenName": "This field is required."}


def test_incremental_counter_is_persisted_only_on_commit(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = make_staff(service)
    values = {"main": {"givenName": "A", "sn": "B"}}
    cfg = f"cn=config,ou=fusiondirectory,{BASE}"
    preview = apply_template(service, "user", dn, values, preview=True)
    assert preview["posix"]["uidNumber"] == 2000
    assert directory.get(cfg) is None
    assert apply_template(service, "user", dn, values)["posix"]["uidNumber"] == 2000
    entry = directory.get(cfg)
    assert entry is not None
    assert entry.texts(legacy.INCREMENTAL_STATES_ATTR) == ["uid;2000"]
    assert apply_template(service, "user", dn, values)["posix"]["uidNumber"] == 2001
    directory.modify(cfg, [Modification("replace", legacy.INCREMENTAL_STATES_ATTR, [b"uid;5000"])])
    assert apply_template(service, "user", dn, values)["posix"]["uidNumber"] == 5001


class DenyAll:
    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        return True

    def can_write(self, dn: str, tab: str, attr: str) -> bool:
        return True

    def can_create(self, type_name: str, base: str) -> bool:
        return base == PARIS

    def can_delete(self, dn: str, type_name: str) -> bool:
        return True


def test_template_management_needs_create_rights(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    make_staff(service)
    restricted = ObjectService(directory, service.registry, policy=DenyAll())
    assert list_templates(restricted, "user") == []
    with pytest.raises(PermissionDeniedError):
        create_template(restricted, "user", BASE, "x", {})
    with pytest.raises(PermissionDeniedError):
        update_template(restricted, "user", STAFF, {})
    with pytest.raises(PermissionDeniedError):
        delete_template(restricted, "user", STAFF)
    create_template(restricted, "user", PARIS, "ok", {})
    assert [t.name for t in list_templates(restricted, "user")] == ["ok"]
