from __future__ import annotations

from typing import Any

import pytest

from heracles.attributes import StringAttr
from heracles.objects import (
    ObjectType,
    Plugin,
    Section,
    Tab,
    TabAttachment,
    TypeRegistry,
    UnknownTypeError,
)
from heracles.objects.builtin import BUILTIN_TYPES, register_builtin_types
from tests.objects.conftest import PosixTab
from tests.objects.fakes import FakeDirectory


def test_dsl_collects_tabs_and_sections() -> None:
    class Thing(ObjectType):
        name = "thing"
        label = "Thing"
        main_attr = "cn"

        class Main(Tab):
            name = "main"
            first = Section("First", StringAttr("cn", "Name"))
            second = Section("Second", StringAttr("x", "X"))

        class Extra(Tab):
            name = "extra"
            optional = True
            object_classes = ("extraClass",)

    assert [t.name for t in Thing.tabs] == ["main", "extra"]
    assert [s.name for s in Thing.Main.sections] == ["first", "second"]
    assert Thing.Main.attribute("x") is not None
    assert Thing.Main.attribute("nope") is None


def test_dsl_rejects_bad_declarations() -> None:
    with pytest.raises(TypeError):

        class NoTab(ObjectType):  # pyright: ignore[reportUnusedClass]
            name = "x"

    with pytest.raises(TypeError):

        class BadOptional(Tab):  # pyright: ignore[reportUnusedClass]
            name = "t"
            optional = True


def test_register_and_describe_user(registry: TypeRegistry) -> None:
    desc = registry.describe("user")
    assert desc["name"] == "user"
    assert desc["main_attr"] == "uid" and desc["name_attr"] == "cn"
    assert desc["columns"] == [
        {"key": "uid", "label": "Login"},
        {"key": "cn", "label": "Name"},
        {"key": "mail", "label": "Email"},
    ]
    tabs: Any = desc["tabs"]
    assert [t["name"] for t in tabs] == ["main", "posix", "ssh"]
    assert [t["optional"] for t in tabs] == [False, True, True]
    sections = tabs[0]["sections"]
    assert [s["name"] for s in sections][:2] == ["identity", "contact"]
    names = {a["name"] for s in sections for a in s["attributes"]}
    assert {"sn", "givenName", "cn", "jpegPhoto", "uid", "userPassword", "base", "manager"} <= names
    pwd = next(a for s in sections for a in s["attributes"] if a["name"] == "userPassword")
    assert pwd["kind"] == "password"
    assert tabs[1]["sections"][0]["attributes"][2]["default"] == "/bin/bash"


def test_summaries_and_lookup(registry: TypeRegistry) -> None:
    summaries: Any = registry.summaries(lambda n: n != "role")
    assert {s["name"] for s in summaries} == {t.name for t in BUILTIN_TYPES}
    role = next(s for s in summaries if s["name"] == "role")
    assert role["can_create"] is False
    assert summaries[0] == {
        "name": "user",
        "label": "User",
        "label_plural": "Users",
        "icon": "user",
        "category": "directory",
        "can_create": True,
    }
    with pytest.raises(UnknownTypeError):
        registry.get("nope")


def test_duplicate_registration(registry: TypeRegistry) -> None:
    with pytest.raises(ValueError, match="already registered"):
        register_builtin_types(registry)
    with pytest.raises(ValueError, match="already on type"):
        registry.attach_tab("user", PosixTab)


def test_attach_does_not_mutate_class() -> None:
    reg = TypeRegistry()
    register_builtin_types(reg)
    reg.attach_tab("user", PosixTab)
    from heracles.objects.builtin import User

    assert len(User.tabs) == 1
    assert len(reg.get("user").tabs) == 2


def test_plugin_enabled_only_with_object_classes() -> None:
    plugin = Plugin(
        "posix",
        "1.0",
        tabs=[TabAttachment("user", PosixTab)],
        required_object_classes=("posixAccount", "shadowAccount"),
    )
    reg = TypeRegistry()
    register_builtin_types(reg)
    status = reg.register_plugin(plugin, {"posixaccount"})
    assert not status.enabled and status.missing_object_classes == ["shadowAccount"]
    assert len(reg.get("user").tabs) == 1

    status = reg.register_plugin(plugin, {"posixaccount", "shadowaccount"})
    assert status.enabled
    assert len(reg.get("user").tabs) == 2
    assert [p.enabled for p in reg.plugins] == [False, True]


class _EntryPoint:
    def __init__(self, name: str, obj: Any) -> None:
        self.name = name
        self._obj = obj

    def load(self) -> Any:
        return self._obj


def test_load_plugins_from_entry_points() -> None:
    class Printer(ObjectType):
        name = "printer"
        label = "Printer"
        main_attr = "cn"

        class Main(Tab):
            name = "main"
            s = Section("S", StringAttr("cn", "Name"))

    available = Plugin("printers", "0.1", types=[Printer], required_object_classes=("printer",))
    unavailable = Plugin("dns", "0.1", required_object_classes=("dNSZone",))
    reg = TypeRegistry()
    directory = FakeDirectory(classes={"printer", "inetOrgPerson"})
    statuses = reg.load_plugins(
        directory,
        [_EntryPoint("a", available), _EntryPoint("b", lambda: unavailable)],
    )
    assert [(s.name, s.enabled) for s in statuses] == [("printers", True), ("dns", False)]
    assert reg.get("printer").name == "printer"
