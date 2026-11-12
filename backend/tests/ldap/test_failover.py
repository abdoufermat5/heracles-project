"""Server selection, backoff and failover of PyLdapDirectory with a stub ``ldap`` module."""

from __future__ import annotations

from types import ModuleType
from typing import Any

import pytest

from heracles.ldap import pyldap
from heracles.ldap.client import DirectoryUnavailableError, NoSuchObjectError
from heracles.ldap.config import DirectoryConfig, load_settings


class _LdapError(Exception):
    pass


class SERVER_DOWN(_LdapError):  # noqa: N801, N818
    pass


class REFERRAL(_LdapError):  # noqa: N818
    pass


class NO_SUCH_OBJECT(_LdapError):  # noqa: N801, N818
    pass


def _make_stub(behaviour: dict[str, str]) -> tuple[ModuleType, list[tuple[str, str]]]:
    """``behaviour[uri]``: ``ok`` | ``down`` | ``readonly``. Records ``(uri, call)``."""
    calls: list[tuple[str, str]] = []
    mod = ModuleType("ldap")
    for name in (
        "TIMEOUT",
        "UNAVAILABLE",
        "CONNECT_ERROR",
        "INVALID_CREDENTIALS",
        "ALREADY_EXISTS",
        "SIZELIMIT_EXCEEDED",
        "UNWILLING_TO_PERFORM",
    ):
        setattr(mod, name, type(name, (_LdapError,), {}))
    mod.LDAPError = _LdapError  # type: ignore[attr-defined]
    mod.SERVER_DOWN = SERVER_DOWN  # type: ignore[attr-defined]
    mod.REFERRAL = REFERRAL  # type: ignore[attr-defined]
    mod.NO_SUCH_OBJECT = NO_SUCH_OBJECT  # type: ignore[attr-defined]
    for const in ("VERSION3", "OPT_REFERRALS", "OPT_NETWORK_TIMEOUT", "OPT_TIMEOUT"):
        setattr(mod, const, 1)
    mod.MOD_ADD = mod.MOD_REPLACE = mod.MOD_DELETE = 0  # type: ignore[attr-defined]

    class Conn:
        def __init__(self, uri: str) -> None:
            self.uri = uri

        def set_option(self, *_a: Any) -> None: ...

        def simple_bind_s(self, *_a: Any) -> None:
            calls.append((self.uri, "bind"))
            if behaviour[self.uri] == "down":
                raise SERVER_DOWN()

        def unbind_s(self) -> None: ...

        def add_s(self, *_a: Any) -> None:
            calls.append((self.uri, "add"))
            if behaviour[self.uri] == "readonly":
                raise REFERRAL()

        def delete_s(self, *_a: Any) -> None:
            raise NO_SUCH_OBJECT()

    mod.initialize = Conn  # type: ignore[attr-defined]
    return mod, calls


class Clock:
    now = 100.0

    def __call__(self) -> float:
        return self.now


def _directory(
    monkeypatch: pytest.MonkeyPatch, behaviour: dict[str, str], clock: Clock, **cfg: Any
) -> tuple[pyldap.PyLdapDirectory, list[tuple[str, str]]]:
    mod, calls = _make_stub(behaviour)
    monkeypatch.setattr(pyldap, "_import_ldap", lambda: mod)
    config = DirectoryConfig(id="d", base_dn="dc=x", **cfg)
    return pyldap.PyLdapDirectory(config, clock=clock), calls


def test_space_separated_uri_and_uris_list() -> None:
    assert DirectoryConfig(id="d", base_dn="dc=x", uri="ldap://a ldap://b").write_uris == [
        "ldap://a",
        "ldap://b",
    ]
    cfg = DirectoryConfig(id="d", base_dn="dc=x", uris=["ldap://a"], read_uris=["ldap://r"])
    assert cfg.all_uris == ["ldap://a", "ldap://r"]
    with pytest.raises(ValueError):
        DirectoryConfig(id="d", base_dn="dc=x")
    env = {"HERACLES_LDAP_URI": "ldap://a ldap://b", "HERACLES_LDAP_BASE_DN": "dc=x"}
    assert len(load_settings(environ=env).directories[0].write_uris) == 2


def test_fails_over_then_backs_off_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = Clock()
    d, calls = _directory(
        monkeypatch, {"ldap://a": "down", "ldap://b": "ok"}, clock, uri="ldap://a ldap://b"
    )
    d.add("cn=x,dc=x", {"cn": [b"x"]})
    assert ("ldap://b", "add") in calls
    assert d.server_states() == {"ldap://a": "down", "ldap://b": "up"}
    calls.clear()
    d.add("cn=y,dc=x", {"cn": [b"y"]})
    assert all(uri == "ldap://b" for uri, _ in calls)  # a is skipped during its backoff
    clock.now += 3  # backoff of 2 s elapsed
    assert d.server_states()["ldap://a"] == "up"


def test_all_down_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    d, _ = _directory(monkeypatch, {"ldap://a": "down"}, Clock(), uri="ldap://a")
    with pytest.raises(DirectoryUnavailableError):
        d.add("cn=x,dc=x", {"cn": [b"x"]})
    with pytest.raises(DirectoryUnavailableError):
        d.add("cn=x,dc=x", {"cn": [b"x"]})  # fails fast while backed off
    assert not d.writable()


def test_write_skips_read_only_server_but_read_error_is_not_failover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d, calls = _directory(
        monkeypatch, {"ldap://a": "readonly", "ldap://b": "ok"}, Clock(), uri="ldap://a ldap://b"
    )
    d.add("cn=x,dc=x", {"cn": [b"x"]})
    assert ("ldap://b", "add") in calls
    assert d.server_states() == {"ldap://a": "up", "ldap://b": "up"}  # still fine for reads
    with pytest.raises(NoSuchObjectError):
        d.delete("cn=none,dc=x")


def test_replicas_do_not_take_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    d, calls = _directory(
        monkeypatch,
        {"ldap://a": "down", "ldap://r": "ok"},
        Clock(),
        uri="ldap://a",
        read_uris=["ldap://r"],
    )
    with pytest.raises(DirectoryUnavailableError):
        d.add("cn=x,dc=x", {"cn": [b"x"]})
    assert ("ldap://r", "add") not in calls
