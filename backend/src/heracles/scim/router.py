"""The HTTP surface of the SCIM endpoint (``/scim/v2``, RFC 7644).

Authentication is by API token only (``Authorization: Bearer hrc_...``): the session cookie
is never looked at, which is what makes the router safe outside the CSRF-protected API. The
token's scope and object types are enforced by :mod:`heracles.api.tokens` (rules for
``/scim/v2``). Every error, whatever raised it, is answered as a SCIM ``Error`` message.

The service is obtained through the :func:`get_scim_service` dependency (one per request);
tests replace it with ``app.dependency_overrides``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, cast

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

from heracles.api import tokens
from heracles.api.deps import CurrentUser, StateDep
from heracles.api.domain import DomainDep
from heracles.api.errors import ApiError
from heracles.api.hosts import request_base
from heracles.api.middleware import bearer_value
from heracles.ldap.client import DirectoryError, DirectoryUnavailableError
from heracles.scim import discovery
from heracles.scim import filter as scim_filter
from heracles.scim import patch as scim_patch
from heracles.scim import projection as scim_projection
from heracles.scim.errors import (
    INVALID_SYNTAX,
    INVALID_VALUE,
    ScimError,
    bad_request,
    not_found,
)
from heracles.scim.schemas import LIST_RESPONSE, SCIM_MEDIA_TYPE, SEARCH_REQUEST
from heracles.scim.service import Page, ResourceOps, ScimService
from heracles.scim.settings import ScimSettings

log = structlog.get_logger(__name__)

PREFIX = "/scim/v2"


class ScimJSONResponse(JSONResponse):
    media_type = SCIM_MEDIA_TYPE


def _json(
    payload: Any, status: int = 200, headers: dict[str, str] | None = None
) -> ScimJSONResponse:
    out = ScimJSONResponse(payload, status_code=status, headers=headers)
    out.headers["Cache-Control"] = "no-store"
    return out


def error_response(exc: Exception) -> Response:
    """The SCIM ``Error`` message for any exception raised while handling a request."""
    headers: dict[str, str] = {}
    err: ScimError
    if isinstance(exc, ScimError):
        err = exc
    elif isinstance(exc, ApiError):
        err = ScimError(exc.status, exc.message)
        headers.update(exc.headers or {})
    elif isinstance(exc, RequestValidationError):
        parts: list[str] = []
        for item in exc.errors():
            loc = ".".join(str(p) for p in item["loc"] if p not in ("body", "query", "path"))
            parts.append(f"{loc}: {item['msg']}" if loc else str(item["msg"]))
        err = bad_request("Invalid request: " + "; ".join(parts), INVALID_VALUE)
    elif isinstance(exc, StarletteHTTPException):
        err = ScimError(exc.status_code, str(exc.detail))
        headers.update(exc.headers or {})
    elif isinstance(exc, DirectoryUnavailableError):
        log.warning("scim_directory_unavailable", error=str(exc))
        err = ScimError(503, "The directory is unavailable, try again shortly")
        headers["Retry-After"] = "5"
    elif isinstance(exc, DirectoryError):
        log.warning("scim_directory_error", error=type(exc).__name__, detail=str(exc)[:500])
        err = ScimError(502, "The directory server reported an error")
    else:
        log.error("scim_unhandled_exception", exc_info=exc)
        err = ScimError(500, "Internal server error")
    if err.status == 401:
        headers.setdefault("WWW-Authenticate", "Bearer")
    return _json(err.body(), err.status, headers)


class ScimRoute(APIRoute):
    """Route turning every error into a SCIM ``Error`` message."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except Exception as exc:
                return error_response(exc)

        return handler


# -- dependencies ---------------------------------------------------------------------------------
def scim_enabled(state: StateDep) -> None:
    if not state.settings.scim.enabled:
        raise not_found("The SCIM endpoint is disabled")


def scim_user(
    request: Request, state: StateDep, _enabled: Annotated[None, Depends(scim_enabled)]
) -> CurrentUser:
    """The owner of the request's API token. Nothing else authenticates here."""
    if bearer_value(request) is None:
        raise ScimError(401, "An API token is required (Authorization: Bearer hrc_...)")
    return tokens.authenticate(request, state)


UserDep = Annotated[CurrentUser, Depends(scim_user)]


def scim_base_url(request: Request, state: StateDep) -> str:
    """Absolute URL of ``/scim/v2`` (the ``Host`` must be an allowed host)."""
    return (
        request_base(
            request,
            state.settings.allowed_hosts,
            setting="cas_service_name",
            trusted_proxies=state.trusted_proxies,
        )
        + PREFIX
    )


BaseUrlDep = Annotated[str, Depends(scim_base_url)]


def get_scim_service(
    user: UserDep, domain: DomainDep, state: StateDep, base_url: BaseUrlDep
) -> ScimService:
    return ScimService(user, domain, state.settings.scim, base_url)


ServiceDep = Annotated[ScimService, Depends(get_scim_service)]


def _scim_settings(state: StateDep) -> ScimSettings:
    return state.settings.scim


SettingsDep = Annotated[ScimSettings, Depends(_scim_settings)]


async def json_body(request: Request) -> dict[str, Any]:
    """The request body: a JSON object, as ``application/scim+json`` or ``application/json``."""
    media = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if media and media != "application/json" and not media.endswith("+json"):
        raise ScimError(415, f"Unsupported media type {media}: use {SCIM_MEDIA_TYPE}")
    raw = await request.body()
    try:
        parsed: Any = json.loads(raw)
    except ValueError as exc:
        raise bad_request("The request body is not valid JSON", INVALID_SYNTAX) from exc
    if not isinstance(parsed, dict):
        raise bad_request("The request body must be a JSON object", INVALID_SYNTAX)
    return cast("dict[str, Any]", parsed)


BodyDep = Annotated[dict[str, Any], Depends(json_body)]


# -- query parameters -----------------------------------------------------------------------------
def _names(raw: str | Sequence[str] | None) -> list[str]:
    if raw is None:
        return []
    items = raw.split(",") if isinstance(raw, str) else list(raw)
    return [n.strip() for n in items if n.strip()]


@dataclass(frozen=True, slots=True)
class Projection:
    attributes: list[str]
    excluded: list[str]

    def apply(self, resource: dict[str, Any]) -> dict[str, Any]:
        if not self.attributes and not self.excluded:
            return resource
        return scim_projection.project(resource, self.attributes, self.excluded)


def make_projection(
    attributes: str | Sequence[str] | None, excluded: str | Sequence[str] | None
) -> Projection:
    attrs, excl = _names(attributes), _names(excluded)
    if attrs and excl:
        raise bad_request(
            "attributes and excludedAttributes cannot be used together", INVALID_SYNTAX
        )
    return Projection(attrs, excl)


def projection_query(
    attributes: Annotated[str | None, Query()] = None,
    excluded: Annotated[str | None, Query(alias="excludedAttributes")] = None,
) -> Projection:
    return make_projection(attributes, excluded)


ProjectionDep = Annotated[Projection, Depends(projection_query)]


@dataclass(frozen=True, slots=True)
class ListQuery:
    flt: scim_filter.Filter | None
    start_index: int
    count: int
    sort_by: str | None
    descending: bool
    projection: Projection


def make_list_query(
    settings: ScimSettings,
    *,
    flt: str | None,
    start_index: int | None,
    count: int | None,
    sort_by: str | None,
    sort_order: str | None,
    projection: Projection,
) -> ListQuery:
    parsed = scim_filter.parse(flt) if flt is not None and flt.strip() else None
    start = max(1, start_index if start_index is not None else 1)
    limit = settings.max_results if count is None else max(0, min(count, settings.max_results))
    order = (sort_order or "ascending").strip().lower()
    if order not in ("ascending", "descending"):
        raise bad_request("sortOrder must be ascending or descending", INVALID_VALUE)
    return ListQuery(
        parsed, start, limit, (sort_by or "").strip() or None, order == "descending", projection
    )


def list_query(
    settings: SettingsDep,
    projection: ProjectionDep,
    flt: Annotated[str | None, Query(alias="filter")] = None,
    start_index: Annotated[int | None, Query(alias="startIndex")] = None,
    count: Annotated[int | None, Query()] = None,
    sort_by: Annotated[str | None, Query(alias="sortBy")] = None,
    sort_order: Annotated[str | None, Query(alias="sortOrder")] = None,
) -> ListQuery:
    return make_list_query(
        settings,
        flt=flt,
        start_index=start_index,
        count=count,
        sort_by=sort_by,
        sort_order=sort_order,
        projection=projection,
    )


ListQueryDep = Annotated[ListQuery, Depends(list_query)]


def _opt(body: dict[str, Any], key: str, kind: type) -> Any:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise bad_request(f"{key} has the wrong type", INVALID_VALUE)
    return value


def search_query(settings: ScimSettings, body: dict[str, Any]) -> ListQuery:
    """The :class:`ListQuery` of a ``SearchRequest`` message (RFC 7644 section 3.4.3)."""
    schemas = body.get("schemas")
    if not isinstance(schemas, list) or SEARCH_REQUEST not in cast("list[object]", schemas):
        raise bad_request(f"schemas must contain {SEARCH_REQUEST}", INVALID_SYNTAX)

    def names(key: str) -> list[str] | str | None:
        value = body.get(key)
        if value is None or isinstance(value, str):
            return value
        if isinstance(value, list) and all(isinstance(v, str) for v in cast("list[Any]", value)):
            return cast("list[str]", value)
        raise bad_request(f"{key} must be a list of attribute names", INVALID_VALUE)

    return make_list_query(
        settings,
        flt=_opt(body, "filter", str),
        start_index=_opt(body, "startIndex", int),
        count=_opt(body, "count", int),
        sort_by=_opt(body, "sortBy", str),
        sort_order=_opt(body, "sortOrder", str),
        projection=make_projection(names("attributes"), names("excludedAttributes")),
    )


# -- ETag -----------------------------------------------------------------------------------------
def _version(resource: dict[str, Any]) -> str | None:
    meta = resource.get("meta")
    if isinstance(meta, dict):
        version = cast("dict[str, Any]", meta).get("version")
        if isinstance(version, str):
            return version
    return None


def _etag_matches(header: str | None, version: str | None) -> bool:
    """Weak comparison of an ``If-Match`` / ``If-None-Match`` value with the version."""
    if header is None or version is None:
        return False
    if header.strip() == "*":
        return True
    wanted = version.removeprefix("W/")
    return any(part.strip().removeprefix("W/") == wanted for part in header.split(","))


def _check_if_match(request: Request, ops: ResourceOps, resource_id: str) -> None:
    header = request.headers.get("if-match")
    if header is None:
        return
    current = ops.get(resource_id)  # 404 first when the resource does not exist
    if not _etag_matches(header, _version(current)):
        raise ScimError(412, "The resource was changed since the version given in If-Match")


def _resource_response(
    resource: dict[str, Any], projection: Projection, status: int = 200, *, location: bool = False
) -> Response:
    headers: dict[str, str] = {}
    version = _version(resource)
    if version:
        headers["ETag"] = version
    if location:
        meta = resource.get("meta")
        url = cast("dict[str, Any]", meta).get("location") if isinstance(meta, dict) else None
        if isinstance(url, str):
            headers["Location"] = url
    return _json(projection.apply(resource), status, headers)


def _list_response(page: Page, projection: Projection) -> Response:
    resources = [projection.apply(r) for r in page.resources]
    return _json(
        {
            "schemas": [LIST_RESPONSE],
            "totalResults": page.total_results,
            "startIndex": page.start_index,
            "itemsPerPage": len(resources),
            "Resources": resources,
        }
    )


def _search(ops: ResourceOps, q: ListQuery) -> Response:
    page = ops.search(
        q.flt,
        start_index=q.start_index,
        count=q.count,
        sort_by=q.sort_by,
        descending=q.descending,
    )
    return _list_response(page, q.projection)


# -- routes ---------------------------------------------------------------------------------------
def _resource_routes(
    router: APIRouter, collection: str, ops_of: Callable[[ScimService], ResourceOps]
) -> None:
    base = f"/{collection}"
    item = base + "/{resource_id}"

    @router.get(base)
    def list_resources(  # pyright: ignore[reportUnusedFunction]
        user: UserDep, svc: ServiceDep, query: ListQueryDep
    ) -> Response:
        return _search(ops_of(svc), query)

    @router.post(base + "/.search")
    def search_resources(  # pyright: ignore[reportUnusedFunction]
        user: UserDep, svc: ServiceDep, settings: SettingsDep, body: BodyDep
    ) -> Response:
        return _search(ops_of(svc), search_query(settings, body))

    @router.post(base, status_code=201)
    def create_resource(  # pyright: ignore[reportUnusedFunction]
        user: UserDep, svc: ServiceDep, body: BodyDep, projection: ProjectionDep
    ) -> Response:
        return _resource_response(ops_of(svc).create(body), projection, 201, location=True)

    @router.get(item)
    def get_resource(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        user: UserDep,
        svc: ServiceDep,
        resource_id: str,
        projection: ProjectionDep,
    ) -> Response:
        resource = ops_of(svc).get(resource_id)
        version = _version(resource)
        if _etag_matches(request.headers.get("if-none-match"), version):
            return Response(status_code=304, headers={"ETag": version or ""})
        return _resource_response(resource, projection)

    @router.put(item)
    def replace_resource(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        user: UserDep,
        svc: ServiceDep,
        resource_id: str,
        body: BodyDep,
        projection: ProjectionDep,
    ) -> Response:
        ops = ops_of(svc)
        _check_if_match(request, ops, resource_id)
        return _resource_response(ops.replace(resource_id, body), projection)

    @router.patch(item)
    def patch_resource(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        user: UserDep,
        svc: ServiceDep,
        resource_id: str,
        body: BodyDep,
        projection: ProjectionDep,
    ) -> Response:
        ops = ops_of(svc)
        parsed = scim_patch.parse_patch(body)
        _check_if_match(request, ops, resource_id)
        return _resource_response(ops.patch(resource_id, parsed), projection)

    @router.delete(item, status_code=204)
    def delete_resource(  # pyright: ignore[reportUnusedFunction]
        request: Request, user: UserDep, svc: ServiceDep, resource_id: str
    ) -> Response:
        ops = ops_of(svc)
        _check_if_match(request, ops, resource_id)
        ops.delete(resource_id)
        return Response(status_code=204)


def _list_doc(docs: list[dict[str, Any]]) -> Response:
    return _json(
        {
            "schemas": [LIST_RESPONSE],
            "totalResults": len(docs),
            "startIndex": 1,
            "itemsPerPage": len(docs),
            "Resources": docs,
        }
    )


def _discovery_routes(router: APIRouter) -> None:
    @router.get("/ServiceProviderConfig")
    def service_provider_config(  # pyright: ignore[reportUnusedFunction]
        user: UserDep, settings: SettingsDep, base_url: BaseUrlDep
    ) -> Response:
        return _json(discovery.service_provider_config(settings, base_url))

    @router.get("/ResourceTypes")
    def list_resource_types(  # pyright: ignore[reportUnusedFunction]
        user: UserDep, base_url: BaseUrlDep
    ) -> Response:
        return _list_doc(discovery.resource_types(base_url))

    @router.get("/ResourceTypes/{name}")
    def get_resource_type(  # pyright: ignore[reportUnusedFunction]
        user: UserDep, base_url: BaseUrlDep, name: str
    ) -> Response:
        doc = discovery.resource_type(base_url, name)
        if doc is None:
            raise not_found(f"Unknown resource type {name}")
        return _json(doc)

    @router.get("/Schemas")
    def list_schemas(  # pyright: ignore[reportUnusedFunction]
        user: UserDep, base_url: BaseUrlDep
    ) -> Response:
        return _list_doc(discovery.schemas(base_url))

    @router.get("/Schemas/{urn}")
    def get_schema(  # pyright: ignore[reportUnusedFunction]
        user: UserDep, base_url: BaseUrlDep, urn: str
    ) -> Response:
        doc = discovery.schema(base_url, urn)
        if doc is None:
            raise not_found(f"Unknown schema {urn}")
        return _json(doc)


def build_router() -> APIRouter:
    """The ``/scim/v2`` router (outside ``/api/v2``: no session, no CSRF)."""
    router = APIRouter(
        prefix=PREFIX, route_class=ScimRoute, default_response_class=ScimJSONResponse
    )
    _resource_routes(router, "Users", lambda svc: svc.users)
    _resource_routes(router, "Groups", lambda svc: svc.groups)
    _discovery_routes(router)

    @router.api_route(
        "/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    def unknown(rest: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        raise not_found("Unknown SCIM endpoint")

    @router.api_route(
        "",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    def unknown_root() -> Response:  # pyright: ignore[reportUnusedFunction]
        raise not_found("Unknown SCIM endpoint")

    return router


__all__ = ["PREFIX", "ScimRoute", "build_router", "error_response", "get_scim_service"]
