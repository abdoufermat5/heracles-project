"""API v2: the JSON contract between the SPA and the backend.

:func:`build_router` assembles a fresh router per application; every route
inherits the CSRF dependency.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import APIRouter, Depends

from heracles.api.deps import csrf_protect
from heracles.api.v2 import auth
from heracles.auth import routes as sso_routes


def build_router(extra: Iterable[APIRouter] = ()) -> APIRouter:
    """The ``/api/v2`` router with the auth routes plus ``extra`` routers."""
    router = APIRouter(prefix="/api/v2", dependencies=[Depends(csrf_protect)])
    router.include_router(auth.router)
    router.include_router(auth.directories_router)
    router.include_router(sso_routes.router)  # P3 compat: login methods, CAS, HTTP Basic
    for sub in extra:
        router.include_router(sub)
    return router
