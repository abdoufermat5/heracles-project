"""Prolongation endpoint on a small FastAPI app."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import heracles_plugins.user_reminder as ur
from heracles.auth.ratelimit import RateLimiter
from heracles.ldap.memory import MemoryDirectory

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)
EPOCH = date(1970, 1, 1)
EXPIRE = NOW.date() + timedelta(days=5)


class Env:
    def __init__(self) -> None:
        self.directory = MemoryDirectory(BASE)
        self.directory.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
        self.directory.add(PEOPLE, {"objectClass": [b"organizationalUnit"], "ou": [b"people"]})
        self.dn = f"uid=jdoe,{PEOPLE}"
        self.directory.add(
            self.dn,
            {
                "objectClass": [b"inetOrgPerson", b"shadowAccount"],
                "uid": [b"jdoe"],
                "cn": [b"J"],
                "sn": [b"D"],
                "shadowExpire": [str((EXPIRE - EPOCH).days).encode()],
            },
        )
        self.token = ur.create_prolongation_token(self.directory, self.dn, now=NOW, valid_days=7)
        self.now = NOW.timestamp()
        self.settings = ur.UserReminderSettings(prolongation_days=10)
        app = FastAPI()
        app.include_router(
            ur.build_prolong_router(
                lambda: self.directory,
                self.settings,
                clock=lambda: self.now,
                limiter=RateLimiter(free_attempts=2, clock=lambda: 0.0),
            )
        )
        self.client = TestClient(app)

    def prolong(self, login: str = "jdoe", token: str | None = None) -> tuple[int, dict[str, str]]:
        r = self.client.post(
            "/api/v2/reminder/prolong", json={"login": login, "token": token or self.token}
        )
        return r.status_code, r.json()


@pytest.fixture
def env() -> Env:
    return Env()


def test_prolong_ok_then_reuse_fails(env: Env) -> None:
    status, body = env.prolong()
    assert status == 200
    assert body == {"status": "ok", "new_expiration": (EXPIRE + timedelta(days=10)).isoformat()}
    assert env.prolong()[0] == 400


def test_prolong_uses_configured_days(env: Env) -> None:
    env.settings.prolongation_days = 45
    assert env.prolong()[1]["new_expiration"] == (EXPIRE + timedelta(days=45)).isoformat()


def test_prolong_rejects_expired_token_and_wrong_user(env: Env) -> None:
    assert env.prolong(login="nobody")[0] == 400
    env.now += 8 * 86400
    assert env.prolong()[0] == 400


def test_prolong_validates_body_and_rate_limits(env: Env) -> None:
    assert env.client.post("/api/v2/reminder/prolong", json={"login": "x"}).status_code == 422
    assert env.prolong(token="bad")[0] == 400
    assert env.prolong(token="bad")[0] == 400
    r = env.client.post("/api/v2/reminder/prolong", json={"login": "jdoe", "token": env.token})
    assert r.status_code == 429 and "retry-after" in r.headers
