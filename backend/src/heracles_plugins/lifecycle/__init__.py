"""Lifecycle plugin: act on accounts that reached their end date.

Provides the ``lifecycle_task`` type (``hrcTasks`` + ``hrcTasksLifeCycle``, ACL
``tasks/lifeCycleTask``) and the pure runner :func:`run_lifecycle`.

The change applied (lock the account, move it to a department, set an attribute) and the end
date attribute (POSIX ``shadowExpire`` by default) are plugin settings
(``registry.settings["lifecycle"]``). Each task chooses the accounts (members, login pattern),
a grace period in days after the end date and whether to also lock the account.

Integration notes: from the CLI / scheduler call ``run_lifecycle(directory,
datetime.now(UTC), registry.settings["lifecycle"], lock_hooks=registry.account_lock_hooks)``.
"""

from __future__ import annotations

import re

from heracles.attributes import BooleanAttr, IntAttr, ListAttr, ObjectRefAttr, StringAttr
from heracles.i18n import _
from heracles.objects import Plugin, Section
from heracles.objects.hooks import TabContext
from heracles_plugins._tasks import TaskObjectType, TaskTab
from heracles_plugins.lifecycle.runner import (
    TASK_CLASS,
    TASK_FILTER,
    LifecycleRecord,
    LifecycleReport,
    LifecycleSettings,
    run_lifecycle,
)

PLUGIN_NAME = "lifecycle"


class LifecycleTask(TaskObjectType):
    """A task applying a change to the accounts that reached their end date."""

    name = "lifecycle_task"
    label = _("Lifecycle task")
    label_plural = _("Lifecycle tasks")
    icon = "hourglass"
    filter = TASK_FILTER

    class Main(TaskTab):
        name = "main"
        acl_key = "lifeCycleTask"
        label = _("Lifecycle")
        object_classes = ("hrcTasks", TASK_CLASS)

        lifecycle = Section(
            _("Lifecycle"),
            IntAttr(
                "hrcTasksLifeCyclePostEndDate",
                _("Grace period (days)"),
                min=0,
                description=_("Days to wait after the end date before changing the account"),
            ),
            StringAttr(
                "hrcTasksLifeCycleRegexPattern",
                _("Login pattern"),
                description=_("Regular expression; only matching logins are processed"),
            ),
            BooleanAttr(
                "hrcTasksLifeCycleEnableAccountClosure",
                _("Lock the account"),
                description=_("Also lock the account, whatever the configured change"),
                default=False,
            ),
        )
        members = Section(
            _("Accounts"),
            ListAttr(
                "hrcTasksLifeCycleMembers",
                _("Users, groups or roles"),
                ObjectRefAttr("member", _("Member"), ref_type="user"),
                required=True,
                description=_("Users, or groups and roles that are expanded to their users"),
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            super().prepare(ctx)
            pattern = ctx.values.get("hrcTasksLifeCycleRegexPattern")
            if isinstance(pattern, str) and pattern:
                try:
                    re.compile(pattern)
                except re.error:
                    ctx.error("hrcTasksLifeCycleRegexPattern", _("Invalid regular expression."))


def plugin() -> Plugin:
    """Entry point of the lifecycle plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(LifecycleTask,),
        required_object_classes=("hrcTasks", TASK_CLASS),
        settings=LifecycleSettings(),
    )


__all__ = [
    "LifecycleRecord",
    "LifecycleReport",
    "LifecycleSettings",
    "LifecycleTask",
    "plugin",
    "run_lifecycle",
]
