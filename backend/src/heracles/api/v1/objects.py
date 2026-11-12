"""v1 types and objects endpoints (search, CRUD on objects, tabs, attributes, values)."""

from __future__ import annotations

import base64
import importlib
from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, Query, Request, Response, status

from heracles.api.deps import CurrentUser
from heracles.api.domain import Domain, DomainDep, TypeAclPolicy
from heracles.api.errors import ApiError, forbidden, not_found
from heracles.api.v1.common import V1Route, V1UserDep
from heracles.api.v1.convert import bad_request, tabs_payload, to_v1
from heracles.api.v1.names import (
    V1Tab,
    filter_checks,
    find_attribute,
    find_tab,
    resolve_type,
    type_id,
    v1_tab_name,
    v1_tabs,
)
from heracles.api.v2.objects import locked_error, object_errors
from heracles.attributes import JSON, AnyAttribute
from heracles.ldap import dn as dnlib
from heracles.ldap.client import Entry, NoSuchObjectError, Scope
from heracles.ldap.filter import Filter, FilterError, filter_attributes, parse_filter
from heracles.objects import ObjectService, ObjectState, PermissionDeniedError, TypeInfo, filters

router = APIRouter(route_class=V1Route)

_SCOPES = {"base": Scope.BASE, "one": Scope.ONE, "onelevel": Scope.ONE}


# -- helpers ----------------------------------------------------------------------------------
def _info(domain: Domain, name: str) -> TypeInfo:
    with object_errors():
        return resolve_type(domain.registry, name)


def _tab(info: TypeInfo, name: str) -> V1Tab:
    found = find_tab(info, name)
    if found is None:
        raise not_found(f"Unknown tab: {name}")
    return found


def _ensure_unlocked(domain: Domain, user: CurrentUser, dn: str) -> None:
    lock = domain.locks(user.directory_id, user.directory).get(dn)
    if lock is not None and dnlib.normalize(lock.user_dn) != dnlib.normalize(user.dn):
        raise locked_error(lock)


def _load(
    domain: Domain, user: CurrentUser, info: TypeInfo, dn: str
) -> tuple[ObjectService, TypeAclPolicy, ObjectState]:
    with object_errors():
        service, policy = domain.service(user, info.name)
        state = service.load(info.name, dn)
        if not policy.can_read(dn, info.main_tab.name, ""):
            raise PermissionDeniedError(f"cannot read {dn}")
    return service, policy, state


def _templates() -> Any:
    try:
        return importlib.import_module("heracles.objects.templates")
    except ImportError:
        raise ApiError(501, "not_implemented", "Object templates are not available") from None


def _template_context(service: ObjectService) -> ObjectService:
    """What the template functions receive as ``ctx`` (the object service of the request)."""
    return service


def _update(
    domain: Domain, user: CurrentUser, info: TypeInfo, dn: str, payload: dict[str, Any]
) -> ObjectState:
    _ensure_unlocked(domain, user, dn)
    with object_errors():
        service, _policy = domain.service(user, info.name)
        state = service.update(info.name, dn, payload)
    if dnlib.normalize(state.dn) != dnlib.normalize(dn):
        domain.locks(user.directory_id, user.directory).release(dn, user.dn)
    return state


def _filter_checks(info: TypeInfo, flt: Filter) -> list[tuple[str, str]]:
    """See :func:`heracles.api.v1.names.filter_checks`; refuses with a 400."""
    try:
        return filter_checks(info, filter_attributes(flt))
    except ValueError as exc:
        raise bad_request(f"The attribute '{exc}' cannot be used in a filter") from None


# -- types ------------------------------------------------------------------------------------
@router.get("/types", tags=["types"], summary="List all types", operation_id="listTypes")
def list_types(user: V1UserDep, domain: DomainDep) -> dict[str, str]:
    del user
    return {type_id(i): i.type.label for i in domain.registry.list()}


@router.get(
    "/types/{type}",
    tags=["types"],
    summary="Get informations on a type",
    operation_id="getTypeInfo",
)
def get_type(type: str, user: V1UserDep, domain: DomainDep) -> dict[str, JSON]:
    del user
    info = _info(domain, type)
    rdn = info.type.rdn
    tabs = v1_tabs(info)
    return {
        "name": info.type.label,
        "description": info.type.label_plural or info.type.label,
        "mainAttr": info.type.main_attr,
        "nameAttr": info.type.name_attr,
        "icon": info.type.icon,
        "ou": f"{rdn}," if rdn else "",
        "mainTab": tabs[0].name,
        "templateActive": bool(rdn),
        "snapshotActive": True,
        "aclCategory": info.acl_category,
        "filter": info.type.filter,
        "management": info.type.category,
        "filterRDN": f"(ou:dn:={rdn.partition('=')[2]})" if rdn else "",
        "tabs": [{"class": t.name, "name": t.tab.display_label()} for t in tabs],
    }


@router.get(
    "/types/{type}/{tab}",
    tags=["types"],
    summary="Get informations on a tab",
    operation_id="getTabInfo",
)
def get_tab_info(type: str, tab: str, user: V1UserDep, domain: DomainDep) -> dict[str, JSON]:
    del user
    found = _tab(_info(domain, type), tab)
    sections: dict[str, JSON] = {}
    for section in found.tab.sections:
        sections[section.name] = {
            "name": section.label,
            "attrs": [a.name for a in section.attributes],
        }
    return {"sections": sections, "sections_order": [s.name for s in found.tab.sections]}


# -- search -----------------------------------------------------------------------------------
def _parse_attrs(request: Request) -> dict[str, str]:
    """The ``attrs[name]=mode`` deepObject query parameters."""
    out: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key.startswith("attrs[") and key.endswith("]") and len(key) > 7:
            out[key[6:-1]] = value
    return out


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _format_values(entry: Entry, name: str, mode: str) -> JSON:
    values = entry.get(name)
    if mode == "*":
        return [_text(v) for v in values]
    if mode == "b64":
        return [base64.b64encode(v).decode("ascii") for v in values]
    if mode == "raw":
        return [_text(v) for v in values]
    return _text(values[0]) if values else ""


@router.get(
    "/objects/{type}",
    tags=["objects"],
    summary="Search objects of specific type",
    operation_id="listObjects",
    openapi_extra={
        "parameters": [
            {
                "name": "attrs",
                "in": "query",
                "required": False,
                "style": "deepObject",
                "explode": True,
                "schema": {"type": "object"},
                "description": "Attributes to return: keys are attribute names, values are "
                "1 (single value), '*' (all values), 'b64' (base64 values) or 'raw'.",
            }
        ]
    },
)
def search_objects(
    type: str,
    request: Request,
    user: V1UserDep,
    domain: DomainDep,
    base: Annotated[str | None, Query(description="The LDAP base to use")] = None,
    filter: Annotated[str | None, Query(description="An LDAP filter to search with")] = None,
    scope: Annotated[str, Query(description="The scope, defaults to subtree")] = "subtree",
    templates: Annotated[bool, Query(description="Search templates instead of objects")] = False,
) -> dict[str, JSON]:
    info = _info(domain, type)
    search_base = base or user.directory.base_dn
    filter_checks: list[tuple[str, str]] = []
    if filter:
        try:
            parsed_filter = parse_filter(filter)
        except FilterError as exc:
            raise bad_request(f"Invalid filter: {exc}") from None
        filter_checks = _filter_checks(info, parsed_filter)
    if templates:
        module = _templates()
        with object_errors():
            service, _policy = domain.service(user, info.name)
            found = module.list_templates(_template_context(service), info.name)
        return {str(t.dn): str(t.name) for t in found}
    ldap_scope = _SCOPES.get(scope.lower(), Scope.SUBTREE)
    flt = filters.and_(info.type.filter, filter or "")
    wanted = _parse_attrs(request)
    fetch = list(dict.fromkeys([info.type.main_attr, info.type.name_attr, *wanted]))
    with object_errors():
        service, policy = domain.service(user, info.name)
    readable: dict[str, tuple[str, AnyAttribute]] = {}
    for name in wanted:
        for tab in info.tabs:
            attr = find_attribute(tab, name)
            if attr is not None:
                readable[name] = (tab.name, attr)
                break
    result: dict[str, JSON] = {}
    try:
        entries = list(user.directory.search(search_base, flt, ldap_scope, [a for a in fetch if a]))
    except NoSuchObjectError:
        entries = []
    for entry in entries:
        if not policy.can_read(entry.dn, info.main_tab.name, info.type.main_attr):
            continue
        if not all(policy.can_read(entry.dn, tab, attr) for tab, attr in filter_checks):
            continue
        if not wanted:
            result[entry.dn] = entry.text(info.type.name_attr) or ""
            continue
        row: dict[str, JSON] = {}
        for name, mode in wanted.items():
            target = readable.get(name)
            if target is None or target[1].write_only:
                continue
            if not policy.can_read(entry.dn, target[0], target[1].name):
                continue
            row[name] = _format_values(entry, name, mode)
        result[entry.dn] = row
    return result


# -- create / read / delete / patch -----------------------------------------------------------
@router.post(
    "/objects/{type}",
    tags=["objects"],
    status_code=status.HTTP_201_CREATED,
    summary="Create an object of specific type",
    operation_id="createObject",
)
def create_object(
    type: str,
    body: Annotated[dict[str, Any], Body()],
    user: V1UserDep,
    domain: DomainDep,
) -> str:
    info = _info(domain, type)
    attrs_raw: object = body.get("attrs")
    if not isinstance(attrs_raw, dict):
        raise bad_request("The 'attrs' field must be an object grouped by tab")
    attrs = cast("dict[str, Any]", attrs_raw)
    template: object = body.get("template")
    if template is not None and not isinstance(template, str):
        raise bad_request("The 'template' field must be a DN")
    payload = tabs_payload(info, attrs)
    with object_errors():
        service, _policy = domain.service(user, info.name)
        if template:
            module = _templates()
            values = {t: dict(p["values"]) for t, p in payload.items()}
            resolved = module.apply_template(
                _template_context(service), info.name, template, values
            )
            payload = {
                str(t): {"active": True, "values": dict(v)}
                for t, v in cast("dict[str, dict[str, Any]]", resolved).items()
            }
        base = user.directory.base_dn
        for tab in info.tabs:
            tab_values = cast("dict[str, Any]", payload.get(tab.name, {}).get("values", {}))
            department: object = tab_values.get("base")
            if isinstance(department, str) and department:
                base = department
        return service.create(info.name, base, payload)


@router.get(
    "/objects/{type}/{dn}/templatefields",
    tags=["objects"],
    summary="List fields asked to use a specific template",
    operation_id="getTemplateFields",
)
def template_fields(type: str, dn: str, user: V1UserDep, domain: DomainDep) -> dict[str, JSON]:
    info = _info(domain, type)
    module = _templates()
    with object_errors():
        service, _policy = domain.service(user, info.name)
        fields = module.template_fields(_template_context(service), info.name, dn)
    out: dict[str, JSON] = {}
    for tab_name, names in cast("dict[str, list[str]]", fields).items():
        out[v1_tab_name(info, tab_name)] = list(names)
    return out


@router.get(
    "/objects/{type}/{dn}",
    tags=["objects"],
    summary="List tabs of the object, with name and status",
    operation_id="listObjectTabs",
)
def list_object_tabs(type: str, dn: str, user: V1UserDep, domain: DomainDep) -> list[JSON]:
    info = _info(domain, type)
    _service, _policy, state = _load(domain, user, info, dn)
    return [
        {"class": t.name, "name": t.tab.display_label(), "active": state.tabs[t.tab.name].active}
        for t in v1_tabs(info)
    ]


@router.delete(
    "/objects/{type}/{dn}",
    tags=["objects"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the object",
    operation_id="deleteObject",
)
def delete_object(type: str, dn: str, user: V1UserDep, domain: DomainDep) -> Response:
    info = _info(domain, type)
    _ensure_unlocked(domain, user, dn)
    with object_errors():
        service, _policy = domain.service(user, info.name)
        service.delete(info.name, dn)
    domain.locks(user.directory_id, user.directory).release(dn, user.dn)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/objects/{type}/{dn}",
    tags=["objects"],
    summary="Set the object attributes",
    operation_id="modifyObject",
)
def modify_object(
    type: str,
    dn: str,
    body: Annotated[dict[str, Any], Body()],
    user: V1UserDep,
    domain: DomainDep,
) -> str:
    info = _info(domain, type)
    return _update(domain, user, info, dn, tabs_payload(info, body)).dn


# -- tabs -------------------------------------------------------------------------------------
@router.get(
    "/objects/{type}/{dn}/{tab}",
    tags=["attributes"],
    summary="Get attributes values from object specific tab",
    operation_id="getObjectTab",
)
def get_object_tab(
    type: str, dn: str, tab: str, user: V1UserDep, domain: DomainDep
) -> dict[str, JSON]:
    info = _info(domain, type)
    found = _tab(info, tab)
    _service, _policy, state = _load(domain, user, info, dn)
    tab_state = state.tabs[found.tab.name]
    if not tab_state.active:
        raise not_found(f"The tab {found.name} is not active")
    out: dict[str, JSON] = {}
    for attr in found.tab.attributes():
        if attr.write_only or attr.name not in tab_state.values:
            continue
        out[attr.name] = to_v1(attr, attr.to_json(tab_state.values[attr.name]))
    return out


@router.patch(
    "/objects/{type}/{dn}/{tab}",
    tags=["objects"],
    summary="Set the object attributes of a specific tab",
    operation_id="modifyObjectTab",
)
def modify_object_tab(
    type: str,
    dn: str,
    tab: str,
    body: Annotated[dict[str, Any], Body()],
    user: V1UserDep,
    domain: DomainDep,
) -> str:
    info = _info(domain, type)
    found = _tab(info, tab)
    return _update(domain, user, info, dn, tabs_payload(info, {found.name: body})).dn


@router.delete(
    "/objects/{type}/{dn}/{tab}",
    tags=["objects"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate the tab",
    operation_id="disableTab",
)
def disable_tab(type: str, dn: str, tab: str, user: V1UserDep, domain: DomainDep) -> Response:
    info = _info(domain, type)
    found = _tab(info, tab)
    _update(domain, user, info, dn, {found.tab.name: {"active": False, "values": {}}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# -- attributes -------------------------------------------------------------------------------
def _target(
    domain: Domain, user: CurrentUser, type_name: str, dn: str, tab: str, attribute: str
) -> tuple[TypeInfo, V1Tab, AnyAttribute, ObjectState, TypeAclPolicy]:
    info = _info(domain, type_name)
    found = _tab(info, tab)
    attr = find_attribute(found.tab, attribute)
    if attr is None:
        raise not_found(f"Unknown attribute: {attribute}")
    _service, policy, state = _load(domain, user, info, dn)
    return info, found, attr, state, policy


def _current(
    found: V1Tab, attr: AnyAttribute, state: ObjectState, policy: TypeAclPolicy, dn: str
) -> JSON:
    tab_state = state.tabs[found.tab.name]
    if not tab_state.active:
        raise not_found(f"The tab {found.name} is not active")
    if not policy.can_read(dn, found.tab.name, attr.name):
        raise forbidden(f"cannot read {attr.name}")
    if attr.write_only:
        return to_v1(attr, None)
    return to_v1(attr, attr.to_json(tab_state.values.get(attr.name)))


@router.get(
    "/objects/{type}/{dn}/{tab}/{attribute}",
    tags=["attributes"],
    summary="Get a single attribute value(s)",
    operation_id="getAttributeValues",
)
def get_attribute(
    type: str, dn: str, tab: str, attribute: str, user: V1UserDep, domain: DomainDep
) -> JSON:
    _, found, attr, state, policy = _target(domain, user, type, dn, tab, attribute)
    return _current(found, attr, state, policy, dn)


@router.put(
    "/objects/{type}/{dn}/{tab}/{attribute}",
    tags=["attributes"],
    summary="Set attribute value(s)",
    operation_id="setAttributeValues",
)
def set_attribute(
    type: str,
    dn: str,
    tab: str,
    attribute: str,
    body: Annotated[Any, Body()],
    user: V1UserDep,
    domain: DomainDep,
) -> str:
    info = _info(domain, type)
    found = _tab(info, tab)
    payload = tabs_payload(info, {found.name: {attribute: body}})
    return _update(domain, user, info, dn, payload).dn


@router.delete(
    "/objects/{type}/{dn}/{tab}/{attribute}",
    tags=["attributes"],
    summary="Reset the attribute to its default value",
    operation_id="resetAttributeValue",
)
def reset_attribute(
    type: str, dn: str, tab: str, attribute: str, user: V1UserDep, domain: DomainDep
) -> JSON:
    info, found, attr, _state, _policy = _target(domain, user, type, dn, tab, attribute)
    default = attr.to_json(attr.default)
    state = _update(
        domain, user, info, dn, {found.tab.name: {"active": True, "values": {attr.name: default}}}
    )
    service, policy = domain.service(user, info.name)
    del service
    return _current(found, attr, state, policy, state.dn)


def _multi_target(
    domain: Domain, user: CurrentUser, type_name: str, dn: str, tab: str, attribute: str
) -> tuple[TypeInfo, V1Tab, AnyAttribute, list[JSON]]:
    info, found, attr, state, policy = _target(domain, user, type_name, dn, tab, attribute)
    if not attr.multivalued:
        raise bad_request(f"{attr.name} is not a multi-valued attribute")
    current = _current(found, attr, state, policy, dn)
    return info, found, attr, list(current) if isinstance(current, list) else []


@router.patch(
    "/objects/{type}/{dn}/{tab}/{attribute}/values",
    tags=["multivaluated"],
    summary="Add attribute values. Only on multivaluated attributes.",
    operation_id="addAttributeValues",
)
def add_values(
    type: str,
    dn: str,
    tab: str,
    attribute: str,
    body: Annotated[list[Any], Body()],
    user: V1UserDep,
    domain: DomainDep,
) -> str:
    info, found, attr, current = _multi_target(domain, user, type, dn, tab, attribute)
    merged = [*current, *[v for v in body if v not in current]]
    payload = {found.tab.name: {"active": True, "values": {attr.name: merged}}}
    return _update(domain, user, info, dn, payload).dn


@router.delete(
    "/objects/{type}/{dn}/{tab}/{attribute}/values",
    tags=["multivaluated"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete attribute values. Only on multivaluated attributes.",
    operation_id="deleteAttributeValues",
)
def delete_values(
    type: str,
    dn: str,
    tab: str,
    attribute: str,
    body: Annotated[list[Any], Body()],
    user: V1UserDep,
    domain: DomainDep,
) -> Response:
    info, found, attr, current = _multi_target(domain, user, type, dn, tab, attribute)
    remaining = [v for v in current if v not in body]
    payload = {found.tab.name: {"active": True, "values": {attr.name: remaining}}}
    _update(domain, user, info, dn, payload)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
