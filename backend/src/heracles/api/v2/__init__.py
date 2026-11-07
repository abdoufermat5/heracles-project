"""API v2 (SPA contract, docs/specs/04-api-v2.md).

Other streams add their routers to :data:`router` (or ``include_router`` them in
``create_app``); every route inherits the CSRF dependency.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from heracles.api.deps import csrf_protect
from heracles.api.v2 import auth

router = APIRouter(prefix="/api/v2", dependencies=[Depends(csrf_protect)])
router.include_router(auth.router)
router.include_router(auth.directories_router)
