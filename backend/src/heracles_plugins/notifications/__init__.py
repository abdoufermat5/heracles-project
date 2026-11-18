"""Notifications plugin: mail people when monitored attributes of users change.

Provides the ``notifications_task`` type (``hrcTasks`` + ``hrcTasksNotifications``, ACL
``tasks/notificationsTask``) and the pure runner :func:`run_notifications`.

A task monitors some attributes of its members (users, or groups and roles expanded to
users) and mails the recipients, with a mail template (``mail_template`` object, see
``user_reminder``), one mail per changed member. Placeholders: ``{uid} {cn} {mail}
{changes} {attributes}``. The values seen at the previous run are kept as a snapshot below
the task; the first run only records them.

The attributes a task may monitor are ``NotificationsSettings.attributes``
(``registry.settings["notifications"]``); password attributes are never monitored.

"""

from __future__ import annotations

from heracles.attributes import EmailAttr, ListAttr, MultiSelectAttr, ObjectRefAttr
from heracles.i18n import _
from heracles.objects import Plugin, Section
from heracles.objects.hooks import TabContext
from heracles.objects.task_runner import TaskRunContext, TaskRunner
from heracles_plugins._secrets import is_secret_name
from heracles_plugins._tasks import MemberRefAttr, TaskObjectType, TaskTab
from heracles_plugins._tasks.author import AuthorRights, author_section, stamp_author
from heracles_plugins.notifications.runner import (
    TASK_CLASS,
    TASK_FILTER,
    TEMPLATE_FIELDS,
    NotificationRecord,
    NotificationsReport,
    NotificationsSettings,
    delete_snapshots,
    load_snapshots,
    run_notifications,
)

PLUGIN_NAME = "notifications"

_PLACEHOLDERS = " ".join("{" + f + "}" for f in TEMPLATE_FIELDS)


class NotificationsTask(TaskObjectType):
    """A task mailing changes of monitored attributes."""

    name = "notifications_task"
    label = _("Notifications task")
    label_plural = _("Notifications tasks")
    nav = "hidden"
    icon = "bell"
    filter = TASK_FILTER

    class Main(TaskTab):
        name = "main"
        acl_key = "notificationsTask"
        label = _("Notifications")
        object_classes = ("hrcTasks", TASK_CLASS)

        notifications = Section(
            _("Notifications"),
            MultiSelectAttr(
                "hrcTasksNotificationsAttributes",
                _("Monitored attributes"),
                options=[
                    (a, a) for a in NotificationsSettings().attributes if not is_secret_name(a)
                ],
                required=True,
            ),
            ObjectRefAttr(
                "hrcTasksNotificationsMailTemplate",
                _("Mail template"),
                ref_type="mail_template",
                required=True,
                description=_("Placeholders: ") + _PLACEHOLDERS,
            ),
            EmailAttr("hrcTasksNotificationsEmailSender", _("Sender address"), required=True),
        )
        members = Section(
            _("People"),
            ListAttr(
                "hrcTasksNotificationsMonitoredMembers",
                _("Monitored users, groups or roles"),
                MemberRefAttr("member", _("Member")),
                required=True,
                description=_("Users, or groups and roles that are expanded to their users"),
            ),
            ListAttr(
                "hrcTasksNotificationsRecipientsMembers",
                _("Recipients"),
                MemberRefAttr("recipient", _("Recipient")),
                required=True,
                description=_("Users, groups or roles receiving the notifications"),
            ),
        )

        author = author_section()

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            super().prepare(ctx)
            stamp_author(ctx)

        @classmethod
        def before_delete(cls, ctx: TabContext) -> None:
            if ctx.dn is not None:
                delete_snapshots(ctx.directory, ctx.dn)


def plugin() -> Plugin:
    """Entry point of the notifications plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(NotificationsTask,),
        required_object_classes=("hrcTasks", TASK_CLASS),
        settings=NotificationsSettings(),
        task_runners=(
            TaskRunner(PLUGIN_NAME, _run, kind=NotificationsTask.name, needs_mailer=True),
        ),
    )


def _run(ctx: TaskRunContext) -> NotificationsReport:
    settings = ctx.settings if isinstance(ctx.settings, NotificationsSettings) else None
    mailer = ctx.mailer
    if mailer is None:
        raise RuntimeError("no mail server is configured")
    rights = AuthorRights(ctx.directory, ctx.registry, ctx.admin_dns)
    return run_notifications(ctx.directory, mailer, ctx.now, settings, rights=rights)


__all__ = [
    "NotificationRecord",
    "NotificationsReport",
    "NotificationsSettings",
    "NotificationsTask",
    "load_snapshots",
    "plugin",
    "run_notifications",
]
