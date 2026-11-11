"""Archive plugin: keep a copy of selected attributes of an object before it is deleted.

Provides the read-only ``archived_object`` type (entries below ``ou=archive``, ACL
``archivedObject/archivedObject``), the ``archive_task`` type purging old archives
(:func:`run_archive`), the service function :func:`archive` and the router
``POST /api/v2/archive/{type}/{dn}`` for users allowed to delete the object.

Integration notes for the framework owners:

* The UI (or the API client) calls the endpoint, then ``DELETE /objects/...``. To archive
  automatically, pass ``ArchiveBeforeDelete(directory, settings)`` as ``events=`` of the
  ``ObjectService`` handling deletions.
* Scheduler / CLI: ``run_archive(directory, datetime.now(UTC), registry.settings["archive"])``.
* Per type rules (kept attributes, unique key) are ``ArchiveSettings.rules``.
"""

from __future__ import annotations

from heracles.attributes import DateTimeAttr, DepartmentAttr, ListAttr, StringAttr
from heracles.i18n import _
from heracles.objects import ObjectType, Plugin, Section, Tab
from heracles.objects.hooks import TabContext
from heracles.objects.policy import NullEvents, ObjectEvents
from heracles.objects.registry import EventsContext
from heracles_plugins._tasks import TaskObjectType, TaskTab
from heracles_plugins.archive.router import build_router
from heracles_plugins.archive.runner import (
    TASK_CLASS,
    TASK_FILTER,
    ArchiveReport,
    run_archive,
)
from heracles_plugins.archive.service import (
    ARCHIVE_CLASS,
    ARCHIVE_RDN,
    ArchiveBeforeDelete,
    ArchiveError,
    ArchiveRule,
    ArchiveSettings,
    archive,
    find_archives,
)

PLUGIN_NAME = "archive"


class ArchiveTask(TaskObjectType):
    """A task purging old archives."""

    name = "archive_task"
    label = _("Archive task")
    label_plural = _("Archive tasks")
    icon = "archive"
    filter = TASK_FILTER

    class Main(TaskTab):
        name = "main"
        acl_key = "archiveTask"
        label = _("Archive")
        object_classes = ("hrcTasks", TASK_CLASS)


class ArchivedObject(ObjectType):
    """An archived object (read-only)."""

    name = "archived_object"
    acl_category = "archivedObject"
    label = _("Archived object")
    label_plural = _("Archived objects")
    icon = "archive"
    category = "workflow"
    filter = f"(objectClass={ARCHIVE_CLASS})"
    main_attr = "cn"
    name_attr = "cn"
    rdn = ARCHIVE_RDN
    columns = ("cn", "hrcArchivedObjectType", "hrcArchivedOriginDn", "hrcArchivedDateTime")
    search_attrs = ("cn", "hrcArchivedObjectType", "hrcArchivedOriginDn", "hrcArchivedUniqueField")

    class Main(Tab):
        name = "main"
        acl_key = "archivedObject"
        label = _("Archived object")
        object_classes = (ARCHIVE_CLASS,)

        archived = Section(
            _("Archive"),
            DepartmentAttr("base", _("Department")),
            StringAttr("cn", _("Identifier"), readonly=True),
            DateTimeAttr("hrcArchivedDateTime", _("Archived on"), readonly=True),
            StringAttr("hrcArchivedObjectType", _("Object type"), readonly=True),
            StringAttr("hrcArchivedOriginDn", _("Original DN"), readonly=True),
            ListAttr(
                "hrcArchivedUniqueField",
                _("Unique fields"),
                StringAttr("field", _("Field")),
                readonly=True,
            ),
            ListAttr(
                "hrcArchivedField",
                _("Archived fields"),
                StringAttr("field", _("Field")),
                readonly=True,
            ),
        )

        @classmethod
        def prepare(cls, ctx: TabContext) -> None:
            ctx.error("cn", _("Archives are written by Heracles and cannot be edited."))


def plugin() -> Plugin:
    """Entry point of the archive plugin."""
    return Plugin(
        name=PLUGIN_NAME,
        version="0.1.0",
        types=(ArchiveTask, ArchivedObject),
        required_object_classes=(ARCHIVE_CLASS,),
        settings=ArchiveSettings(),
        api_routers=(build_router,),
        object_events=(_archive_events,),
    )


def _archive_events(ctx: EventsContext) -> ObjectEvents:
    """Archive before deletion when ``archive_on_delete`` is enabled."""
    settings = ctx.settings if isinstance(ctx.settings, ArchiveSettings) else ArchiveSettings()
    if not settings.archive_on_delete:
        return NullEvents()
    return ArchiveBeforeDelete(ctx.directory, settings)


__all__ = [
    "ArchiveBeforeDelete",
    "ArchiveError",
    "ArchiveReport",
    "ArchiveRule",
    "ArchiveSettings",
    "ArchiveTask",
    "ArchivedObject",
    "archive",
    "find_archives",
    "plugin",
    "run_archive",
]
