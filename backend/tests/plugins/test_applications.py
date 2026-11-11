"""Applications plugin: types, flags, role tab, allowed applications."""

from __future__ import annotations

import base64

import pytest

import heracles_plugins.applications as apps
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles_plugins.applications import allowed_applications, decode_flags, encode_flags

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
ROLES = f"ou=roles,{BASE}"
USER = f"uid=jdoe,{PEOPLE}"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    d.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
    d.add(ROLES, {"objectClass": [b"organizationalUnit"], "ou": [b"roles"]})
    d.add(
        USER,
        {
            "objectClass": [b"inetOrgPerson", b"organizationalPerson", b"person"],
            "uid": [b"jdoe"],
            "cn": [b"John Doe"],
            "sn": [b"Doe"],
        },
    )
    d.set_schema_object_classes(
        [
            *d.schema_object_classes(),
            "hrcDesktopApplication",
            "hrcWebApplication",
            "hrcApplicationRights",
        ]
    )
    return d


@pytest.fixture
def service(directory: MemoryDirectory) -> ObjectService:
    registry = TypeRegistry()
    register_builtin_types(registry)
    status = registry.register_plugin(
        apps.plugin(), {c.lower() for c in directory.schema_object_classes()}
    )
    assert status.enabled
    return ObjectService(directory, registry)


def new_app(service: ObjectService, cn: str = "terminal", **extra: object) -> str:
    return service.create(
        "application",
        BASE,
        {"main": {"values": {"cn": cn, "hrcApplicationExecutePath": "xterm", **extra}}},
    )


def new_web(service: ObjectService, cn: str = "wiki", **extra: object) -> str:
    return service.create(
        "web_application",
        BASE,
        {"main": {"values": {"cn": cn, "labeledURI": "https://wiki.example.com/", **extra}}},
    )


def new_role(service: ObjectService, allowed: list[str], occupants: list[str]) -> str:
    return service.create(
        "role",
        BASE,
        {
            "main": {"values": {"cn": "staff", "roleOccupant": occupants}},
            "applications": {"active": True, "values": {"hrcApplicationAllowed": allowed}},
        },
    )


def test_flags_roundtrip() -> None:
    assert encode_flags({"flag_group": True, "flag_menu": True, "flag_desktop": False}) == "[GM]"
    assert decode_flags("gm") == {
        "flag_group": True,
        "flag_overwrite": False,
        "flag_desktop": False,
        "flag_menu": True,
        "flag_launchbar": False,
    }


def test_acl_keys_and_containers(service: ObjectService) -> None:
    registry = service.registry
    app = registry.get("application")
    web = registry.get("web_application")
    role = registry.get("role")
    assert app.acl_object(app.main_tab) == "application/application"
    assert web.acl_object(web.main_tab) == "webApplication/webApplication"
    assert (app.type.rdn, web.type.rdn) == ("ou=apps", "ou=apps")
    tab = role.tab("applications")
    assert tab is not None and role.acl_object(tab) == "role/applicationRights"


def test_application_flags_are_stored_and_loaded(
    service: ObjectService, directory: MemoryDirectory
) -> None:
    dn = new_app(
        service,
        flag_menu=True,
        flag_launchbar=True,
        hrcApplicationImage="data:image/png;base64," + base64.b64encode(PNG).decode(),
    )
    assert dn == f"cn=terminal,ou=apps,{BASE}"
    entry = directory.get(dn) or pytest.fail()
    assert entry.text("hrcApplicationFlags") == "[ML]"
    assert entry.first("hrcApplicationImage") == PNG
    values = service.load("application", dn).tabs["main"].values
    assert values["flag_menu"] is True and values["flag_group"] is False
    service.update("application", dn, {"main": {"values": {"flag_menu": False}}})
    reloaded = service.load("application", dn).tabs["main"].values
    assert reloaded["flag_menu"] is False and reloaded["flag_launchbar"] is True


def test_web_application_requires_an_address(service: ObjectService) -> None:
    with pytest.raises(ObjectValidationError):
        service.create("web_application", BASE, {"main": {"values": {"cn": "wiki"}}})
    with pytest.raises(ObjectValidationError):
        new_web(service, labeledURI="not a url")


def test_role_tab_checks_the_applications(service: ObjectService) -> None:
    web = new_web(service)
    with pytest.raises(ObjectValidationError) as err:
        new_role(service, [USER], [USER])
    assert "applications.hrcApplicationAllowed" in err.value.fields
    dn = new_role(service, [web, web], [USER])
    loaded = service.load("role", dn).tabs["applications"].values
    assert loaded["hrcApplicationAllowed"] == [web]


def test_allowed_applications_through_roles(service: ObjectService) -> None:
    desktop = new_app(service, "terminal", hrcApplicationTitle="Terminal", flag_menu=True)
    web = new_web(service, "wiki", hrcApplicationTitle="Company wiki")
    unused = new_web(service, "other")
    new_role(service, [web, desktop], [USER])
    result = allowed_applications(service.directory, USER)
    assert [a["title"] for a in result] == ["Company wiki", "Terminal"]
    by_name = {a["name"]: a for a in result}
    assert by_name["wiki"]["type"] == "web_application"
    assert by_name["wiki"]["url"] == "https://wiki.example.com/"
    assert by_name["terminal"]["flags"]["flag_menu"] is True
    assert unused not in {a["dn"] for a in result}
    assert allowed_applications(service.directory, f"uid=nobody,{PEOPLE}") == []


def test_plugin_registers_without_the_role_class() -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {"hrcDesktopApplication".lower(), "hrcWebApplication".lower(), "organizationalrole"}
    registry.register_plugin(apps.plugin(), classes)
    role = registry.get("role")
    assert role.tab("applications") is None


def test_flags_brackets_and_unknown_letters() -> None:
    assert decode_flags("[GD]")["flag_desktop"] is True
    assert encode_flags({"flag_group": True}, previous="[GXZ]") == "[GXZ]"
    assert encode_flags({}) == "[]"
