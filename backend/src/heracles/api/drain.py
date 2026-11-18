"""Draining before shutdown: ``/readyz`` answers 503 while the server still serves.

uvicorn stops accepting connections as soon as it handles SIGTERM, which is before the
application's lifespan shutdown runs: a load balancer that watches ``/readyz`` would only learn
about the stop once connections are refused. :func:`install` therefore wraps the SIGTERM handler
uvicorn installed: it flips the draining flag at once, keeps serving for the drain period, then
hands the signal to uvicorn, which finishes the requests in flight and stops. SIGINT (Ctrl-C)
is not delayed.
"""

from __future__ import annotations

import os
import signal
import threading
from types import FrameType

import structlog

log = structlog.get_logger(__name__)

DRAIN_ENV = "HERACLES_DRAIN_SECONDS"
DEFAULT_DRAIN_SECONDS = 5.0

_draining = threading.Event()


def is_draining() -> bool:
    return _draining.is_set()


def begin() -> None:
    _draining.set()


def reset() -> None:
    _draining.clear()


def drain_seconds() -> float:
    """The drain period (``HERACLES_DRAIN_SECONDS``; 0 stops at once)."""
    raw = os.environ.get(DRAIN_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_DRAIN_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        log.warning("drain.invalid_seconds", value=raw)
        return DEFAULT_DRAIN_SECONDS


def install() -> None:
    """Wrap the SIGTERM handler of the running server (main thread only; else a no-op)."""
    if threading.current_thread() is not threading.main_thread():
        return
    previous = signal.getsignal(signal.SIGTERM)
    if not callable(previous):
        return
    seconds = drain_seconds()

    def handler(signum: int, frame: FrameType | None) -> None:
        if is_draining():  # a second SIGTERM: stop now
            previous(signum, frame)
            return
        begin()
        log.info("drain.started", seconds=seconds)
        if seconds <= 0:
            previous(signum, frame)
            return
        timer = threading.Timer(seconds, previous, args=(signum, frame))
        timer.daemon = True
        timer.start()

    signal.signal(signal.SIGTERM, handler)
