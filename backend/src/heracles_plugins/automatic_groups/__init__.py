"""Automatic groups plugin: keep group memberships in line with a rule.

Provides the ``automatic_groups_task`` type (``hrcTasks`` + ``hrcTasksAutomaticGroups``, ACL
``tasks/automaticGroupsTask``) and the pure runner :func:`run_automatic_groups`.

A task looks at its users (users, or groups and roles expanded to users), keeps those whose
attribute matches a regular expression (``[attribute:]regex``, the attribute defaults to
the login) and adds them to the chosen group. For a dynamic group, users of the task that no
longer match are removed too. The group may be a ``groupOfNames`` or a POSIX group.

"""

from __future__ import annotations

import re

from heracles.attributes import BooleanAttr, ListAttr, ObjectRefAttr, StringAttr
from heracles.i18n import _
from heracles.objects import Plugin, Section
from heracles.objects.hooks import TabContext
from heracles.objects.task_runner import TaskRunContext, TaskRunner
from heracles_plugins._tasks import TaskObjectType, TaskTab
from heracles_plugins.automatic_groups.runner import (
    TASK_CLASS,
    TASK_FILTER,
    AutomaticGroupsReport,
    AutomaticGroupsSettings,
    MembershipChange,
    parse_rule,
    run_automatic_groups,
)

PLUGIN_NAME = "automatic_groups"


class AutomaticGroupsTask(TaskObjectType):
    """A task adding and removing users in a group."""

    name = "automatic_groups_task"
    label = _("Automatic groups task")
    label_plural = _("Automatic groups tasks")
    nav = "hidden"
    icon = "users"
    filter = TASK_FILTER

    class Main(TaskTab):
        name = "main"
        acl_key = "automaticGroupsTask"
        label = _("Automatic groups")
        object_classes = ("hrcTasks", TASK_CLASS)

        rule = Section(
            _("Rule"),
            ObjectRefAttr(
                "hrcTasksAutomaticGroupsOfName",
                _("Group"),
                ref_type="group",
                required=True,
                description=_("Group that receives the matching users"),
            ),
            StringAttr(
                "hrcTasksAutomaticGroupsRegexPattern",
                _("Pattern"),
                description=_(
                    "Regular expression, optionally prefixed by an attribute name and a colon, "
                    "for example mail:@example\\.com$ (default attribute: login)"
                ),
            ),
            BooleanAttr(
                "hrcTasksAutomaticGroupsDynamicGroup",
                _("Dynamic group"),
                description=_("Also remove the users that no longer match"),
                default=False,
            ),
        )
        members = Section(
            _("Users"),
            ListAttr(
                "hrcTasksAutomaticGroupsMembers",
                _("Users, groups or roles"),
                ObjectRefAttr("member", _("Member"), ref_type="user"),
                required=True,
                description=_("Users, or groups and roles that are expanded to their users"),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            super().prepare(ctx)
            pattern = ctx.values.get("hrcTasksAutomaticGroupsRegexPattern")
            if isinstance(pattern, str) and pattern:
                try:
                    parse_rule(pattern, "uid")
                except re.error:
                    ctx.error(
                        "hrcTasksAutomaticGroupsRegexPattern", _("Invalid regular expression.")
                    )


def plugin() -> Plugin:
    """Entry point of the automatic groups plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(AutomaticGroupsTask,),
        required_object_classes=("hrcTasks", TASK_CLASS),
        settings=AutomaticGroupsSettings(),
        task_runners=(TaskRunner(PLUGIN_NAME, _run, kind=AutomaticGroupsTask.name),),
    )


def _run(ctx: TaskRunContext) -> AutomaticGroupsReport:
    settings = ctx.settings if isinstance(ctx.settings, AutomaticGroupsSettings) else None
    return run_automatic_groups(ctx.directory, ctx.now, settings)


__all__ = [
    "AutomaticGroupsReport",
    "AutomaticGroupsSettings",
    "AutomaticGroupsTask",
    "MembershipChange",
    "parse_rule",
    "plugin",
    "run_automatic_groups",
]
