"""Adapter exposing the evaluator to the object layer."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from heracles.acl.evaluator import AclEvaluator
from heracles.acl.rights import Rights


class AccessPolicy(Protocol):
    """What the object layer needs from access control."""

    def can_read(self, dn: str, tab: str, attr: str) -> bool: ...

    def can_write(self, dn: str, tab: str, attr: str) -> bool: ...

    def can_create(self, type_name: str, base: str) -> bool: ...

    def can_delete(self, dn: str, type_name: str) -> bool: ...


class AclAccessPolicy:
    """:class:`AccessPolicy` backed by an :class:`AclEvaluator`.

    ``tab_keys`` maps tab names to ACL object keys (``"posixAccount"`` ->
    ``"user/posixAccount"``); ``type_keys`` maps object type names to the key of
    their main tab (``"user"`` -> ``"user/user"``). Unknown names are denied.
    A tab name already containing ``/`` is taken as an object key.
    """

    def __init__(
        self,
        evaluator: AclEvaluator,
        *,
        tab_keys: Mapping[str, str],
        type_keys: Mapping[str, str],
    ) -> None:
        self._ev = evaluator
        self._tabs = dict(tab_keys)
        self._types = dict(type_keys)

    def _tab_key(self, tab: str) -> str | None:
        return self._tabs.get(tab) or (tab if "/" in tab else None)

    def can_read(self, dn: str, tab: str, attr: str) -> bool:
        key = self._tab_key(tab)
        return key is not None and self._ev.can_read_attr(dn, key, attr)

    def can_write(self, dn: str, tab: str, attr: str) -> bool:
        key = self._tab_key(tab)
        return key is not None and self._ev.can_write_attr(dn, key, attr)

    def can_create(self, type_name: str, base: str) -> bool:
        key = self._types.get(type_name)
        return key is not None and self._ev.permissions(base, key).create

    def can_delete(self, dn: str, type_name: str) -> bool:
        key = self._types.get(type_name)
        return key is not None and self._ev.permissions(dn, key).delete

    def permissions(self, dn: str, object_key: str, attribute: str = "") -> Rights:
        """Effective rights of the user on ``object_key`` (and ``attribute``) at ``dn``."""
        return self._ev.permissions(dn, object_key, attribute)
