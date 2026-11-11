"""Audit plugin: security audit log of object changes.

Provides:

* the read-only ``audit_event`` type (entries below ``ou=audit``, ACL ``auditEvent/auditEvent``);
* the ``audit_task`` type (``hrcTasks`` + ``hrcAuditTasks``) that purges old events and can
  forward new ones to syslog, run with :func:`run_audit`;
* ``GET /api/v2/audit``: filtered, paged and exportable view of the log (the user
  profile and the object editor use it for their history);
* :class:`AuditEvents`, an ``ObjectEvents`` implementation writing the events.

Integration notes for the framework owners:

* Events: ``Domain.service`` builds ``ObjectService(directory, registry, policy=policy)``
  for each request. Pass ``events=AuditEvents(user.directory, author_dn=user.dn,
  author_ip=<client address>, settings=registry.settings["audit"])`` there (and, to keep
  other hooks, wrap several ``ObjectEvents`` in one object calling each in turn).
* Scheduler / CLI: ``run_audit(directory, datetime.now(UTC), registry.settings["audit"])``,
  hourly or daily. Bind a ``logging.handlers.SysLogHandler`` to the ``heracles.audit`` logger
  to get the syslog forwarding.
"""

from __future__ import annotations

from heracles.attributes import (
    BooleanAttr,
    DateTimeAttr,
    DepartmentAttr,
    IntAttr,
    ListAttr,
    ObjectRefAttr,
    StringAttr,
)
from heracles.core.audit import AUDIT_RDN, EVENT_CLASS
from heracles.i18n import _
from heracles.objects import ObjectType, Plugin, Section, Tab
from heracles.objects.hooks import TabContext
from heracles.objects.registry import EventsContext
from heracles_plugins._tasks import TaskObjectType, TaskTab
from heracles_plugins.audit.events import (
    AuditEvents,
    AuditSettings,
    events_for,
    format_event,
    write_event,
)
from heracles_plugins.audit.router import build_router
from heracles_plugins.audit.runner import TASK_CLASS, TASK_FILTER, AuditReport, run_audit

PLUGIN_NAME = "audit"


def virtual[A](attr: A) -> A:
    """Mark an attribute as virtual (never written to the entry)."""
    attr.stored = False  # type: ignore[attr-defined]
    return attr


class AuditTask(TaskObjectType):
    """A task purging old audit events."""

    name = "audit_task"
    label = _("Audit task")
    label_plural = _("Audit tasks")
    icon = "shield"
    filter = TASK_FILTER

    class Main(TaskTab):
        name = "main"
        acl_key = "auditTask"
        label = _("Audit")
        object_classes = ("hrcTasks", TASK_CLASS)

        audit = Section(
            _("Audit"),
            IntAttr(
                "hrcAuditTasksRetention",
                _("Retention (days)"),
                min=0,
                description=_("Events older than this are deleted; empty uses the default"),
            ),
            BooleanAttr(
                "hrcAuditSyslogEnabled",
                _("Forward events to syslog"),
                default=False,
            ),
            StringAttr(
                "hrcAuditSyslogPrefix",
                _("Syslog prefix"),
                description=_("Text put before every forwarded event"),
            ),
        )


class AuditEvent(ObjectType):
    """A recorded change (read-only)."""

    name = "audit_event"
    acl_category = "auditEvent"
    label = _("Audit event")
    label_plural = _("Audit events")
    icon = "shield"
    category = "workflow"
    creatable = False
    editable = False
    deletable = False
    filter = f"(objectClass={EVENT_CLASS})"
    main_attr = "cn"
    name_attr = "cn"
    rdn = AUDIT_RDN
    columns = (
        "hrcAuditDateTime",
        "hrcAuditAction",
        "hrcAuditObjectType",
        "hrcAuditObject",
        "hrcAuditResult",
    )
    search_attrs = (
        "hrcAuditAction",
        "hrcAuditAuthorDN",
        "hrcAuditAuthorIP",
        "hrcAuditObjectType",
        "hrcAuditObject",
        "hrcAuditAttributes",
        "hrcAuditResult",
    )

    class Main(Tab):
        name = "main"
        acl_key = "auditEvent"
        label = _("Audit event")
        object_classes = (EVENT_CLASS,)

        event = Section(
            _("Event"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Identifier"), readonly=True),
            DateTimeAttr("hrcAuditDateTime", _("Date"), readonly=True),
            StringAttr("hrcAuditAction", _("Action"), readonly=True),
            ObjectRefAttr("hrcAuditAuthorDN", _("Author"), ref_type="user", readonly=True),
            StringAttr("hrcAuditAuthorIP", _("Author address"), readonly=True),
            StringAttr("hrcAuditObjectType", _("Object type"), readonly=True),
            StringAttr("hrcAuditObject", _("Object"), readonly=True),
            ListAttr(
                "hrcAuditAttributes",
                _("Attributes"),
                StringAttr("attribute", _("Attribute")),
                readonly=True,
            ),
            StringAttr("hrcAuditResult", _("Result"), readonly=True),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            ctx.error("cn", _("Audit events are written by Heracles and cannot be edited."))


def plugin() -> Plugin:
    """Entry point of the audit plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(AuditTask, AuditEvent),
        required_object_classes=(EVENT_CLASS,),
        settings=AuditSettings(),
        object_events=(_audit_events,),
        api_routers=(build_router,),
    )


def _audit_events(ctx: EventsContext) -> AuditEvents:
    """Record every change made through the object service."""
    settings = ctx.settings if isinstance(ctx.settings, AuditSettings) else AuditSettings()
    return AuditEvents(
        ctx.directory, author_dn=ctx.user_dn, author_ip=ctx.client_ip, settings=settings
    )


__all__ = [
    "AuditEvent",
    "AuditEvents",
    "AuditReport",
    "AuditSettings",
    "AuditTask",
    "events_for",
    "format_event",
    "plugin",
    "run_audit",
    "write_event",
]
