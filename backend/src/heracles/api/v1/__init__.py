"""API v1: the compatibility REST API used by existing scripts.

Sessions are identified by the ``Session-Token`` header (the older
``X-Session-Token`` spelling is also accepted) instead of a cookie, so v1 is
exempt from CSRF protection. Tabs and attributes are addressed by their legacy
names, see :mod:`heracles.api.v1.names`. Accounts with a second factor cannot
use API v1: the login is refused with a 401 explaining it. The contract is
published at ``/api/v1/openapi.json``.
"""

from __future__ import annotations

import copy
from typing import cast

from fastapi import APIRouter, Request

from heracles.api.v1 import misc, objects, session
from heracles.api.v1.common import V1Route

PREFIX = "/api/v1"

router = APIRouter(prefix=PREFIX)
router.include_router(session.router)
router.include_router(objects.router)
router.include_router(misc.router)


def _refs(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in cast("dict[str, object]", node).items():
            if key == "$ref" and isinstance(value, str):
                found.add(value.rsplit("/", 1)[-1])
            else:
                _refs(value, found)
    elif isinstance(node, list):
        for item in cast("list[object]", node):
            _refs(item, found)


def build_openapi(request: Request) -> dict[str, object]:
    """OpenAPI description of the v1 routes only (paths relative to ``/api/v1``)."""
    full = copy.deepcopy(request.app.openapi())
    paths: dict[str, object] = {}
    for path, item in cast("dict[str, object]", full.get("paths", {})).items():
        if path.startswith(PREFIX + "/"):
            paths[path.removeprefix(PREFIX)] = item
    used: set[str] = set()
    _refs(paths, used)
    all_schemas = cast("dict[str, object]", full.get("components", {}).get("schemas", {}))
    pending = list(used)
    while pending:
        name = pending.pop()
        extra: set[str] = set()
        _refs(all_schemas.get(name), extra)
        for other in extra - used:
            used.add(other)
            pending.append(other)
    schema: dict[str, object] = {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {
            "title": "Heracles REST API v1",
            "version": "1.0.0",
            "description": "Compatibility REST API.",
        },
        "servers": [{"url": PREFIX}],
        "security": [{"session": []}],
        "paths": paths,
        "components": {
            "schemas": {k: v for k, v in all_schemas.items() if k in used},
            "securitySchemes": {
                "session": {"type": "apiKey", "name": "Session-Token", "in": "header"}
            },
        },
    }
    for path in ("/login", "/directories"):
        item = cast("dict[str, dict[str, object]]", paths.get(path, {}))
        for operation in item.values():
            operation["security"] = []
    return schema


@router.get("/openapi.json", include_in_schema=False)
def openapi(request: Request) -> dict[str, object]:
    return build_openapi(request)


__all__ = ["V1Route", "router"]
