"""Plugin activation: schema availability, the core profile, the yaml list, stored overrides."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from heracles.attributes import StringAttr
from heracles.objects import ObjectType, Plugin, Section, Tab, TabAttachment, TypeRegistry
from heracles.objects.activation import (
    CORE_PROFILE,
    PluginLockedError,
    PluginManager,
    PluginOverrideStore,
    UnavailablePluginError,
    UnknownPluginError,
)
from heracles.objects.builtin import User, register_builtin_types
from heracles.objects.registry import discover_plugins
from heracles.storage import Database


class Gizmo(ObjectType):
    name = "gizmo"
    filter = "(objectClass=gizmoAccount)"
    main_attr = "cn"

    class Main(Tab):
        name = "main"
        object_classes = ("gizmoAccount",)
        props = Section("Props", StringAttr("cn", "Name"))


class GizmoTab(Tab):
    name = "gizmo"
    optional = True
    object_classes = ("gizmoAccount",)
    props = Section("Gizmo", StringAttr("gizmoValue", "Gizmo"))


def _hook(_entry: Any, _locked: bool) -> list[Any]:
    return []


GIZMO = Plugin(
    "gizmo",
    "1.0",
    types=[Gizmo],
    tabs=[TabAttachment("user", GizmoTab)],
    required_object_classes=("gizmoAccount",),
    account_lock_hooks=[_hook],
    settings={"x": 1},
)
OTHER = Plugin("other", "1.0", required_object_classes=("otherClass",))
POSIX = Plugin("posix", "1.0", required_object_classes=("posixAccount",))
CORE = Plugin("acl_admin", "1.0")
SCHEMA = {"gizmoaccount", "posixaccount"}


def manager(configured: list[str] | None = None, store: PluginOverrideStore | None = None):
    return PluginManager([GIZMO, OTHER, POSIX, CORE], SCHEMA, configured=configured, store=store)


def fresh() -> TypeRegistry:
    reg = TypeRegistry()
    register_builtin_types(reg)
    return reg


@pytest.fixture
def small_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the suite-wide 'everything on' default and use a known small profile."""
    monkeypatch.setattr("heracles.objects.activation.CORE_PROFILE", ("posix", "acl_admin"))


def test_disabled_plugin_contributes_nothing() -> None:
    reg = fresh()
    (status,) = reg.register_plugins([GIZMO], SCHEMA, enabled_names=[])
    assert status.available and not status.enabled
    assert status.missing_object_classes == []
    assert "gizmo" not in [t.name for t in reg.list()]
    assert len(reg.get("user").tabs) == len(User.tabs)
    assert reg.account_lock_hooks == [] and "gizmo" not in reg.settings
    assert reg.events_factories == [] and reg.api_router_factories == []


def test_enabled_plugin_contributes() -> None:
    reg = fresh()
    reg.register_plugins([GIZMO], SCHEMA, enabled_names=["gizmo"])
    assert reg.get("gizmo")
    assert reg.account_lock_hooks and reg.settings["gizmo"] == {"x": 1}


def test_unavailable_is_never_enabled() -> None:
    (status,) = fresh().register_plugins([OTHER], SCHEMA, enabled_names=["other"])
    assert not status.available and not status.enabled
    assert status.missing_object_classes == ["otherClass"]


def test_default_profile_when_key_absent(small_profile: None) -> None:
    m = manager(None)
    assert m.enabled_names() == {"posix", "acl_admin"}
    assert m.is_enabled("posix") and not m.is_enabled("gizmo")
    statuses = {s.name: s for s in m.build_registry().plugins}
    assert statuses["posix"].enabled
    assert not statuses["gizmo"].enabled and statuses["gizmo"].available


def test_real_core_profile_content() -> None:
    assert set(CORE_PROFILE) == {"posix", "ssh", "sudo", "mail", "audit", "acl_admin", "ppolicy"}


def test_profile_only_enables_available(small_profile: None) -> None:
    assert not manager(None).is_enabled("other")


def test_yaml_list_replaces_profile(small_profile: None) -> None:
    m = manager(["gizmo"])
    assert m.is_enabled("gizmo") and not m.is_enabled("posix")
    assert m.is_enabled("acl_admin")  # locked
    assert "gizmo" in {t.name for t in m.build_registry().list()}


def test_wildcard() -> None:
    m = manager(["*"])
    assert m.is_enabled("gizmo") and m.is_enabled("posix") and not m.is_enabled("other")


def test_unknown_names_warn_not_crash(capsys: pytest.CaptureFixture[str]) -> None:
    m = manager(["nonexistent", "gizmo"])
    assert m.is_enabled("gizmo")
    captured = capsys.readouterr()
    assert "plugin_unknown" in captured.out + captured.err


def test_override_precedence_in_database(tmp_path: Path, small_profile: None) -> None:
    db = Database(tmp_path / "app.db")
    m = manager(["posix"], PluginOverrideStore(db))
    assert not m.is_enabled("gizmo") and m.is_enabled("posix")
    m.set_enabled("gizmo", True)
    m.set_enabled("posix", False)
    assert m.is_enabled("gizmo") and not m.is_enabled("posix")
    # a new process sees the stored choice over the yaml list
    again = manager(["posix"], PluginOverrideStore(Database(tmp_path / "app.db")))
    assert again.is_enabled("gizmo") and not again.is_enabled("posix")
    again.set_enabled("posix", True)
    assert manager(["posix"], PluginOverrideStore(db)).is_enabled("posix")


def test_set_enabled_returns_rebuilt_registry(small_profile: None) -> None:
    m = manager([])
    assert "gizmo" not in {t.name for t in m.build_registry().list()}
    assert "gizmo" in {t.name for t in m.set_enabled("gizmo", True).list()}
    assert "gizmo" not in {t.name for t in m.set_enabled("gizmo", False).list()}


def test_set_enabled_errors() -> None:
    m = manager([])
    with pytest.raises(UnknownPluginError):
        m.set_enabled("nope", True)
    with pytest.raises(UnavailablePluginError):
        m.set_enabled("other", True)
    with pytest.raises(PluginLockedError):
        m.set_enabled("acl_admin", False)


def test_discover_plugins_reads_entry_points() -> None:
    assert "posix" in {p.name for p in discover_plugins()}
