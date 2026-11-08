"""Multiple edit: apply the same change to several objects of one type."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from heracles.attributes import JSON, AnyAttribute, DepartmentAttr, DisplayAttr, ListAttr
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import NoSuchObjectError
from heracles.objects.errors import (
    ObjectConflictError,
    ObjectNotFoundError,
    ObjectValidationError,
    PermissionDeniedError,
)
from heracles.objects.model import Tab
from heracles.objects.service import ObjectService

type Op = Literal["set", "add", "remove", "clear"]
OPS: tuple[Op, ...] = ("set", "add", "remove", "clear")
_EXCLUDED_KINDS = frozenset({"image", "file", "composite", "password", "display", "department"})


@dataclass(frozen=True, slots=True)
class BulkResult:
    """Outcome for one object."""

    dn: str
    ok: bool
    error: str | None = None
    code: str | None = None
    fields: Mapping[str, str] | None = None

    def to_json(self) -> dict[str, JSON]:
        out: dict[str, JSON] = {"dn": self.dn, "ok": self.ok}
        if self.error is not None:
            out["error"] = self.error
            out["code"] = self.code
        if self.fields:
            out["fields"] = dict(self.fields)
        return out


def is_bulk_editable(attr: AnyAttribute) -> bool:
    """Whether an attribute can be changed by a multiple edit."""
    if attr.readonly or attr.write_only or not attr.stored:
        return False
    if isinstance(attr, DisplayAttr | DepartmentAttr) or attr.kind in _EXCLUDED_KINDS:
        return False
    if isinstance(attr, ListAttr):
        item = cast("AnyAttribute", attr.item)  # pyright: ignore[reportUnknownMemberType]
        return item.kind not in _EXCLUDED_KINDS
    return True


def editable_attributes(
    service: ObjectService, type_name: str, dns: Sequence[str]
) -> dict[str, list[str]]:
    """``{tab: [attribute]}`` editable on every one of ``dns`` (active tab, write access)."""
    info = service.registry.get(type_name)
    states = [service.load(type_name, dn) for dn in dns]
    out: dict[str, list[str]] = {}
    for tab in info.tabs:
        if not states or not all(s.tabs[tab.name].active for s in states):
            continue
        names = [
            a.name
            for a in tab.attributes()
            if is_bulk_editable(a)
            and all(service.policy.can_write(s.dn, tab.name, a.name) for s in states)
        ]
        if names:
            out[tab.name] = names
    return out


def _same(a: object, b: object) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return a == b or ("=" in a and "=" in b and dnlib.normalize(a) == dnlib.normalize(b))
    return a == b


def _as_list(value: object) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(cast("list[Any]", value))
    return [value]


def new_value(attr: AnyAttribute, current: JSON, op: str, value: object) -> JSON:
    """The JSON value of ``attr`` after applying ``op`` to ``current``."""
    if op == "clear":
        return None
    if op == "set":
        return cast("JSON", value)
    wanted = _as_list(value)
    if not attr.multivalued:
        if op == "add":
            return cast("JSON", value)
        return None if any(_same(current, w) for w in wanted) else current
    existing = _as_list(current)
    if op == "add":
        merged = list(existing)
        for item in wanted:
            if not any(_same(item, e) for e in merged):
                merged.append(item)
        return cast("JSON", merged)
    kept = [e for e in existing if not any(_same(e, w) for w in wanted)]
    return cast("JSON", kept or None)


def bulk_update(
    service: ObjectService,
    type_name: str,
    dns: Sequence[str],
    changes: Mapping[str, Mapping[str, Mapping[str, Any]]],
    *,
    is_locked: Callable[[str], bool] | None = None,
) -> list[BulkResult]:
    """Apply ``changes`` (``{tab: {attr: {"op", "value"}}}``) to every DN; never aborts early."""
    info = service.registry.get(type_name)
    results: list[BulkResult] = []
    for dn in dns:
        try:
            if is_locked is not None and is_locked(dn):
                results.append(BulkResult(dn, False, _("Being edited by another user."), "locked"))
                continue
            state = service.load(type_name, dn)
            payload: dict[str, Any] = {}
            for tab_name, attrs in changes.items():
                tab: type[Tab] | None = info.tab(tab_name)
                if tab is None:
                    raise ObjectValidationError({tab_name: _("Unknown tab.")})
                if not state.tabs[tab_name].active:
                    raise ObjectValidationError({tab_name: _("The tab is not active.")})
                values: dict[str, Any] = {}
                for attr_name, change in attrs.items():
                    attr = tab.attribute(attr_name)
                    key = f"{tab_name}.{attr_name}"
                    op = change.get("op")
                    if attr is None or not is_bulk_editable(attr):
                        raise ObjectValidationError({key: _("This field cannot be edited here.")})
                    if op not in OPS:
                        raise ObjectValidationError({key: _("Unknown operation.")})
                    current = attr.to_json(state.tabs[tab_name].values.get(attr_name))
                    updated = new_value(attr, current, op, change.get("value"))
                    if updated != current:
                        values[attr_name] = updated
                if values:
                    payload[tab_name] = {"values": values}
            if payload:
                service.update(type_name, dn, payload)
            results.append(BulkResult(dn, True))
        except ObjectValidationError as exc:
            results.append(
                BulkResult(dn, False, _("Some fields are invalid"), "validation", exc.fields)
            )
        except PermissionDeniedError as exc:
            results.append(BulkResult(dn, False, str(exc), "forbidden"))
        except (ObjectNotFoundError, NoSuchObjectError):
            results.append(BulkResult(dn, False, _("Object not found."), "not_found"))
        except ObjectConflictError as exc:
            results.append(BulkResult(dn, False, str(exc), "conflict"))
    return results


__all__ = [
    "OPS",
    "BulkResult",
    "bulk_update",
    "editable_attributes",
    "is_bulk_editable",
    "new_value",
]
