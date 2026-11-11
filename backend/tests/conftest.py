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


@pytest.fixture(autouse=True)
def _all_plugins_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apps built without a ``plugins.enabled`` list expose every plugin the schema supports.

    Production defaults to the small core profile; most API tests exercise one plugin each
    and should not have to list it. Tests of the profile itself restore the real value.
    """
    monkeypatch.setattr("heracles.objects.activation.CORE_PROFILE", ("*",))
