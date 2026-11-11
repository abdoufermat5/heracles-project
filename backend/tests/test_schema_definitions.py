"""The Heracles LDAP schema is consistent, complete and matches the shipped files."""

from __future__ import annotations

from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest

from heracles.schema import names as schema
from heracles.schema.definitions import ATTRIBUTE_TYPES, OBJECT_CLASSES
from heracles.schema.export import render_ldif, render_schema

SHIPPED = Path(__file__).resolve().parents[2] / "deploy" / "ldap" / "schema"
ATTRS = {a.name.lower(): a for a in ATTRIBUTE_TYPES}
CLASSES = {c.name.lower(): c for c in OBJECT_CLASSES}


def _plugins() -> list[Any]:
    loaded = [ep.load() for ep in entry_points(group="heracles.plugins")]
    return [p() if callable(p) else p for p in loaded]


def test_numbers_and_names_are_unique() -> None:
    assert len({a.number for a in ATTRIBUTE_TYPES}) == len(ATTRIBUTE_TYPES)
    assert len({c.number for c in OBJECT_CLASSES}) == len(OBJECT_CLASSES)
    names = [a.name.lower() for a in ATTRIBUTE_TYPES] + [c.name.lower() for c in OBJECT_CLASSES]
    assert len(set(names)) == len(names)


def test_every_name_has_the_heracles_prefix() -> None:
    for item in (*ATTRIBUTE_TYPES, *OBJECT_CLASSES):
        assert item.name.startswith("hrc"), item.name


def test_class_members_are_defined() -> None:
    for cls in OBJECT_CLASSES:
        for attr in (*cls.must, *cls.may):
            if attr.startswith("hrc"):
                assert attr.lower() in ATTRS, f"{cls.name}: {attr}"


def test_every_attribute_belongs_to_a_class() -> None:
    owned = {a.lower() for c in OBJECT_CLASSES for a in (*c.must, *c.may)}
    assert sorted(a.name for a in ATTRIBUTE_TYPES if a.name.lower() not in owned) == []


def test_core_names_are_defined() -> None:
    for name in schema.CORE_OBJECT_CLASSES:
        assert name.lower() in CLASSES, name
    for name in schema.CONFIG_ATTRS.values():
        assert name.lower() in ATTRS, name


def _allowed(classes: set[str]) -> set[str]:
    out: set[str] = set()
    for name in classes:
        cls = CLASSES.get(name.lower())
        if cls is not None:
            out |= {a.lower() for a in (*cls.must, *cls.may)}
    return out


@pytest.mark.parametrize("plugin", _plugins(), ids=lambda p: p.name)
def test_plugin_names_are_in_the_schema(plugin: Any) -> None:
    """Each stored ``hrc*`` attribute of a tab is allowed by a class on the entry."""
    tabs = [(ty.tabs[0], t) for ty in plugin.types for t in ty.tabs]
    tabs += [(None, att.tab) for att in plugin.tabs]
    for main, tab in tabs:
        for cls in tab.object_classes:
            if cls.startswith("hrc"):
                assert cls.lower() in CLASSES, f"{tab.name}: {cls}"
        carried: set[str] = set(tab.object_classes)
        if main is not None:
            carried |= set(main.object_classes)
        allowed = _allowed(carried)
        for attr in tab.attributes():
            if attr.stored and attr.name.startswith("hrc"):
                assert attr.name.lower() in ATTRS, f"{tab.name}: {attr.name}"
                assert attr.name.lower() in allowed, f"{tab.name}: {attr.name} not in {carried}"


def test_shipped_files_are_up_to_date() -> None:
    hint = "run: uv run heracles schema export -o ../deploy/ldap/schema/heracles.ldif"
    assert (SHIPPED / "heracles.ldif").read_text(encoding="utf-8") == render_ldif(), hint
    assert (SHIPPED / "heracles.schema").read_text(encoding="utf-8") == render_schema(), hint
