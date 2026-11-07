"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from heracles.attributes import set_default_password_checker


@pytest.fixture(autouse=True)
def _reset_password_checker() -> Iterator[None]:
    """Apps built in tests install a process-wide password policy check: reset it."""
    yield
    set_default_password_checker(None)
