"""Archive task runner: purge archives older than the retention."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from heracles.ldap.client import DirectoryClient, Entry
from heracles_plugins._tasks import TaskReport, purge_older_than, run_tasks, task_filter, utc
from heracles_plugins.archive.service import (
    ARCHIVE_CLASS,
    ArchiveSettings,
    archive_container,
)

TASK_CLASS = "fdArchiveTasks"
TASK_FILTER = task_filter(TASK_CLASS)


@dataclass(slots=True)
class ArchiveReport(TaskReport):
    """What an archive run did."""

    archives_purged: int = 0


def run_archive(
    directory: DirectoryClient, now: datetime, settings: ArchiveSettings | None = None
) -> ArchiveReport:
    """Run every due archive task: delete the archives older than ``settings.retention_days``."""
    settings = settings or ArchiveSettings()
    now = utc(now)
    report = ArchiveReport()

    def process(_task: Entry) -> bool:
        if settings.retention_days > 0:
            report.archives_purged += purge_older_than(
                directory,
                archive_container(directory),
                ARCHIVE_CLASS,
                "fdArchivedDateTime",
                now - timedelta(days=settings.retention_days),
                report.errors,
            )
        return True

    run_tasks(directory, TASK_FILTER, now, process, report)
    return report
