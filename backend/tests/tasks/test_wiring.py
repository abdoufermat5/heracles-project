"""Audit syslog wiring, the worker command and "Run now"."""

from __future__ import annotations

import logging
import logging.handlers
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
from heracles.tasks.syslog import AUDIT_LOGGER, configure_audit_syslog, syslog_configured
from heracles.tasks.wiring import attach_scheduler


@pytest.fixture(autouse=True)
def clean_audit_logger() -> Iterator[None]:
    yield
    configure_audit_syslog(None)


def test_syslog_handler_is_bound_and_removed() -> None:
    assert not syslog_configured()
    assert configure_audit_syslog({"syslog": {"address": "127.0.0.1:5514", "facility": "local3"}})
    assert syslog_configured()
    handlers = logging.getLogger(AUDIT_LOGGER).handlers
    assert sum(isinstance(h, logging.handlers.SysLogHandler) for h in handlers) == 1
    # configuring again replaces the handler instead of stacking another one
    assert configure_audit_syslog({"syslog": {"address": "127.0.0.1:5514"}})
    assert len(logging.getLogger(AUDIT_LOGGER).handlers) == len(handlers)
    assert not configure_audit_syslog({})
    assert not syslog_configured()


def test_syslog_bad_facility_is_not_configured() -> None:
    assert not configure_audit_syslog({"syslog": {"address": "127.0.0.1:1", "facility": "nope"}})
    assert not syslog_configured()


class FakeScheduler(Scheduler):
    def __init__(self) -> None:  # pyright: ignore[reportMissingSuperCall]
        self.passes = 0

    def run_pass(self, directory_ids: Any = None) -> list[RunRecord] | None:
        self.passes += 1
        return []


def test_worker_once_runs_a_single_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeScheduler()

    def build(_config: str | None = None) -> Scheduler:
        return fake

    monkeypatch.setattr(wiring, "build_worker", build)
    assert main(["worker", "--once", "--config", "ignored.yaml"]) == 0
    assert fake.passes == 1


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
        assert "audit" in {run["runner"] for run in ran["runs"]}

        runs = client.get("/api/v2/admin/tasks/runs").json()["runs"]
        assert runs and runs[0]["runner"]
        listing = client.get("/api/v2/admin/tasks").json()
        assert listing["capabilities"]["scheduler_in_process"] is True
        assert listing["capabilities"]["syslog_configured"] is False
        row = listing["tasks"][0]
        assert row["last_report"]["status"] in ("ok", "error")
