"""Assemble a scheduler for the web application or for the stand-alone worker."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from fastapi import FastAPI

from heracles.auth.mail import Mailer, MailSettings
from heracles.storage import Database
from heracles.storage.database import MEMORY
from heracles.tasks.scheduler import Scheduler, SchedulerThread, TaskStore
from heracles.tasks.syslog import configure_audit_syslog

if TYPE_CHECKING:
    from heracles.api.state import AppState

__all__ = ["attach_scheduler", "build_worker", "task_store"]


def attach_scheduler(
    app: FastAPI,
    *,
    mailer: Mailer | None = None,
    interval: float = 60.0,
    start: bool = True,
) -> Scheduler:
    """Create the application's in-process scheduler (``app.state.scheduler``).

    With ``start`` a background thread runs a pass every ``interval`` seconds. Without a
    configured database the lease and the reports live in memory (demo, tests).
    """
    state: AppState = app.state.heracles
    store = task_store(app) or TaskStore(Database(MEMORY))
    app.state.task_store = store
    scheduler = Scheduler(
        app.state.domain.registry,
        state.directories,
        store,
        mailer=mailer,
        base_url=state.settings.recovery.base_url,
    )
    app.state.scheduler = scheduler
    if start:
        thread = SchedulerThread(scheduler, interval)
        app.state.scheduler_thread = thread
        thread.start()
    return scheduler


def task_store(app: FastAPI) -> TaskStore | None:
    """The run reports of the application database (``None`` without a database)."""
    existing: TaskStore | None = getattr(app.state, "task_store", None)
    if existing is not None:
        return existing
    state: AppState = app.state.heracles
    if state.database is None:
        return None
    store = TaskStore(state.database)
    app.state.task_store = store
    return store


def build_worker(config_path: str | os.PathLike[str] | None = None) -> Scheduler:
    """A scheduler for the stand-alone ``heracles worker`` from the configuration file."""
    from heracles.objects import TypeRegistry
    from heracles.objects.builtin import register_builtin_types
    from heracles.server import load_config

    raw, api_settings, directories = load_config(config_path)
    configure_audit_syslog(raw.get("audit"))
    registry = TypeRegistry()
    register_builtin_types(registry)
    if directories:
        registry.load_plugins(next(iter(directories.values())))
    database = Database(api_settings.database.path or MEMORY)
    return Scheduler(
        registry,
        directories,
        TaskStore(database),
        mailer=MailSettings.model_validate(raw.get("mail") or {}).build(),
        base_url=api_settings.recovery.base_url,
    )
