"""The v1 <-> Heracles name mapping layer, checked on every type of the demo application."""

from __future__ import annotations

import pytest

from heracles.api.domain import Domain
from heracles.api.v1.convert import from_v1, tabs_payload, to_v1
from heracles.api.v1.names import (
    find_attribute,
    find_tab,
    resolve_type,
    type_id,
    v1_tab_name,
    v1_tabs,
)
from heracles.objects import TypeInfo, TypeRegistry
from heracles.objects.errors import UnknownTypeError
from heracles.server import build_demo_app


@pytest.fixture(scope="module")
def registry() -> TypeRegistry:
    app = build_demo_app()
    domain: Domain = app.state.domain
    return domain.registry


def test_type_identifiers_are_unique_and_resolvable(registry: TypeRegistry) -> None:
    ids = [type_id(i) for i in registry.list()]
    assert len(ids) == len(set(ids))
    for info in registry.list():
        assert resolve_type(registry, type_id(info)) is info
        assert resolve_type(registry, type_id(info).lower()) is info
        assert resolve_type(registry, info.name) is info


def test_unknown_type(registry: TypeRegistry) -> None:
    with pytest.raises(UnknownTypeError):
        resolve_type(registry, "nope")


def test_legacy_type_identifiers(registry: TypeRegistry) -> None:
    assert type_id(registry.get("group")) == "OGROUP"
    assert type_id(registry.get("user")) == "USER"
    assert resolve_type(registry, "OGROUP").name == "group"


def test_tab_names_are_unique_and_bijective(registry: TypeRegistry) -> None:
    for info in registry.list():
        tabs = v1_tabs(info)
        names = [t.name.lower() for t in tabs]
        assert len(names) == len(set(names)), info.name
        for item in tabs:
            found = find_tab(info, item.name)
            assert found is not None and found.tab is item.tab, (info.name, item.name)
            assert v1_tab_name(info, item.tab.name) == item.name
        # the tab name is the ACL key, i.e. the second part of the ACL object
        main = info.acl_object(info.main_tab).partition("/")[2]
        assert tabs[0].name == main


def test_every_attribute_resolves_by_ldap_name(registry: TypeRegistry) -> None:
    for info in registry.list():
        for item in v1_tabs(info):
            for attr in item.tab.attributes():
                assert find_attribute(item.tab, attr.name) is attr
                assert find_attribute(item.tab, attr.name.upper()) is attr


def test_payload_roundtrip_on_every_type(registry: TypeRegistry) -> None:
    for info in registry.list():
        body: dict[str, dict[str, object]] = {item.name: {} for item in v1_tabs(info)}
        payload = tabs_payload(info, body)
        assert set(payload) == {t.name for t in info.tabs}


def _info(registry: TypeRegistry, name: str) -> TypeInfo:
    return registry.get(name)


def test_value_conversion(registry: TypeRegistry) -> None:
    info = _info(registry, "user")
    single = find_attribute(info.main_tab, "sn")
    assert single is not None
    assert from_v1(single, ["x"]) == "x" and from_v1(single, "x") == "x"
    assert from_v1(single, []) is None
    with pytest.raises(ValueError, match="single value"):
        from_v1(single, ["a", "b"])
    assert to_v1(single, None) == ""
    multi = find_attribute(_info(registry, "group").main_tab, "member")
    assert multi is not None
    assert from_v1(multi, "dn") == ["dn"] and to_v1(multi, None) == []
