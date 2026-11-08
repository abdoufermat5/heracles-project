"""Value conversion between API v1 payloads and the API v2 object JSON."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from heracles.api.errors import ApiError, validation
from heracles.api.v1.names import find_attribute, find_tab
from heracles.attributes import JSON, AnyAttribute
from heracles.objects import TypeInfo


def to_v1(attr: AnyAttribute, value: JSON) -> JSON:
    """v2 JSON value -> v1 value: a list for multi-valued attributes, a scalar otherwise."""
    if attr.multivalued:
        if value is None:
            return []
        return cast("list[JSON]", value) if isinstance(value, list) else [value]
    if isinstance(value, list):
        items = cast("list[JSON]", value)
        return items[0] if len(items) == 1 else items
    return "" if value is None else value


def from_v1(attr: AnyAttribute, value: object) -> object:
    """v1 value -> v2 JSON value (scalars and one-element lists are interchangeable)."""
    if attr.multivalued:
        if value is None:
            return None
        return cast("list[object]", value) if isinstance(value, list) else [value]
    if isinstance(value, list):
        items = cast("list[object]", value)
        if not items:
            return None
        if len(items) == 1:
            return items[0]
        raise ValueError("this attribute accepts a single value")
    return value


def tabs_payload(
    info: TypeInfo, body: Mapping[str, Any], *, activate: bool = True
) -> dict[str, dict[str, Any]]:
    """v1 ``{tab: {attr: value}}`` -> v2 ``{tab: {"active": ..., "values": {...}}}``.

    Unknown tabs and attributes are reported as a 422 ``fields`` error keyed ``<tab>.<attr>``.
    """
    out: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for tab_name, values in body.items():
        found = find_tab(info, tab_name)
        if found is None:
            errors[tab_name] = "Unknown tab."
            continue
        if not isinstance(values, Mapping):
            errors[tab_name] = "Expected an object of attribute values."
            continue
        converted: dict[str, Any] = {}
        for attr_name, raw in values.items():  # pyright: ignore[reportUnknownVariableType]
            name = str(attr_name)  # pyright: ignore[reportUnknownArgumentType]
            attr = find_attribute(found.tab, name)
            key = f"{tab_name}.{name}"
            if attr is None:
                errors[key] = "Unknown attribute."
                continue
            try:
                converted[attr.name] = from_v1(attr, cast("object", raw))
            except ValueError as exc:
                errors[key] = str(exc)
        out[found.tab.name] = {"active": activate or not found.tab.optional, "values": converted}
    if errors:
        raise validation("Some fields are invalid", errors)
    return out


def bad_request(message: str) -> ApiError:
    return ApiError(400, "validation", message)
