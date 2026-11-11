"""Scheduler passes, the lease, run reports and the plugins' runner registration."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field

import pytest

from heracles.auth.mail import MemoryMailer
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.objects.task_runner import TaskRunContext, TaskRunner
from heracles.storage import Database
from heracles.tasks.scheduler import RunRecord, Scheduler, TaskStore


@dataclass
class FakeReport:
    tasks_run: int = 0
    records: list[str] = field(default_factory=lambda: [])
    errors: list[str] = field(default_factory=lambda: [])


def make(
    *runners: TaskRunner, mailer: MemoryMailer | None = None, db: Database | None = None
) -> Scheduler:
    registry = TypeRegistry()
    registry.settings["demo"] = "settings-of-demo"
    registry.task_runners.extend(("demo", r) for r in runners)
    directories = {"a": MemoryDirectory("dc=a"), "b": MemoryDirectory("dc=b")}
    store = TaskStore(db or Database(":memory:"))
    return Scheduler(registry, directories, store, mailer=mailer, base_url="https://h.test")


def test_pass_calls_each_runner_for_each_directory() -> None:
    seen: list[tuple[str, str, object]] = []

    def run(ctx: TaskRunContext) -> FakeReport:
        seen.append((ctx.directory.base_dn, ctx.base_url, ctx.settings))
        return FakeReport(tasks_run=2, records=["x", "y", "z"])

    scheduler = make(TaskRunner("one", run, kind="k1"), TaskRunner("two", run, kind="k2"))
    runs = scheduler.run_pass()
    assert runs is not None and len(runs) == 4
    assert {s[0] for s in seen} == {"dc=a", "dc=b"} and len(seen) == 4
    assert all(s[1:] == ("https://h.test", "settings-of-demo") for s in seen)
    assert runs[0].status == "ok" and runs[0].counts == {"tasks_run": 2, "records": 3}
    only_b = scheduler.run_pass(["b"])
    assert only_b is not None and {r.directory for r in only_b} == {"b"}


def test_reports_are_recorded_and_pruned() -> None:
    def failing(_ctx: TaskRunContext) -> FakeReport:
        raise RuntimeError("boom")

    def reporting(_ctx: TaskRunContext) -> FakeReport:
        return FakeReport(errors=["bad task"])

    scheduler = make(TaskRunner("f", failing, kind="kf"), TaskRunner("r", reporting, kind="kr"))
    scheduler.store.keep = 3
    scheduler.run_pass(["a"])
    scheduler.run_pass(["a"])
    recent = scheduler.store.recent()
    assert len(recent) == 3 and recent[0].runner == "r"
    failed = next(r for r in recent if r.runner == "f")
    assert failed.status == "error" and "boom" in failed.errors[0]
    assert next(r for r in recent if r.runner == "r").errors == ["bad task"]
    assert set(scheduler.store.last_by_kind()) == {"kf", "kr"}
    assert recent[0].as_dict()["summary"] == "1 error(s)"


def test_runner_needing_a_mailer_is_skipped_without_one() -> None:
    calls: list[str] = []

    def run(_ctx: TaskRunContext) -> FakeReport:
        calls.append("run")
        return FakeReport()

    runner = TaskRunner("mailing", run, kind="k", needs_mailer=True)
    skipped = make(runner).run_pass(["a"])
    assert skipped is not None and skipped[0].status == "skipped" and not calls
    assert "no mail server" in skipped[0].errors[0]
    ran = make(runner, mailer=MemoryMailer()).run_pass(["a"])
    assert ran is not None and ran[0].status == "ok" and calls == ["run"]


def test_lease_prevents_concurrent_passes() -> None:
    db = Database(":memory:")
    inner: list[list[RunRecord] | None] = []

    def run(_ctx: TaskRunContext) -> FakeReport:
        # another worker sharing the database tries a pass while this one is running
        inner.append(other.run_pass())
        return FakeReport()

    first = make(TaskRunner("slow", run), db=db)
    other = make(TaskRunner("slow", run), db=db)
    assert first.run_pass(["a"]) is not None
    assert inner == [None]
    # the lease was released: the other worker can run now
    assert other.run_pass(["a"]) is not None and len(inner) == 2


def test_expired_lease_is_taken_over() -> None:
    now = [100.0]
    store = TaskStore(Database(":memory:"), clock=lambda: now[0])
    assert store.acquire_lease("w1", ttl=10)
    assert not store.acquire_lease("w2", ttl=10)
    now[0] = 111.0
    assert store.acquire_lease("w2", ttl=10)
    store.release_lease("w1")  # not the owner: no effect
    assert not store.acquire_lease("w3", ttl=10)


PLUGINS = {
    "heracles_plugins.archive": ("archive", "archive_task", False),
    "heracles_plugins.audit": ("audit", "audit_task", False),
    "heracles_plugins.automatic_groups": ("automatic_groups", "automatic_groups_task", False),
    "heracles_plugins.lifecycle": ("lifecycle", "lifecycle_task", False),
    "heracles_plugins.notifications": ("notifications", "notifications_task", True),
    "heracles_plugins.extractor": ("extractor", "extractor_task", True),
    "heracles_plugins.user_reminder": ("user_reminder", "reminder_task", True),
}


@pytest.mark.parametrize("module", sorted(PLUGINS))
def test_each_plugin_registers_its_runner(module: str) -> None:
    name, kind, needs_mailer = PLUGINS[module]
    plugin = importlib.import_module(module).plugin()
    (runner,) = plugin.task_runners
    assert (runner.name, runner.kind, runner.needs_mailer) == (name, kind, needs_mailer)
    registry = TypeRegistry()
    registry.register_plugins([plugin], {c.lower() for c in plugin.required_object_classes})
    assert [(n, r.name) for n, r in registry.task_runners] == [(name, name)]


def test_runners_run_against_an_empty_directory() -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    for module in PLUGINS:
        plugin = importlib.import_module(module).plugin()
        registry.settings.setdefault(plugin.name, plugin.settings)
        registry.task_runners.extend((plugin.name, r) for r in plugin.task_runners)
    scheduler = Scheduler(
        registry,
        {"main": MemoryDirectory("dc=t")},
        TaskStore(Database(":memory:")),
        mailer=MemoryMailer(),
        base_url="https://h.test",
    )
    runs = scheduler.run_pass()
    assert runs is not None and len(runs) == len(PLUGINS)
    assert [r.errors for r in runs if r.status != "ok"] == []
