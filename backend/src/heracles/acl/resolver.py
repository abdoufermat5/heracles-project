"""Resolution of the ACL rules that apply to a connected user."""

from __future__ import annotations

import itertools
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import structlog

from heracles.acl.model import AclAssignment, AclBlock, AclScope, AclWarning, Ignored, Rule
from heracles.acl.parser import parse_assignment, parse_role_value
from heracles.ldap import dn as dnlib

log = structlog.get_logger(__name__)

DEFAULT_TARGET_LIMIT = 100
_PLACEHOLDER = re.compile(r"%([A-Za-z][A-Za-z0-9;-]*)%")


@dataclass(frozen=True, slots=True)
class AssignmentEntry:
    """An entry carrying assignment values."""

    dn: str
    values: Sequence[str]


class AclDirectory(Protocol):
    """Every directory lookup the ACL engine needs."""

    def groups_of_user(self, user_dn: str) -> list[str]:
        """DNs of ``groupOfNames`` entries having ``member=<user_dn>``."""
        ...

    def posix_groups_by_uid(self, uid: str) -> list[str]:
        """DNs of ``posixGroup`` entries having ``memberUid=<uid>``."""
        ...

    def roles_of_user(self, user_dn: str) -> list[str]:
        """DNs of ``organizationalRole`` entries having ``roleOccupant=<user_dn>``."""
        ...

    def assignment_entries(self) -> list[AssignmentEntry]:
        """Every entry below the base carrying assignment values."""
        ...

    def role_templates(self, role_dn: str) -> list[str]:
        """Template values of an ACL role (empty if the role does not exist)."""
        ...

    def user_matches_filter(self, user_dn: str, filterstr: str) -> bool:
        """Base search on the user entry with ``filterstr``."""
        ...

    def search_targets(self, base_dn: str, filterstr: str, limit: int) -> list[str]:
        """Subtree search under ``base_dn``; returns at most ``limit`` DNs."""
        ...


def escape_filter_value(value: str) -> str:
    """Escape a value for use inside an LDAP filter (RFC 4515)."""
    out: list[str] = []
    for ch in value:
        if ch in "\\*()\x00":
            out.append(f"\\{ord(ch):02x}")
        else:
            out.append(ch)
    return "".join(out)


def _substituter(values: Mapping[str, str]) -> Callable[[re.Match[str]], str]:
    def substitute(match: re.Match[str]) -> str:
        return escape_filter_value(values[match.group(1).lower()])

    return substitute


def expand_target_filter(template: str, user_attrs: Mapping[str, Sequence[str]]) -> list[str]:
    """Substitute ``%attr%`` placeholders with escaped values of the user.

    A multi-valued attribute yields one filter per value. When a placeholder has
    no value the result is empty: an unresolved placeholder must never widen the
    match.
    """
    names: list[str] = []
    for match in _PLACEHOLDER.finditer(template):
        name = match.group(1).lower()
        if name not in names:
            names.append(name)
    if not names:
        return [template]
    lowered = {k.lower(): v for k, v in user_attrs.items()}
    pools = [list(lowered.get(name, ())) for name in names]
    if any(not pool for pool in pools):
        return []
    filters: list[str] = []
    for combo in itertools.product(*pools):
        chosen = dict(zip(names, combo, strict=True))
        filters.append(_PLACEHOLDER.sub(_substituter(chosen), template))
    return filters


@dataclass(slots=True)
class ResolvedAcl:
    """Result of the resolution: per-path rule views plus warnings."""

    user_dn: str
    rules: dict[str, list[Rule]] = field(default_factory=lambda: {})
    views: dict[str, tuple[Rule, ...]] = field(default_factory=lambda: {})
    warnings: list[AclWarning] = field(default_factory=lambda: [])
    #: ``time.monotonic()`` of the resolution: callers refresh a resolution that grew old.
    resolved_at: float = field(default_factory=time.monotonic)

    @property
    def targets_by_depth(self) -> list[str]:
        """Normalised target DNs, shallowest first."""
        return sorted(self.rules, key=lambda d: (dnlib.depth(d), d))

    def nearest_view(self, dn: str) -> tuple[str, tuple[Rule, ...]] | None:
        """The view of ``dn`` or of its closest ancestor having one."""
        for candidate in ancestors(dn):
            view = self.views.get(candidate)
            if view is not None:
                return candidate, view
        return None


def ancestors(dn: str) -> Iterator[str]:
    """Normalised ``dn`` followed by its ancestors, nearest first."""
    parts = dnlib.split(dnlib.normalize(dn))
    for i in range(len(parts)):
        yield ",".join(parts[i:])


class AclResolver:
    """Computes :class:`ResolvedAcl` for a user (run at login, cache per session)."""

    def __init__(
        self, directory: AclDirectory, *, target_limit: int = DEFAULT_TARGET_LIMIT
    ) -> None:
        self._dir = directory
        self._limit = target_limit

    def resolve(
        self,
        user_dn: str,
        *,
        uid: str | None = None,
        user_attrs: Mapping[str, Sequence[str]] | None = None,
    ) -> ResolvedAcl:
        attrs: dict[str, Sequence[str]] = {k.lower(): v for k, v in (user_attrs or {}).items()}
        attrs.setdefault("dn", [user_dn])
        if uid is not None:
            attrs.setdefault("uid", [uid])
        result = ResolvedAcl(user_dn=dnlib.normalize(user_dn))

        # Steps 1-2: identities of the user.
        identities = {dnlib.normalize(user_dn)}
        identities.update(dnlib.normalize(g) for g in self._dir.groups_of_user(user_dn))
        if uid:
            identities.update(dnlib.normalize(g) for g in self._dir.posix_groups_by_uid(uid))
        identities.update(dnlib.normalize(r) for r in self._dir.roles_of_user(user_dn))

        # Steps 3-4.
        for entry in self._dir.assignment_entries():
            for value in entry.values:
                parsed = parse_assignment(value)
                if isinstance(parsed, Ignored):
                    result.warnings.append(
                        AclWarning("ignored_assignment", parsed.reason, entry.dn)
                    )
                    continue
                if not self._relevant(parsed, identities):
                    continue
                if parsed.user_filter and not self._dir.user_matches_filter(
                    user_dn, parsed.user_filter
                ):
                    continue
                targets = self._targets(entry.dn, parsed, attrs, result)
                if not targets:
                    continue
                role_rules = self._role_rules(parsed, result)
                for target in targets:
                    key = dnlib.normalize(target)
                    for scope, blocks in role_rules:
                        result.rules.setdefault(key, []).append(Rule(key, scope, blocks))
        # Steps 5-6.
        for target in result.targets_by_depth:
            view: list[Rule] = list(result.rules[target])
            for ancestor in itertools.islice(ancestors(target), 1, None):
                view.extend(
                    r for r in result.rules.get(ancestor, ()) if r.scope is AclScope.SUBTREE
                )
            result.views[target] = tuple(view)
        return result

    @staticmethod
    def _relevant(assignment: AclAssignment, identities: set[str]) -> bool:
        if assignment.applies_to_everyone:
            return True
        return any(dnlib.normalize(m) in identities for m in assignment.members)

    def _targets(
        self,
        entry_dn: str,
        assignment: AclAssignment,
        attrs: Mapping[str, Sequence[str]],
        result: ResolvedAcl,
    ) -> list[str]:
        if not assignment.target_filter:
            return [entry_dn]
        found: list[str] = []
        seen: set[str] = set()
        overflow = False
        for filterstr in expand_target_filter(assignment.target_filter, attrs):
            for target in self._dir.search_targets(entry_dn, filterstr, self._limit + 1):
                key = dnlib.normalize(target)
                if key in seen:
                    continue
                if len(found) >= self._limit:
                    overflow = True
                    break
                seen.add(key)
                found.append(target)
        if overflow:
            message = f"target filter matched more than {self._limit} entries; extra ignored"
            log.warning("acl_target_limit", dn=entry_dn, limit=self._limit)
            result.warnings.append(AclWarning("target_limit", message, entry_dn))
        return found

    def _role_rules(
        self,
        assignment: AclAssignment,
        result: ResolvedAcl,
    ) -> list[tuple[AclScope, dict[str, AclBlock]]]:
        out: list[tuple[AclScope, dict[str, AclBlock]]] = []
        for value in self._dir.role_templates(assignment.role_dn):
            parsed = parse_role_value(value)
            if isinstance(parsed, Ignored):
                result.warnings.append(
                    AclWarning("ignored_role_value", parsed.reason, assignment.role_dn)
                )
                continue
            out.append((assignment.scope, parsed.block_map()))
        return out
