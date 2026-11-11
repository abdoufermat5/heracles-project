"""The task scheduler: runs the plugins' task runners against every directory.

One *pass* calls every registered :class:`~heracles.objects.task_runner.TaskRunner` once per
directory; each runner picks the tasks that are due (``hrcTasksNextExec``) and reschedules
them, so passes can simply be repeated at a fixed interval (``heracles worker``) or on
demand ("Run now").

Two workers must not run tasks concurrently: a pass first takes a *lease* stored in the
application database (with an expiry, so a crashed worker does not block the others for
long). The outcome of every runner is recorded in the same database; only the most recent
runs are kept.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence, Sized
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import structlog

from heracles.auth.mail import Mailer
from heracles.ldap.client import DirectoryClient
from heracles.objects.registry import TypeRegistry
from heracles.objects.task_runner import TaskRunContext, TaskRunner
from heracles.storage import Database

__all__ = [
    "LEASE_NAME",
    "TASKS_MIGRATIONS",
    "RunRecord",
    "Scheduler",
    "SchedulerThread",
    "TaskStore",
]

log = structlog.get_logger(__name__)

LEASE_NAME = "scheduler"
DEFAULT_KEEP = 200
DEFAULT_LEASE_SECONDS = 600.0

TASKS_MIGRATIONS: Sequence[str] = (
    """
    CREATE TABLE task_lease (
        name TEXT PRIMARY KEY,
        owner TEXT NOT NULL,
        expires_at REAL NOT NULL
    );
    CREATE TABLE task_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        directory TEXT NOT NULL,
        runner TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT '',
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        status TEXT NOT NULL,
        counts TEXT NOT NULL,
        errors TEXT NOT NULL
    );
    CREATE INDEX task_runs_runner ON task_runs (runner, id);
    """,
)


@dataclass(frozen=True, slots=True)
class RunRecord:
    """The outcome of one runner on one directory."""

    directory: str
    runner: str
    kind: str
    started_at: datetime
    finished_at: datetime
    #: ``ok``, ``error`` (the runner failed or reported errors) or ``skipped``.
    status: str
    counts: Mapping[str, int] = field(default_factory=lambda: {})
    errors: Sequence[str] = ()
    id: int = 0

    @property
    def summary(self) -> str:
        parts = [f"{k} {v}" for k, v in self.counts.items() if v]
        if self.errors:
            parts.append(f"{len(self.errors)} error(s)")
        return ", ".join(parts) or "nothing to do"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "directory": self.directory,
            "runner": self.runner,
            "kind": self.kind,
            "started": self.started_at.isoformat(),
            "finished": self.finished_at.isoformat(),
            "status": self.status,
            "counts": dict(self.counts),
            "errors": list(self.errors),
            "summary": self.summary,
        }


def _counts_of(report: object) -> dict[str, int]:
    """Counters of a task report: its integer fields, and the length of its lists."""
    if not dataclasses.is_dataclass(report) or isinstance(report, type):
        return {}
    out: dict[str, int] = {}
    for f in dataclasses.fields(report):
        if f.name == "errors":
            continue
        value = getattr(report, f.name)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            out[f.name] = value
        elif isinstance(value, list | tuple | set | dict):
            out[f.name] = len(cast("Sized", value))
    return out


def _errors_of(report: object) -> list[str]:
    errors = getattr(report, "errors", None)
    if isinstance(errors, list):
        return [str(e) for e in cast("list[object]", errors)]
    return []


class TaskStore:
    """Lease and run reports in the application database (component ``tasks``)."""

    def __init__(
        self,
        database: Database,
        *,
        keep: int = DEFAULT_KEEP,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._db = database
        self.keep = keep
        self._clock = clock
        database.migrate("tasks", TASKS_MIGRATIONS)

    # -- lease ---------------------------------------------------------------------------------
    def acquire_lease(self, owner: str, ttl: float, name: str = LEASE_NAME) -> bool:
        """Take the lease unless another owner holds an unexpired one."""
        now = self._clock()
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT owner, expires_at FROM task_lease WHERE name = ?", (name,)
            ).fetchone()
            if row is not None and row["owner"] != owner and row["expires_at"] > now:
                return False
            conn.execute(
                "INSERT INTO task_lease (name, owner, expires_at) VALUES (?, ?, ?)"
                " ON CONFLICT(name) DO UPDATE SET owner = excluded.owner,"
                " expires_at = excluded.expires_at",
                (name, owner, now + ttl),
            )
        return True

    def release_lease(self, owner: str, name: str = LEASE_NAME) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM task_lease WHERE name = ? AND owner = ?", (name, owner))

    # -- reports -------------------------------------------------------------------------------
    def record(self, run: RunRecord) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO task_runs (directory, runner, kind, started_at, finished_at,"
                " status, counts, errors) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.directory,
                    run.runner,
                    run.kind,
                    run.started_at.isoformat(),
                    run.finished_at.isoformat(),
                    run.status,
                    json.dumps(dict(run.counts)),
                    json.dumps(list(run.errors)),
                ),
            )
            conn.execute(
                "DELETE FROM task_runs WHERE id <= (SELECT MAX(id) FROM task_runs) - ?",
                (self.keep,),
            )

    def recent(self, limit: int = 50, *, directory: str | None = None) -> list[RunRecord]:
        """Most recent runs first."""
        sql = "SELECT * FROM task_runs"
        args: list[Any] = []
        if directory is not None:
            sql += " WHERE directory = ?"
            args.append(directory)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(max(1, limit))
        with self._db.connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_record_of(r) for r in rows]

    def last_by_kind(self, directory: str | None = None) -> dict[str, RunRecord]:
        """The latest run of each task kind."""
        out: dict[str, RunRecord] = {}
        for run in self.recent(self.keep, directory=directory):
            if run.kind and run.kind not in out:
                out[run.kind] = run
        return out


def _record_of(row: Any) -> RunRecord:
    return RunRecord(
        id=int(row["id"]),
        directory=row["directory"],
        runner=row["runner"],
        kind=row["kind"],
        started_at=datetime.fromisoformat(row["started_at"]),
        finished_at=datetime.fromisoformat(row["finished_at"]),
        status=row["status"],
        counts=json.loads(row["counts"]),
        errors=json.loads(row["errors"]),
    )


class Scheduler:
    """Runs every task runner of the registry against the configured directories."""

    def __init__(
        self,
        registry: TypeRegistry,
        directories: Mapping[str, DirectoryClient],
        store: TaskStore,
        *,
        mailer: Mailer | None = None,
        base_url: str = "",
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.registry = registry
        self.directories = directories
        self.store = store
        self.mailer = mailer
        self.base_url = base_url
        self._lease_seconds = lease_seconds
        self._now = now

    def run_pass(self, directory_ids: Iterable[str] | None = None) -> list[RunRecord] | None:
        """One pass; ``None`` when another worker holds the lease (nothing was run)."""
        owner = uuid.uuid4().hex
        if not self.store.acquire_lease(owner, self._lease_seconds):
            log.info("tasks.pass_skipped", reason="lease held by another worker")
            return None
        try:
            wanted = None if directory_ids is None else set(directory_ids)
            runs: list[RunRecord] = []
            for dir_id, directory in self.directories.items():
                if wanted is not None and dir_id not in wanted:
                    continue
                for plugin_name, runner in self.registry.task_runners:
                    run = self._run_one(dir_id, directory, plugin_name, runner)
                    self.store.record(run)
                    runs.append(run)
            return runs
        finally:
            self.store.release_lease(owner)

    def _run_one(
        self, dir_id: str, directory: DirectoryClient, plugin_name: str, runner: TaskRunner
    ) -> RunRecord:
        started = self._now()
        if runner.needs_mailer and self.mailer is None:
            log.warning("tasks.runner_skipped", runner=runner.name, reason="no mail server")
            return RunRecord(
                started_at=started,
                finished_at=started,
                status="skipped",
                errors=["no mail server is configured: the runner was skipped"],
                directory=dir_id,
                runner=runner.name,
                kind=runner.kind,
            )
        ctx = TaskRunContext(
            directory=directory,
            now=started,
            settings=self.registry.settings.get(plugin_name),
            mailer=self.mailer,
            registry=self.registry,
            base_url=self.base_url,
        )
        try:
            report = runner.run(ctx)
        except Exception as exc:
            log.exception("tasks.runner_failed", runner=runner.name, directory=dir_id)
            return RunRecord(
                started_at=started,
                finished_at=self._now(),
                status="error",
                errors=[f"{type(exc).__name__}: {exc}"],
                directory=dir_id,
                runner=runner.name,
                kind=runner.kind,
            )
        errors = _errors_of(report)
        return RunRecord(
            started_at=started,
            finished_at=self._now(),
            status="error" if errors else "ok",
            counts=_counts_of(report),
            errors=errors,
            directory=dir_id,
            runner=runner.name,
            kind=runner.kind,
        )


class SchedulerThread:
    """Calls :meth:`Scheduler.run_pass` every ``interval`` seconds in a daemon thread."""

    def __init__(self, scheduler: Scheduler, interval: float = 60.0) -> None:
        self.scheduler = scheduler
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="heracles-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float | None = 5.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scheduler.run_pass()
            except Exception:
                log.exception("tasks.pass_failed")
            self._stop.wait(self.interval)
