"""SCIM ``User`` / ``Group`` resources over the Heracles ``user`` / ``group`` object types.

Owner: stream B. Contract (the router, stream C, codes against it):

* ``ScimService(user, domain, settings, base_url)``: one per request. ``user`` is the
  request's :class:`~heracles.api.deps.CurrentUser` (the token's owner), ``domain`` the
  :class:`~heracles.api.domain.Domain`. Every read and write goes through
  ``domain.service(user, type_name)`` (ACL, validation, hooks, audit, snapshots) and the
  account lock / archive paths the console uses; never around them. ``base_url`` is the
  absolute URL of ``/scim/v2`` (``meta.location`` = ``{base_url}/Users/{id}``).
* ``.users`` and ``.groups`` are :class:`ResourceOps`. Every method returns resources in
  SCIM JSON shape with ``schemas``, ``id``, ``meta`` (``resourceType``, ``created``,
  ``lastModified``, ``location``, ``version``); errors are :class:`ScimError` (404 unknown
  id or not readable, 409 ``uniqueness``, 400 ``invalidValue`` / ``mutability`` /
  ``invalidFilter``, 403 when the ACL refuses).
* ``version`` is a weak ETag ``W/"<hash>"`` of the resource without its ``meta``; the router
  compares it with ``If-Match`` / ``If-None-Match``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from heracles.scim.filter import Filter
from heracles.scim.patch import PatchOp
from heracles.scim.settings import ScimSettings

if TYPE_CHECKING:
    from heracles.api.deps import CurrentUser
    from heracles.api.domain import Domain


@dataclass(frozen=True, slots=True)
class Page:
    """One page of a list request (``start_index`` is 1-based, as in SCIM)."""

    resources: list[dict[str, Any]]
    total_results: int
    start_index: int


class ResourceOps(Protocol):
    def get(self, resource_id: str) -> dict[str, Any]: ...

    def search(
        self,
        flt: Filter | None,
        *,
        start_index: int = 1,
        count: int | None = None,
        sort_by: str | None = None,
        descending: bool = False,
    ) -> Page: ...

    def create(self, resource: dict[str, Any]) -> dict[str, Any]: ...

    def replace(self, resource_id: str, resource: dict[str, Any]) -> dict[str, Any]: ...

    def patch(self, resource_id: str, ops: list[PatchOp]) -> dict[str, Any]: ...

    def delete(self, resource_id: str) -> None: ...


class ScimService:
    def __init__(
        self, user: CurrentUser, domain: Domain, settings: ScimSettings, base_url: str
    ) -> None:
        raise NotImplementedError

    @property
    def users(self) -> ResourceOps:
        raise NotImplementedError

    @property
    def groups(self) -> ResourceOps:
        raise NotImplementedError


__all__ = ["Page", "ResourceOps", "ScimService"]
