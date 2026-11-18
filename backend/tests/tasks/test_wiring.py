"""Audit syslog wiring, the worker command and "Run now"."""

from __future__ import annotations

import os
import signal
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles.cli.main import main
from heracles.demo import BASE
from heracles.server import build_demo_app
from heracles.storage import Database
from heracles.tasks import wiring
from heracles.tasks.scheduler import RunRecord, Scheduler, TaskStore
from heracles.tasks.syslog import audit_sender, configure_audit_syslog, syslog_configured
from heracles.tasks.wiring import attach_scheduler


@pytest.fixture(autouse=True)
def clean_audit_logger() -> Iterator[None]:
    yield
    configure_audit_syslog(None)


def test_syslog_sender_is_configured_and_replaced() -> None:
    assert not syslog_configured()
    assert configure_audit_syslog({"syslog": {"address": "127.0.0.1:5514", "facility": "local3"}})
    assert syslog_configured()
    first = audit_sender()
    assert first is not None and first.settings.facility == "local3"
    # configuring again replaces the sender
    assert configure_audit_syslog({"syslog": {"address": "127.0.0.1:5514"}})
    assert audit_sender() is not first
    assert not configure_audit_syslog({})
    assert not syslog_configured()


def test_syslog_bad_facility_is_not_configured() -> None:
    assert not configure_audit_syslog({"syslog": {"address": "127.0.0.1:1", "facility": "nope"}})
    assert not syslog_configured()


class FakeScheduler(Scheduler):
    def __init__(self) -> None:  # pyright: ignore[reportMissingSuperCall]
        self.passes = 0
        self.stopped = False
        self.closed = False

    def request_stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True

    def run_pass(self, directory_ids: Any = None, kinds: Any = None) -> list[RunRecord] | None:
        self.passes += 1
        return []


def test_worker_once_runs_a_single_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeScheduler()

    def build(_config: str | None = None) -> Scheduler:
        return fake

    monkeypatch.setattr(wiring, "build_worker", build)
    assert main(["worker", "--once", "--config", "ignored.yaml"]) == 0
    assert fake.passes == 1


def test_worker_sigterm_stops_the_scheduler_and_closes_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeScheduler()

    def terminate_during_pass(directory_ids: Any = None, kinds: Any = None) -> list[RunRecord]:
        fake.passes += 1
        os.kill(os.getpid(), signal.SIGTERM)  # the orchestrator stops the pod mid-pass
        return []

    monkeypatch.setattr(fake, "run_pass", terminate_during_pass)

    def build(_config: str | None = None) -> Scheduler:
        return fake

    monkeypatch.setattr(wiring, "build_worker", build)
    old = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        assert main(["worker", "--interval", "3600", "--config", "ignored.yaml"]) == 0
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)
    assert fake.passes == 1
    assert fake.stopped
    assert fake.closed


def test_worker_rejects_a_bad_interval() -> None:
    assert main(["worker", "--interval", "0"]) == 2


def dnp(dn: str) -> str:
    return quote(dn, safe="")


def test_run_now_runs_the_pass_and_exposes_reports() -> None:
    app = build_demo_app()
    with TestClient(app, base_url="http://testserver") as client:
        token = client.get("/api/v2/auth/csrf").json()["token"]
        headers = {"X-CSRF-Token": token}
        r = client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": "admin", "password": "heracles"},
            headers=headers,
        )
        assert r.status_code == 200, r.text
        headers = {"X-CSRF-Token": client.get("/api/v2/auth/csrf").json()["token"]}
        created = client.post(
            "/api/v2/objects/audit_task",
            json={"base": BASE, "tabs": {"main": {"active": True, "values": {"cn": "purge"}}}},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        dn = created.json()["dn"]

        queued = client.post(f"/api/v2/admin/tasks/{dnp(dn)}/run", headers=headers).json()
        assert queued["queued"] is True  # no scheduler in this process yet

        scheduler = attach_scheduler(app, start=False)
        scheduler.store = TaskStore(Database(":memory:"))
        app.state.task_store = scheduler.store
        ran = client.post(f"/api/v2/admin/tasks/{dnp(dn)}/run", headers=headers).json()
        assert ran["queued"] is False
        # only the runner of the task's own kind runs, not every runner of the directory
        assert {run["kind"] for run in ran["runs"]} == {"audit_task"}

        runs = client.get("/api/v2/admin/tasks/runs").json()["runs"]
        assert runs and runs[0]["runner"]
        assert all("reason" in run for run in runs)
        # a deliberate skip is not an error: the report carries the reason, not an error
        scheduler.run_pass()
        runs = client.get("/api/v2/admin/tasks/runs").json()["runs"]
        skipped = [run for run in runs if run["status"] == "skipped"]
        assert skipped and all(not run["errors"] and run["reason"] for run in skipped)
        # the sentence is translated by the client from the stable id
        assert all(run["reason_key"] == "no_mailer" for run in skipped)
        listing = client.get("/api/v2/admin/tasks").json()
        assert listing["capabilities"]["scheduler_in_process"] is True
        assert listing["capabilities"]["syslog_configured"] is False
        row = listing["tasks"][0]
        assert row["last_report"]["status"] in ("ok", "error")
