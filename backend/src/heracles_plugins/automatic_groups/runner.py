"""Automatic groups runner: add or remove users in a group according to a rule.

The rule is a regular expression applied to an attribute of the users of the task
(``[attribute:]regex``, the attribute defaults to ``AutomaticGroupsSettings.default_attribute``).
Matching users are added to the group; with a dynamic group the users of the task that no
longer match are removed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, Entry, Modification
from heracles.schema import names as schema
from heracles_plugins._patterns import PatternError, compile_checked, search
from heracles_plugins._secrets import is_secret_name
from heracles_plugins._tasks import (
    TaskReport,
    bool_of,
    expand_members,
    run_tasks,
    task_filter,
    utc,
)

TASK_CLASS = "hrcTasksAutomaticGroups"
TASK_FILTER = task_filter(TASK_CLASS)
_RULE = re.compile(r"(?P<attr>[A-Za-z][A-Za-z0-9-]*):(?P<regex>.*)", re.DOTALL)


class ForbiddenAttributeError(ValueError):
    """The rule tests an attribute whose values are secrets."""


@dataclass(slots=True)
class AutomaticGroupsSettings:
    """Settings of the automatic groups plugin."""

    #: Attribute tested by a rule that does not name one.
    default_attribute: str = "uid"


@dataclass(frozen=True, slots=True)
class MembershipChange:
    """Users added to or removed from a group by a run."""

    task_dn: str
    group_dn: str
    added: tuple[str, ...]
    removed: tuple[str, ...]


@dataclass(slots=True)
class AutomaticGroupsReport(TaskReport):
    """What an automatic groups run did."""

    changes: list[MembershipChange] = field(default_factory=lambda: [])


def parse_rule(rule: str, default_attribute: str) -> tuple[str, re.Pattern[str]]:
    """Split ``[attribute:]regex``.

    Raises :class:`~heracles_plugins._patterns.PatternError` for an invalid or unsafe
    expression (too long, nested quantifiers) and :class:`ForbiddenAttributeError` when the
    attribute holds secrets: the task runs with the server's rights and its result (who joins
    the group) is visible, so a rule such as ``userPassword:^{SSHA}ab`` would be an oracle.
    """
    match = _RULE.fullmatch(rule.strip())
    attribute, expression = (
        (default_attribute, rule.strip()) if match is None else (match["attr"], match["regex"])
    )
    if is_secret_name(attribute):
        raise ForbiddenAttributeError(attribute)
    return attribute, compile_checked(expression)


def _matches(user: Entry, attribute: str, regex: re.Pattern[str]) -> bool:
    return any(search(regex, v) for v in user.texts(attribute))


def _uses_dn(group: Entry) -> bool:
    return group.has_object_class("groupOfNames") or group.has_object_class(schema.OC.OBJECT_GROUP)


def _key(user: Entry, uses_dn: bool) -> str:
    """Identity of a user in the group: normalised DN (``member``) or login (``memberUid``)."""
    return dnlib.normalize(user.dn) if uses_dn else (user.text("uid") or "")


def _apply(
    directory: DirectoryClient,
    task: Entry,
    group: Entry,
    users: list[Entry],
    matching: set[str],
    dynamic: bool,
    report: AutomaticGroupsReport,
) -> None:
    uses_dn = _uses_dn(group)
    attr = "member" if uses_dn else "memberUid"
    stored = {dnlib.normalize(v) if uses_dn else v: v for v in group.texts(attr)}
    to_add = [u for u in users if _key(u, uses_dn) in matching and _key(u, uses_dn) not in stored]
    to_remove = (
        [u for u in users if _key(u, uses_dn) not in matching and _key(u, uses_dn) in stored]
        if dynamic
        else []
    )
    if uses_dn and to_remove and len(stored) - len(to_remove) + len(to_add) <= 0:
        report.errors.append(f"{group.dn}: a group needs at least one member, nobody removed")
        to_remove = []
    changes: list[Modification] = []
    if to_add:
        added = [(u.dn if uses_dn else u.text("uid") or "").encode() for u in to_add]
        changes.append(Modification("add", attr, added))
    if to_remove:
        removed = [stored[_key(u, uses_dn)].encode() for u in to_remove]
        changes.append(Modification("delete", attr, removed))
    if not changes:
        return
    directory.modify(group.dn, changes)
    report.changes.append(
        MembershipChange(
            task.dn, group.dn, tuple(u.dn for u in to_add), tuple(u.dn for u in to_remove)
        )
    )


def run_automatic_groups(
    directory: DirectoryClient,
    now: datetime,
    settings: AutomaticGroupsSettings | None = None,
) -> AutomaticGroupsReport:
    """Run every due automatic groups task once.

    The group (``hrcTasksAutomaticGroupsOfName``) is a ``groupOfNames`` or a POSIX group
    (``memberUid``). Users already in the group are left alone; a task whose group is
    missing or whose rule is invalid is reported and left to be retried.
    """
    settings = settings or AutomaticGroupsSettings()
    now = utc(now)
    report = AutomaticGroupsReport()

    def process(task: Entry) -> bool:
        group_dn = task.text("hrcTasksAutomaticGroupsOfName")
        group = directory.get(group_dn) if group_dn else None
        if group is None:
            report.errors.append(f"{task.dn}: group not found")
            return False
        try:
            attribute, regex = parse_rule(
                task.text("hrcTasksAutomaticGroupsRegexPattern") or ".*",
                settings.default_attribute,
            )
        except PatternError as exc:
            report.errors.append(f"{task.dn}: invalid rule ({exc})")
            return False
        except ForbiddenAttributeError as exc:
            report.errors.append(f"{task.dn}: the rule cannot test {exc}")
            return False
        users = expand_members(directory, task.texts("hrcTasksAutomaticGroupsMembers"), [attribute])
        uses_dn = _uses_dn(group)
        matching = {_key(u, uses_dn) for u in users if _matches(u, attribute, regex)}
        _apply(
            directory,
            task,
            group,
            users,
            matching,
            bool_of(task, "hrcTasksAutomaticGroupsDynamicGroup") is True,
            report,
        )
        return True

    run_tasks(directory, TASK_FILTER, now, process, report)
    return report
