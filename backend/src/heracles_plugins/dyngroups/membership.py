"""Dynamic group membership: LDAP URL / filter parsing and evaluation.

A rule is either a bare LDAP filter (``(department=sales)``) or an LDAP URL as
in RFC 4516 (``ldap:///ou=people,dc=example,dc=com??sub?(l=Paris)``). Only user
entries (``inetOrgPerson``) are members.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import unquote

from heracles.ldap import dn as dnlib
from heracles.ldap.client import (
    DirectoryClient,
    Entry,
    NoSuchObjectError,
    Scope,
    SizeLimitExceededError,
)
from heracles.ldap.filter import FilterError, matches, parse_filter

USER_CLASS = "inetOrgPerson"
DEFAULT_FILTER = "(objectClass=*)"
DEFAULT_MAX_MEMBERS = 10_000


class MemberRuleError(ValueError):
    """The membership rule is malformed or unusable."""


@dataclass(frozen=True, slots=True)
class MemberRule:
    """A parsed membership rule."""

    #: Search base; ``None`` means the directory base.
    base: str | None
    scope: Scope
    filter: str


_SCOPES = {"base": Scope.BASE, "one": Scope.ONE, "sub": Scope.SUBTREE}


def parse_member_rule(text: str) -> MemberRule:
    """Parse a bare filter or an LDAP URL; raises :class:`MemberRuleError`."""
    raw = text.strip()
    if not raw:
        raise MemberRuleError("The rule is empty.")
    if raw.startswith("("):
        return MemberRule(None, Scope.SUBTREE, _checked_filter(raw))
    scheme, sep, rest = raw.partition("://")
    if not sep or scheme.lower() not in {"ldap", "ldaps"}:
        raise MemberRuleError("Expected an LDAP filter or an ldap:// URL.")
    _host, slash, path = rest.partition("/")
    if not slash:
        raise MemberRuleError("The URL has no path.")
    parts = path.split("?")
    if len(parts) > 5:
        raise MemberRuleError("Too many components in the URL.")
    parts += [""] * (4 - len(parts))
    base = unquote(parts[0]).strip() or None
    scope_text = unquote(parts[2]).strip().lower() or "base"
    if scope_text not in _SCOPES:
        raise MemberRuleError("The scope must be base, one or sub.")
    flt = unquote(parts[3]).strip() or DEFAULT_FILTER
    if base is not None and not dnlib.split(base):
        raise MemberRuleError("Invalid search base.")
    return MemberRule(base, _SCOPES[scope_text], _checked_filter(flt))


def _checked_filter(text: str) -> str:
    try:
        parse_filter(text)
    except FilterError as exc:
        raise MemberRuleError(f"Invalid filter: {exc}") from None
    return text


def _search_base(rule: MemberRule, directory_base: str) -> str:
    base = rule.base or directory_base
    if not dnlib.is_descendant(base, directory_base):
        raise MemberRuleError("The search base is outside of the directory.")
    return base


def _in_scope(dn: str, base: str, scope: Scope) -> bool:
    if scope is Scope.BASE:
        return dnlib.normalize(dn) == dnlib.normalize(base)
    if not dnlib.is_descendant(dn, base):
        return False
    if scope is Scope.ONE:
        return dnlib.depth(dn) == dnlib.depth(base) + 1
    return True


def select_members(entries: Iterable[Entry], rule: MemberRule, *, directory_base: str) -> list[str]:
    """Pure evaluation: DNs of the user ``entries`` that satisfy ``rule``, sorted."""
    base = _search_base(rule, directory_base)
    flt = parse_filter(rule.filter)
    found = [
        e.dn
        for e in entries
        if e.has_object_class(USER_CLASS) and _in_scope(e.dn, base, rule.scope) and matches(e, flt)
    ]
    return sorted(found, key=dnlib.normalize)


def evaluate_members(
    directory: DirectoryClient,
    rule: MemberRule | str,
    *,
    max_members: int = DEFAULT_MAX_MEMBERS,
) -> list[str]:
    """DNs of the users matching ``rule`` (server-side search), sorted.

    Raises :class:`MemberRuleError` when the rule is invalid or matches more than
    ``max_members`` users.
    """
    parsed = parse_member_rule(rule) if isinstance(rule, str) else rule
    base = _search_base(parsed, directory.base_dn)
    flt = f"(&(objectClass={USER_CLASS}){parsed.filter})"
    try:
        entries = list(
            directory.search(base, flt, parsed.scope, ["objectClass"], size_limit=max_members + 1)
        )
    except NoSuchObjectError:
        return []
    except SizeLimitExceededError:
        raise MemberRuleError(f"The rule matches more than {max_members} users.") from None
    if len(entries) > max_members:
        raise MemberRuleError(f"The rule matches more than {max_members} users.")
    return sorted((e.dn for e in entries), key=dnlib.normalize)


__all__ = [
    "DEFAULT_MAX_MEMBERS",
    "MemberRule",
    "MemberRuleError",
    "evaluate_members",
    "parse_member_rule",
    "select_members",
]
