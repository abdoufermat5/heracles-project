"""Object templates: stored presets with ``%attr%`` placeholders (see :mod:`masks`).

Storage (fixed, existing data must load): a template of type ``T`` is the entry
``cn=<name>,ou=templates,<T container rdn>,<department>``; its object classes
are ``top`` plus the template marker, and every attribute of the would-be object
(including the real ``objectClass`` values) is one value ``<attribute>:<value>``
of a multi-valued attribute (split on the first colon), sorted, empty values
omitted.

The three functions of the cross-stream contract take the
:class:`~heracles.objects.service.ObjectService` as ``ctx`` (it carries the
directory, the registry and the access policy of the current user):

* :func:`list_templates` -> :class:`TemplateInfo` list,
* :func:`template_fields` -> ``{tab: [attribute, ...]}`` the user must provide,
* :func:`apply_template` -> ``{tab: {attribute: json value}}`` ready for
  :meth:`ObjectService.create`. A tab is present when the template activates it
  (the main tab always) or the caller supplied values for it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from heracles.attributes import JSON, AnyAttribute, DepartmentAttr, DisplayAttr
from heracles.core.containers import ensure_container
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    AlreadyExistsError,
    DirectoryClient,
    Entry,
    Modification,
    NoSuchObjectError,
    Scope,
)
from heracles.objects import filters, masks
from heracles.objects.errors import (
    ObjectConflictError,
    ObjectNotFoundError,
    ObjectValidationError,
    PermissionDeniedError,
)
from heracles.objects.masks import CounterState, MaskEnv
from heracles.objects.model import Tab
from heracles.objects.registry import TypeInfo
from heracles.objects.service import ObjectService, department_of
from heracles.schema import legacy

_OBJECT_CLASS = "objectclass"
_MAX_UNIQUE_SUFFIX = 1000


@dataclass(frozen=True, slots=True)
class TemplateInfo:
    """A template in a listing."""

    dn: str
    name: str
    type_name: str
    #: Department the template lives in.
    base: str = ""

    def to_json(self) -> dict[str, JSON]:
        return {"dn": self.dn, "name": self.name, "type": self.type_name, "base": self.base}


@dataclass(slots=True)
class Template:
    """A loaded template: ``fields`` maps attribute names to raw (mask) values."""

    info: TemplateInfo
    fields: dict[str, list[str]] = field(default_factory=lambda: {})

    def values(self, name: str) -> list[str]:
        lname = name.lower()
        for key, vals in self.fields.items():
            if key.lower() == lname:
                return vals
        return []


# ------------------------------------------------------------------ helpers


def container_rdn(info: TypeInfo) -> str:
    """Template container RDNs below a department, e.g. ``ou=templates,ou=people``."""
    if not info.type.rdn:
        raise ObjectValidationError({"": _("This type does not support templates.")})
    return dnlib.join(legacy.TEMPLATES_RDN, info.type.rdn)


def supports_templates(info: TypeInfo) -> bool:
    return bool(info.type.rdn)


def _split_field(raw: str) -> tuple[str, str] | None:
    name, sep, value = raw.partition(":")
    return (name.strip(), value) if sep and name.strip() else None


def _encode_fields(fields: Mapping[str, Sequence[str]]) -> list[bytes]:
    out = {f"{name}:{value}" for name, values in fields.items() for value in values if value != ""}
    return [v.encode("utf-8") for v in sorted(out)]


def _read(info: TypeInfo, entry: Entry) -> Template:
    fields: dict[str, list[str]] = {}
    for raw in entry.texts(legacy.TEMPLATE_FIELD_ATTR):
        parsed = _split_field(raw)
        if parsed is not None:
            fields.setdefault(parsed[0], []).append(parsed[1])
    name = entry.text(legacy.STD_ATTR.CN) or dnlib.rdn(entry.dn).partition("=")[2]
    base = department_of(entry.dn, container_rdn(info))
    return Template(TemplateInfo(entry.dn, name, info.name, base), fields)


def _is_template_of(info: TypeInfo, dn: str) -> bool:
    parent = dnlib.parent(dn)
    if parent is None or not info.type.rdn:
        return False
    return dnlib.normalize(parent).startswith(dnlib.normalize(container_rdn(info)) + ",")


def _load(ctx: ObjectService, info: TypeInfo, dn: str) -> Template:
    entry = ctx.directory.get(dn)
    if (
        entry is None
        or not entry.has_object_class(legacy.OC.TEMPLATE)
        or not _is_template_of(info, entry.dn)
    ):
        raise ObjectNotFoundError(dn)
    return _read(info, entry)


def _require_manage(ctx: ObjectService, info: TypeInfo, base: str) -> None:
    if not ctx.policy.can_create(info.name, base):
        raise PermissionDeniedError(f"cannot manage {info.name} templates in {base}")


def _owners(info: TypeInfo) -> dict[str, tuple[type[Tab], AnyAttribute]]:
    """Lower-cased attribute name -> (tab, attribute) for storable attributes."""
    out: dict[str, tuple[type[Tab], AnyAttribute]] = {}
    for tab in info.tabs:
        for attr in tab.attributes():
            if isinstance(attr, DepartmentAttr) or not (
                attr.stored or isinstance(attr, DisplayAttr)
            ):
                continue
            out.setdefault(attr.name.lower(), (tab, attr))
    return out


def _tab_active(tab: type[Tab], fields: Mapping[str, Sequence[str]]) -> bool:
    if not tab.optional:
        return True
    classes = {v.lower() for k, vs in fields.items() if k.lower() == _OBJECT_CLASS for v in vs}
    return bool(tab.object_classes) and all(c.lower() in classes for c in tab.object_classes)


# ------------------------------------------------------------------ listing


def list_templates(
    ctx: ObjectService, type_name: str, base: str | None = None
) -> list[TemplateInfo]:
    """Templates of a type (below ``base``, default the whole directory).

    Only templates in departments where the user may create the type are listed.
    """
    info = ctx.registry.get(type_name)
    if not supports_templates(info):
        return []
    flt = filters.equals("objectClass", legacy.OC.TEMPLATE)
    try:
        entries = list(
            ctx.directory.search(
                base or ctx.directory.base_dn, flt, Scope.SUBTREE, [legacy.STD_ATTR.CN]
            )
        )
    except NoSuchObjectError:
        return []
    found = [_read(info, e).info for e in entries if _is_template_of(info, e.dn)]
    visible = [t for t in found if ctx.policy.can_create(type_name, t.base)]
    return sorted(visible, key=lambda t: (t.name.lower(), dnlib.normalize(t.dn)))


def get_template(ctx: ObjectService, type_name: str, dn: str) -> Template:
    """Load one template (requires create rights in its department)."""
    info = ctx.registry.get(type_name)
    tpl = _load(ctx, info, dn)
    _require_manage(ctx, info, tpl.info.base)
    return tpl


# --------------------------------------------------------------------- JSON


def _text_of(value: object) -> list[str]:
    """Free text values of a JSON value (templates store everything as text)."""
    if value is None:
        return []
    if isinstance(value, bool):
        return ["TRUE" if value else "FALSE"]
    if isinstance(value, str):
        return [value] if value != "" else []
    if isinstance(value, int | float):
        return [str(value)]
    if isinstance(value, list):
        out: list[str] = []
        for element in cast("list[object]", value):
            out.extend(_text_of(element))
        return out
    raise ValueError("expected text")


def template_json(ctx: ObjectService, tpl: Template) -> dict[str, JSON]:
    """``GET .../templates/{dn}``: the template with the descriptors' tab layout."""
    info = ctx.registry.get(tpl.info.type_name)
    owners = _owners(info)
    tabs: dict[str, JSON] = {}
    for tab in info.tabs:
        active = _tab_active(tab, tpl.fields)
        values: dict[str, JSON] = {}
        if active:
            for attr in tab.attributes():
                owner = owners.get(attr.name.lower())
                if owner is None or owner[0] is not tab:
                    continue
                raw = tpl.values(attr.name)
                if not raw:
                    continue
                values[attr.name] = cast("JSON", list(raw)) if attr.multivalued else raw[0]
        tabs[tab.name] = {"active": active, "values": values}
    return {**tpl.info.to_json(), "tabs": tabs}


def _check_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ObjectValidationError({"name": _("This field is required.")})
    cleaned = name.strip()
    if any(c in cleaned for c in ',+"\\<>;=\n'):
        raise ObjectValidationError({"name": _("Invalid format.")})
    return cleaned


def _apply_tabs(
    info: TypeInfo,
    fields: dict[str, list[str]],
    tabs_json: Mapping[str, Any],
) -> dict[str, list[str]]:
    """Merge a ``tabs`` payload into raw template fields (validating the masks)."""
    owners = _owners(info)
    errors: dict[str, str] = {}
    result = {k: list(v) for k, v in fields.items()}

    def remove(name: str) -> None:
        for key in [k for k in result if k.lower() == name.lower()]:
            del result[key]

    def set_values(name: str, values: list[str]) -> None:
        remove(name)
        if values:
            result[name] = values

    for tab_name, data in tabs_json.items():
        tab = info.tab(tab_name)
        if tab is None:
            errors[tab_name] = _("Unknown tab.")
            continue
        if not isinstance(data, Mapping):
            errors[tab_name] = _("Expected an object.")
            continue
        body = cast("Mapping[str, Any]", data)
        wanted = body.get("active", _tab_active(tab, result))
        if not isinstance(wanted, bool):
            errors[tab_name] = _("'active' must be a boolean.")
            continue
        if not tab.optional and not wanted:
            errors[tab_name] = _("This tab cannot be deactivated.")
            continue
        if not wanted and _tab_active(tab, result):
            for attr in tab.attributes():
                owner = owners.get(attr.name.lower())
                if owner is not None and owner[0] is tab:
                    remove(attr.name)
            kept = {
                c.lower()
                for t in info.tabs
                if t is not tab and _tab_active(t, result)
                for c in t.object_classes
            }
            current = result.get("objectClass", [])
            set_values(
                "objectClass",
                [
                    c
                    for c in current
                    if c.lower() not in {x.lower() for x in tab.object_classes} or c.lower() in kept
                ],
            )
        if wanted:
            current = result.get("objectClass", [])
            have = {c.lower() for c in current}
            set_values(
                "objectClass", [*current, *(c for c in tab.object_classes if c.lower() not in have)]
            )
        raw_values: object = body.get("values") or {}
        if not isinstance(raw_values, Mapping):
            errors[tab_name] = _("'values' must be an object.")
            continue
        values = cast("Mapping[str, Any]", raw_values)
        if values and not wanted:
            errors[tab_name] = _("The tab is not active.")
            continue
        for attr_name, raw in values.items():
            key = f"{tab_name}.{attr_name}"
            owner = owners.get(str(attr_name).lower())
            if owner is None or owner[0] is not tab:
                errors[key] = _("Unknown attribute.")
                continue
            try:
                texts = _text_of(raw)
            except ValueError:
                errors[key] = _("Expected text.")
                continue
            set_values(owner[1].name, texts)
    for name, values in result.items():
        if name.lower() == _OBJECT_CLASS:
            continue
        owner = owners.get(name.lower())
        key = f"{owner[0].name}.{owner[1].name}" if owner else name
        for raw in values:
            try:
                masks.references(raw)
            except masks.MaskError as exc:
                errors.setdefault(key, str(exc))
    if not errors:
        try:
            masks.resolution_order({k: v for k, v in result.items() if k.lower() != _OBJECT_CLASS})
        except masks.MaskCycleError as exc:
            first = exc.cycle[0]
            owner = owners.get(first)
            errors[f"{owner[0].name}.{owner[1].name}" if owner else first] = _(
                "Circular reference: {cycle}"
            ).format(cycle=" -> ".join(exc.cycle))
    if errors:
        raise ObjectValidationError(errors)
    return result


def _main_classes(info: TypeInfo, fields: dict[str, list[str]]) -> dict[str, list[str]]:
    have = {c.lower() for k, v in fields.items() if k.lower() == _OBJECT_CLASS for c in v}
    missing = [c for c in info.main_tab.object_classes if c.lower() not in have]
    if missing:
        fields["objectClass"] = [*fields.get("objectClass", []), *missing]
    return fields


# --------------------------------------------------------------------- CRUD


def template_dn(info: TypeInfo, base: str, name: str) -> str:
    # not dnlib.join for the RDN: it would strip an escaped trailing space
    return f"cn={dnlib.escape_rdn_value(name)},{dnlib.join(container_rdn(info), base)}"


def create_template(
    ctx: ObjectService, type_name: str, base: str, name: object, tabs_json: Mapping[str, Any]
) -> Template:
    """Create a template in department ``base``."""
    info = ctx.registry.get(type_name)
    if not supports_templates(info):
        raise ObjectValidationError({"": _("This type does not support templates.")})
    _require_manage(ctx, info, base)
    cleaned = _check_name(name)
    fields = _main_classes(info, _apply_tabs(info, {}, tabs_json))
    dn = template_dn(info, base, cleaned)
    ensure_container(ctx.directory, dnlib.join(container_rdn(info), base))
    attrs: dict[str, list[bytes]] = {
        "objectClass": [b"top", legacy.OC.TEMPLATE.encode()],
        legacy.STD_ATTR.CN: [cleaned.encode("utf-8")],
    }
    encoded = _encode_fields(fields)
    if encoded:
        attrs[legacy.TEMPLATE_FIELD_ATTR] = encoded
    try:
        ctx.directory.add(dn, attrs)
    except AlreadyExistsError:
        raise ObjectConflictError(f"{dn} already exists") from None
    return Template(TemplateInfo(dn, cleaned, type_name, base), fields)


def update_template(
    ctx: ObjectService,
    type_name: str,
    dn: str,
    tabs_json: Mapping[str, Any],
    name: object = None,
) -> Template:
    """Apply a PATCH-like change (only the given attributes) and/or rename."""
    info = ctx.registry.get(type_name)
    tpl = _load(ctx, info, dn)
    _require_manage(ctx, info, tpl.info.base)
    fields = _main_classes(info, _apply_tabs(info, tpl.fields, tabs_json))
    new_name = tpl.info.name if name is None else _check_name(name)
    new_dn = dn
    if new_name != tpl.info.name:
        try:
            new_dn = ctx.directory.rename(dn, f"cn={dnlib.escape_rdn_value(new_name)}")
        except AlreadyExistsError:
            raise ObjectConflictError(f"cn={new_name} already exists") from None
    if tpl.fields != fields:
        encoded = _encode_fields(fields)
        mod = (
            Modification("replace", legacy.TEMPLATE_FIELD_ATTR, encoded)
            if encoded
            else Modification("delete", legacy.TEMPLATE_FIELD_ATTR)
        )
        ctx.directory.modify(new_dn, [mod])
    return Template(TemplateInfo(new_dn, new_name, type_name, tpl.info.base), fields)


def delete_template(ctx: ObjectService, type_name: str, dn: str) -> None:
    info = ctx.registry.get(type_name)
    tpl = _load(ctx, info, dn)
    _require_manage(ctx, info, tpl.info.base)
    ctx.directory.delete(dn)


# ----------------------------------------------------------------- applying


def _definitions(tpl: Template) -> dict[str, list[str]]:
    return {k: v for k, v in tpl.fields.items() if k.lower() != _OBJECT_CLASS}


def template_fields(ctx: ObjectService, type_name: str, template_dn: str) -> dict[str, list[str]]:
    """Attributes the user must provide, by tab.

    Those referenced by a placeholder (without the ``c`` modifier) but not defined
    by the template, plus the required attributes the template leaves out.
    """
    info = ctx.registry.get(type_name)
    tpl = _load(ctx, info, template_dn)
    defs = _definitions(tpl)
    defined = {k.lower() for k in defs}
    owners = _owners(info)
    wanted = {n.lower() for n in masks.required_fields(defs)}
    out: dict[str, list[str]] = {}
    for tab in info.tabs:
        if not _tab_active(tab, tpl.fields):
            continue
        for attr in tab.attributes():
            key = attr.name.lower()
            owner = owners.get(key)
            if owner is None or owner[0] is not tab or isinstance(attr, DisplayAttr):
                continue
            if key in wanted or (attr.required and not attr.readonly and key not in defined):
                out.setdefault(tab.name, []).append(attr.name)
    # referenced names that no tab declares are still asked for, on the main tab
    for name in masks.required_fields(defs):
        if name.lower() not in owners:
            out.setdefault(info.main_tab.name, []).append(name)
    return out


def _json_texts(values: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for attrs in values.values():
        for name, value in attrs.items():
            try:
                texts = _text_of(value)
            except ValueError:
                continue
            if texts:
                out.setdefault(name, texts)
    return out


def _clean_supplied(values: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for tab, attrs in values.items():
        kept = {k: v for k, v in attrs.items() if v is not None and v != "" and v != []}
        if kept:
            out[tab] = kept
    return out


def _counters(directory: DirectoryClient) -> tuple[str, CounterState]:
    dn = dnlib.join(legacy.CONFIG_RDN, legacy.APP_OU, directory.base_dn)
    entry = directory.get(dn)
    states = entry.texts(legacy.INCREMENTAL_STATES_ATTR) if entry is not None else []
    return dn, CounterState.parse(states)


def _save_counters(directory: DirectoryClient, dn: str, state: CounterState) -> None:
    values = [v.encode("utf-8") for v in state.serialise()]
    if directory.get(dn, ["objectClass"]) is None:
        ensure_container(directory, dnlib.join(legacy.APP_OU, directory.base_dn))
        directory.add(
            dn,
            {
                "objectClass": [legacy.OC.MAIN_CONFIG.encode()],
                legacy.STD_ATTR.CN: [b"config"],
                legacy.INCREMENTAL_STATES_ATTR: values,
            },
        )
        return
    directory.modify(dn, [Modification("replace", legacy.INCREMENTAL_STATES_ATTR, values)])


def _exists(ctx: ObjectService, info: TypeInfo, value: str) -> bool:
    flt = filters.and_(info.type.filter, filters.equals(info.type.main_attr, value))
    try:
        for _entry in ctx.directory.search(
            ctx.directory.base_dn, flt, Scope.SUBTREE, [info.type.main_attr]
        ):
            return True
    except NoSuchObjectError:
        return False
    return False


def _json_of(attr: AnyAttribute, texts: list[str]) -> JSON:
    if attr.write_only:
        return texts[0]
    parsed = attr.from_ldap([t.encode("utf-8") for t in texts])
    if parsed is None:
        raise ValueError("invalid value")
    return attr.to_json(parsed)


def apply_template(
    ctx: ObjectService,
    type_name: str,
    template_dn: str,
    values: Mapping[str, Mapping[str, Any]],
    *,
    preview: bool = False,
) -> dict[str, dict[str, Any]]:
    """Resolve a template with the user supplied ``values`` (``{tab: {attr: json}}``).

    The user's values win over the template's definitions and are passed through
    unchanged. When the naming attribute is defined by the template and its
    resolved value is already used in the directory, the next candidate is
    tried (``t``/``s`` variants, in order), then the first candidate with a
    numeric suffix ``1``, ``2``, ... Incremental counters (``n`` modifier) are
    stored only when ``preview`` is false.
    """
    info = ctx.registry.get(type_name)
    tpl = _load(ctx, info, template_dn)
    owners = _owners(info)
    supplied = _clean_supplied(values)
    config_dn, counters = _counters(ctx.directory)
    env = MaskEnv(counter=counters.next)
    main_key = info.type.main_attr.lower()

    def choose(key: str, options: list[str]) -> str:
        if key != main_key:
            return options[0]
        for option in options:
            if not _exists(ctx, info, option):
                return option
        for n in range(1, _MAX_UNIQUE_SUFFIX):
            candidate = f"{options[0]}{n}"
            if not _exists(ctx, info, candidate):
                return candidate
        raise ObjectConflictError(f"no free {info.type.main_attr} value for {options[0]!r}")

    def field_key(attr: str) -> str:
        owner = owners.get(attr.lower())
        return f"{owner[0].name}.{owner[1].name}" if owner else attr

    given = {k.lower() for k in _json_texts(supplied)}
    absent = [n for n in masks.required_fields(_definitions(tpl)) if n.lower() not in given]
    if absent:
        raise ObjectValidationError({field_key(n): _("This field is required.") for n in absent})
    try:
        resolved = masks.resolve_definitions(_definitions(tpl), _json_texts(supplied), env, choose)
    except masks.MissingAttributeError as exc:
        raise ObjectValidationError({field_key(exc.attr): _("This field is required.")}) from exc
    except masks.MaskCycleError as exc:
        raise ObjectValidationError({field_key(exc.cycle[0]): str(exc)}) from exc
    except masks.MaskError as exc:
        raise ObjectValidationError({"template": str(exc)}) from exc

    result: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    for tab in info.tabs:
        if _tab_active(tab, tpl.fields) or tab.name in supplied:
            result[tab.name] = {}
    for key, texts in resolved.items():
        owner = owners.get(key)
        if owner is None or owner[0].name not in result:
            continue
        try:
            result[owner[0].name][owner[1].name] = _json_of(owner[1], texts)
        except ValueError:
            errors[f"{owner[0].name}.{owner[1].name}"] = _("Invalid format.")
    for tab_name, attrs in supplied.items():
        result.setdefault(tab_name, {}).update(attrs)
    if errors:
        raise ObjectValidationError(errors)
    if not preview and counters.pending:
        _save_counters(ctx.directory, config_dn, counters)
    return result


__all__ = [
    "Template",
    "TemplateInfo",
    "apply_template",
    "create_template",
    "delete_template",
    "get_template",
    "list_templates",
    "supports_templates",
    "template_fields",
    "template_json",
    "update_template",
]
