"""``POST /api/v2/archive/{type}/{dn}``: archive an object before deleting it."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, status

from heracles.api.deps import CurrentUserDep
from heracles.api.domain import DomainDep
from heracles.api.errors import not_found, validation
from heracles.api.v2.objects import object_errors
from heracles.ldap.client import NoSuchObjectError
from heracles.objects import PermissionDeniedError
from heracles.objects.registry import PluginRouterContext
from heracles_plugins.archive.service import ArchiveError, ArchiveSettings, archive


def build_router(ctx: PluginRouterContext) -> APIRouter:
    """Router factory (``Plugin.api_routers``)."""
    router = APIRouter(prefix="/archive", tags=["archive"])

    @router.post("/{type_name}/{dn:path}", status_code=status.HTTP_201_CREATED)
    def archive_object(
        type_name: str, dn: str, user: CurrentUserDep, domain: DomainDep
    ) -> dict[str, str]:
        """Archive an object the user may delete; the object itself is left in place."""
        settings: Any = ctx.settings
        rules = settings if isinstance(settings, ArchiveSettings) else ArchiveSettings()
        with object_errors():
            service, policy = domain.service(user, type_name)
            service.load(type_name, dn)
            if not policy.can_delete(dn, type_name):
                raise PermissionDeniedError(f"cannot archive {dn}")
        try:
            archive_dn = archive(
                user.directory, dn, type_name, settings=rules, now=datetime.now(UTC)
            )
        except NoSuchObjectError:
            raise not_found(f"Object not found: {dn}") from None
        except ArchiveError as exc:
            raise validation(str(exc)) from exc
        return {"dn": archive_dn}

    return router
