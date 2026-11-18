"""Who a task acts for: the author recorded on it and the read rights that author holds.

A task runs unattended, so it must not read (and mail or export) more than the person who
defined it could read in the console. The last person to save a task is recorded in
``hrcTasksAuthor``; a run evaluates the ACLs of that DN and drops every attribute, and every
entry, the author may not read. A task without a (still existing) author does not run.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import structlog

from heracles.acl import AclEvaluator, AclResolver, LdapAclDirectory
from heracles.api.domain import TypeAclPolicy, category_tabs_of
from heracles.attributes import AnyAttribute, StringAttr
from heracles.i18n import _
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Entry
from heracles.ldap.filter import Filter, matches, parse_filter
from heracles.objects import Section, TypeInfo, TypeRegistry
from heracles.objects.hooks import TabContext
from heracles.objects.model import Tab

log = structlog.get_logger(__name__)

AUTHOR_ATTR = "hrcTasksAuthor"


def author_section() -> Section:
    """The read-only "Author" section of a task kind (used with :func:`stamp_author`)."""
    return Section(
        _("Author"),
        StringAttr(
            AUTHOR_ATTR,
            _("Author"),
            readonly=True,
            description=_("Whose rights the task runs with: the person who last saved it"),
        ),
    )


def stamp_author(ctx: TabContext) -> None:
    """Record the acting user as the author of the task being saved (from ``prepare``)."""
    author = getattr(ctx.policy, "user_dn", None)
    if isinstance(author, str):  # no acting user on an internal save
        ctx.values[AUTHOR_ATTR] = author


def _find(tab: type[Tab], lowered: str) -> AnyAttribute | None:
    for attr in tab.attributes():
        if attr.name.lower() == lowered:
            return attr
    return None


@dataclass(slots=True)
class AuthorReader:
    """What one author may read of the user entries a task handles."""

    evaluator: AclEvaluator
    registry: TypeRegistry
    _filters: dict[str, Filter]

    def _policies(self, entry: Entry) -> list[tuple[TypeInfo, TypeAclPolicy]]:
        found: list[tuple[TypeInfo, TypeAclPolicy]] = []
        for info in self.registry.list():
            flt = self._filters.get(info.name)
            if flt is None:
                flt = self._filters[info.name] = parse_filter(info.type.filter)
            if matches(entry, flt):
                found.append((info, TypeAclPolicy(self.evaluator, info)))
        return found

    def readable(self, entry: Entry, names: Iterable[str]) -> list[str] | None:
        """The ``names`` the author may read on ``entry``, in order; ``None`` when the entry
        itself is not readable. An attribute no tab describes is judged by the main tab."""
        policies = self._policies(entry)
        if not any(p.can_read(entry.dn, info.main_tab.name, "") for info, p in policies):
            return None
        out: list[str] = []
        for name in names:
            wanted = name.lower()
            known = False
            allowed = False
            for info, policy in policies:
                for tab in info.tabs:
                    attr = _find(tab, wanted)
                    if attr is None:
                        continue
                    known = True
                    if not attr.write_only and policy.can_read(entry.dn, tab.name, attr.name):
                        allowed = True
            if not known:
                allowed = any(p.can_read(entry.dn, i.main_tab.name, name) for i, p in policies)
            if allowed:
                out.append(name)
        return out

    def filtered(self, entry: Entry, names: Iterable[str]) -> Entry | None:
        """``entry`` reduced to the readable ``names`` (``None``: not readable at all).

        ``uid`` and ``cn`` stay when readable so a row keeps its label; everything else is
        dropped.
        """
        allowed = self.readable(entry, [*names, "uid", "cn"])
        if allowed is None:
            return None
        kept = {n.lower() for n in allowed}
        shown = {n: list(v) for n, v in entry.attrs.items() if n.lower() in kept}
        return Entry(entry.dn, shown)


class AuthorRights:
    """Builds, once per run, the reader of each task author."""

    def __init__(
        self,
        directory: DirectoryClient,
        registry: TypeRegistry,
        admin_dns: Iterable[str] = (),
    ) -> None:
        self._directory = directory
        self._registry = registry
        self._admins = frozenset(dnlib.normalize(d) for d in admin_dns)
        self._readers: dict[str, AuthorReader | None] = {}
        self._evaluators: dict[str, AclEvaluator | None] = {}
        self._category_tabs = category_tabs_of(registry)

    def evaluator_for(self, author: str) -> AclEvaluator | None:
        """ACL evaluator of ``author``, resolved once per run; ``None`` if they no longer exist."""
        key = dnlib.normalize(author)
        if key not in self._evaluators:
            self._evaluators[key] = self._build_evaluator(author)
        return self._evaluators[key]

    def reader_for(self, task: Entry) -> AuthorReader | None:
        """The reader of the author recorded on ``task``; ``None`` when there is none."""
        author = task.text(AUTHOR_ATTR)
        if not author:
            return None
        key = dnlib.normalize(author)
        if key not in self._readers:
            evaluator = self.evaluator_for(author)
            self._readers[key] = (
                None if evaluator is None else AuthorReader(evaluator, self._registry, {})
            )
        return self._readers[key]

    def _build_evaluator(self, author: str) -> AclEvaluator | None:
        try:
            entry = self._directory.get(author)
        except DirectoryError:
            return None
        if entry is None:
            return None
        attrs = {k: [v.decode("utf-8", "replace") for v in vals] for k, vals in entry.attrs.items()}
        resolved = AclResolver(LdapAclDirectory(self._directory)).resolve(
            author, uid=entry.text("uid"), user_attrs=attrs
        )
        return AclEvaluator(
            resolved,
            category_tabs=self._category_tabs,
            ignore_acl=dnlib.normalize(author) in self._admins,
        )


def author_missing(dn: str) -> str:
    """Report line of a task that cannot run for lack of a usable author."""
    return f"{dn}: the task has no author who still exists; save it again to run it"


__all__ = [
    "AUTHOR_ATTR",
    "AuthorReader",
    "AuthorRights",
    "author_missing",
    "author_section",
    "stamp_author",
]
