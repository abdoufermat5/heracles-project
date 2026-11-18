"""Readiness while the server drains before a shutdown."""

from __future__ import annotations

import os
import signal
import threading
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from heracles.api import drain
from heracles.server import build_demo_app


@pytest.fixture(autouse=True)
def clean_drain() -> Iterator[None]:
    drain.reset()
    old = signal.getsignal(signal.SIGTERM)
    yield
    signal.signal(signal.SIGTERM, old)
    drain.reset()


def test_sigterm_flips_readiness_before_the_server_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERACLES_DRAIN_SECONDS", "0.3")
    received: list[int] = []
    stopped = threading.Event()

    def uvicorn_handler(signum: int, _frame: object) -> None:  # stands for Server.handle_exit
        received.append(signum)
        stopped.set()

    signal.signal(signal.SIGTERM, uvicorn_handler)
    # the lifespan start-up installs the drain around that handler (on uvicorn's main thread;
    # the test client runs the lifespan on another one, so it is done here)
    drain.install()
    with TestClient(build_demo_app()) as client:
        assert client.get("/readyz").status_code == 200
        os.kill(os.getpid(), signal.SIGTERM)
        # the server is still up: it serves, but tells the load balancer to go away
        assert not received
        ready = client.get("/readyz")
        assert ready.status_code == 503
        assert ready.json() == {"status": "draining"}
        assert client.get("/healthz").status_code == 200
        # then the stop proceeds
        assert stopped.wait(5)
        assert received == [signal.SIGTERM]


def test_the_application_lifespan_installs_the_drain(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(drain, "install", lambda: calls.append(1))
    with TestClient(build_demo_app()):
        assert calls == [1]
