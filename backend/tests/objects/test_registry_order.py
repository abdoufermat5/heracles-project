"""Plugins may extend types of other plugins whatever their load order."""

from __future__ import annotations

from heracles.attributes import StringAttr
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment, TypeRegistry


class _Gadget(ObjectType):
    name = "gadget"
    filter = "(objectClass=gadget)"
    main_attr = "cn"

    class Main(Tab):
        name = "main"
        object_classes = ("gadget",)
        props = Section("Props", StringAttr("cn", "Name"))


class _Extra(Tab):
    name = "extra"
    optional = True
    object_classes = ("gadgetExtra",)
    props = Section("Extra", StringAttr("extraValue", "Extra"))


EXTENDER = Plugin(name="a_extender", version="1", tabs=(TabAttachment("gadget", _Extra),))
PROVIDER = Plugin(name="z_provider", version="1", types=(_Gadget,))


def test_extender_loaded_before_provider() -> None:
    registry = TypeRegistry()
    registry.register_plugins([EXTENDER, PROVIDER], {"gadget", "gadgetextra"})
    assert registry.get("gadget").tab("extra") is not None


def test_tab_for_missing_type_is_skipped() -> None:
    registry = TypeRegistry()
    statuses = registry.register_plugins([EXTENDER], {"gadget", "gadgetextra"})
    assert statuses[0].enabled
    assert [t.name for t in registry.list()] == []
