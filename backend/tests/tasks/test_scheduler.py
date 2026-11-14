"""Scheduler passes, the lease, run reports and the plugins' runner registration."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field

import pytest
from structlog.testing import capture_logs

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
    assert failed.status == "error" and "boom" in failed.errors[0] and failed.reason is None
    reported = next(r for r in recent if r.runner == "r")
    assert reported.errors == ["bad task"] and reported.reason is None
    assert set(scheduler.store.last_by_kind()) == {"kf", "kr"}
    assert recent[0].as_dict()["summary"] == "1 error(s)"


def test_runner_needing_a_mailer_is_skipped_without_one() -> None:
    calls: list[str] = []

    def run(_ctx: TaskRunContext) -> FakeReport:
        calls.append("run")
        return FakeReport()

    runner = TaskRunner("mailing", run, kind="k", needs_mailer=True)
    scheduler = make(runner)
    with capture_logs() as logs:
        skipped = scheduler.run_pass(["a"])
    assert skipped is not None and skipped[0].status == "skipped" and not calls
    record = skipped[0]
    assert record.errors == [] and record.reason and "no mail server" in record.reason
    assert any(
        entry["event"] == "tasks.runner_skipped" and entry["log_level"] == "info" for entry in logs
    )
    (stored,) = scheduler.store.recent()
    assert (stored.status, list(stored.errors), stored.reason) == ("skipped", [], record.reason)
    assert stored.reason_key == "no_mailer" == record.reason_key
    assert stored.as_dict()["reason"] == record.reason
    assert stored.as_dict()["reason_key"] == "no_mailer"
    ran = make(runner, mailer=MemoryMailer()).run_pass(["a"])
    assert ran is not None and ran[0].status == "ok" and ran[0].reason is None and calls == ["run"]


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


def test_registry_provider_is_read_at_every_pass() -> None:
    """A plugin switched off in the console (registry swapped) stops running its tasks."""
    calls: list[str] = []

    def run(_ctx: TaskRunContext) -> FakeReport:
        calls.append("run")
        return FakeReport()

    with_runner = TypeRegistry()
    with_runner.task_runners.append(("demo", TaskRunner("one", run, kind="k")))
    current = {"registry": with_runner}
    scheduler = Scheduler(
        lambda: current["registry"],
        {"a": MemoryDirectory("dc=a")},
        TaskStore(Database(":memory:")),
    )
    assert scheduler.run_pass() is not None and calls == ["run"]
    current["registry"] = TypeRegistry()  # the plugin was disabled
    assert scheduler.run_pass() == [] and calls == ["run"]


def test_pass_limited_to_kinds() -> None:
    seen: list[str] = []

    def run(ctx: TaskRunContext) -> FakeReport:
        del ctx
        return FakeReport()

    def one(ctx: TaskRunContext) -> FakeReport:
        seen.append(ctx.directory.base_dn)
        return FakeReport()

    scheduler = make(TaskRunner("one", one, kind="k1"), TaskRunner("two", run, kind="k2"))
    runs = scheduler.run_pass(["a"], kinds=["k1"])
    assert runs is not None and [r.kind for r in runs] == ["k1"] and seen == ["dc=a"]


def _timed_scheduler(now: list[float], *runners: TaskRunner) -> tuple[Scheduler, TaskStore]:
    registry = TypeRegistry()
    registry.task_runners.extend(("demo", r) for r in runners)
    store = TaskStore(Database(":memory:"), clock=lambda: now[0])
    scheduler = Scheduler(registry, {"a": MemoryDirectory("dc=a")}, store, lease_seconds=600)
    return scheduler, store


def test_a_long_pass_renews_its_lease() -> None:
    now = [100.0]
    stolen: list[bool] = []
    ran: list[str] = []

    def slow(name: str, others_try: bool) -> TaskRunner:
        def run(_ctx: TaskRunContext) -> FakeReport:
            ran.append(name)
            now[0] += 400.0  # each runner takes 400 s: the pass outlives one 600 s lease
            if others_try:
                stolen.append(store.acquire_lease("other", 600))
            return FakeReport()

        return TaskRunner(name, run)

    scheduler, store = _timed_scheduler(now, slow("r1", False), slow("r2", True), slow("r3", False))
    runs = scheduler.run_pass()
    assert runs is not None and ran == ["r1", "r2", "r3"]
    assert stolen == [False]  # without renewal the first lease would have expired at 700


def test_a_pass_stops_when_its_lease_was_taken_over() -> None:
    now = [100.0]
    ran: list[str] = []

    def first(_ctx: TaskRunContext) -> FakeReport:
        ran.append("first")
        now[0] += 700.0  # the lease expires, another replica takes it
        assert store.acquire_lease("other", 600)
        return FakeReport()

    def second(_ctx: TaskRunContext) -> FakeReport:
        ran.append("second")
        return FakeReport()

    scheduler, store = _timed_scheduler(
        now, TaskRunner("first", first), TaskRunner("second", second)
    )
    runs = scheduler.run_pass()
    assert runs is not None and [r.runner for r in runs] == ["first"]
    assert ran == ["first"]
