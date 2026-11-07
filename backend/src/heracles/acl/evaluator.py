"""Permission evaluation for a connected user."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from heracles.acl.model import ALL_OBJECTS, AclBlock, AclScope, Rule
from heracles.acl.resolver import ResolvedAcl
from heracles.acl.rights import FULL_RIGHTS, NO_RIGHTS, Rights
from heracles.ldap import dn as dnlib

WILDCARD = "0"
"""Tab key of a category wildcard object (``<cat>/0``)."""

SNAPSHOT_ATTRIBUTE = "snapshot"


def object_key(category: str, tab: str) -> str:
    """ACL object key of a tab: ``<category>/<tab>``."""
    return f"{category}/{tab}"


class AclEvaluator:
    """Answers ``permissions(dn, object, attribute)`` for one connected user.

    ``category_tabs`` maps a category (``"user"``) to the tab keys it contains
    (``["user", "posixAccount", ...]``), used to expand ``<cat>/0`` wildcards.
    """

    def __init__(
        self,
        resolved: ResolvedAcl,
        *,
        category_tabs: Mapping[str, Sequence[str]] | None = None,
        ignore_acl: bool = False,
    ) -> None:
        self._resolved = resolved
        self._user = dnlib.normalize(resolved.user_dn)
        self._tabs = {k: tuple(v) for k, v in (category_tabs or {}).items()}
        self._ignore = ignore_acl
        self._cache: dict[tuple[str, str, str], Rights] = {}

    @property
    def user_dn(self) -> str:
        return self._user

    @property
    def ignore_acl(self) -> bool:
        return self._ignore

    # ------------------------------------------------------------------ core

    def permissions(
        self, dn: str, obj: str, attribute: str = "", skip_write: bool = False
    ) -> Rights:
        """Rights of the user on ``obj`` (optionally one attribute) of entry ``dn``."""
        if self._ignore:
            return FULL_RIGHTS.read_only() if skip_write else FULL_RIGHTS
        ndn = dnlib.normalize(dn)
        key = (ndn, obj, attribute.lower())
        cached = self._cache.get(key)
        if cached is None:
            cached = self._compute(ndn, obj, attribute)
            self._cache[key] = cached
        return cached.read_only() if skip_write else cached

    def _compute(self, ndn: str, obj: str, attribute: str) -> Rights:
        nearest = self._resolved.nearest_view(ndn)
        if nearest is None:
            return NO_RIGHTS
        _, view = nearest
        own = ndn == self._user
        result = NO_RIGHTS
        for rule in view:
            if result.is_full:
                break
            if rule.scope is AclScope.BASE and rule.origin != ndn:
                continue
            result = result.union(self._rule_rights(rule, obj, attribute, own=own))
        return result.without_self()

    def _rule_rights(self, rule: Rule, obj: str, attribute: str, *, own: bool) -> Rights:
        blocks = rule.blocks
        target = blocks.get(obj)
        if target is not None and target.is_self and not own:
            return NO_RIGHTS  # the whole rule is skipped
        result = NO_RIGHTS
        everything = blocks.get(ALL_OBJECTS)
        if everything is not None and (own or not everything.is_self):
            result = result.union(everything.rights)
        category, _, tab = obj.partition("/")
        if tab == WILDCARD and not attribute:
            if target is not None:
                result = result.union(target.rights)
            for name in self._tabs.get(category, ()):
                block = blocks.get(object_key(category, name))
                if block is not None and (own or not block.is_self):
                    result = result.union(block.rights)
            return result
        if target is None:
            return result
        if not attribute:
            return result.union(target.all_rights(own=own))
        return result.union(self._attribute_rights(target, attribute, own=own))

    @staticmethod
    def _attribute_rights(block: AclBlock, attribute: str, *, own: bool) -> Rights:
        return block.attribute_rights(attribute, own=own).union(block.rights)

    # --------------------------------------------------------------- helpers

    def can_read_attr(self, dn: str, obj: str, attribute: str) -> bool:
        return self.permissions(dn, obj, attribute).read

    def can_write_attr(self, dn: str, obj: str, attribute: str) -> bool:
        return self.permissions(dn, obj, attribute).write

    def can_create(self, base_dn: str, category: str, tab: str) -> bool:
        """``c`` on ``<category>/<tab>`` (the category's main tab) at ``base_dn``."""
        return self.permissions(base_dn, object_key(category, tab)).create

    def can_delete(self, dn: str, category: str, tab: str) -> bool:
        return self.permissions(dn, object_key(category, tab)).delete

    def can_move(self, dn: str, category: str, tab: str) -> bool:
        return self.permissions(dn, object_key(category, tab)).move

    def departments_for(self, category: str, departments: list[str]) -> list[str]:
        """Departments where the user has any right on the category."""
        wildcard = object_key(category, WILDCARD)
        return [d for d in departments if not self.permissions(d, wildcard).is_empty]

    # -------------------------------------------------------------- snapshots

    def can_snapshot_create(self, dn: str, obj: str) -> bool:
        return self._snapshot(dn, obj).create

    def can_snapshot_restore(self, dn: str, obj: str) -> bool:
        return self._snapshot(dn, obj).write

    def can_snapshot_delete(self, dn: str, obj: str) -> bool:
        return self._snapshot(dn, obj).delete

    def _snapshot(self, dn: str, obj: str) -> Rights:
        full = self.permissions(dn, obj)
        if full.is_full:
            return FULL_RIGHTS
        return self.permissions(dn, obj, SNAPSHOT_ATTRIBUTE)
