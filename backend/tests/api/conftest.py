from __future__ import annotations

from dataclasses import dataclass, field

import httpx2
import pytest
from fastapi.testclient import TestClient

from heracles.api.app import create_app
from heracles.api.settings import ApiSettings
from heracles.auth.mail import MemoryMailer
from heracles.auth.ratelimit import RateLimiter
from heracles.auth.recovery import InMemoryTokenStore
from heracles.auth.second_factor import InMemorySecondFactorStore
from heracles.auth.sessions import InMemorySessionStore
from tests.auth.fakes import FakeDirectory


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class Env:
    client: TestClient
    directory: FakeDirectory
    mailer: MemoryMailer
    sessions: InMemorySessionStore
    second_factor: InMemorySecondFactorStore
    tokens: InMemoryTokenStore
    clock: Clock
    user_dn: str
    csrf_token: str = ""
    logout_calls: list[str] = field(default_factory=lambda: [])

    def headers(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf_token}

    def post(self, path: str, json: object = None) -> httpx2.Response:
        return self.client.post(path, json=json, headers=self.headers())

    def login(self, username: str = "jdoe", password: str = "s3cretpass") -> httpx2.Response:
        return self.post(
            "/api/v2/auth/login",
            {"directory": "main", "username": username, "password": password},
        )


@pytest.fixture
def env() -> Env:
    clock = Clock()
    directory = FakeDirectory()
    user_dn = directory.add_user("jdoe", "s3cretpass", mail="jdoe@example.com", cn="John Doe")
    directory.add_user("other", "otherpass", mail="other@example.com")
    mailer = MemoryMailer()
    sessions = InMemorySessionStore(clock=clock)
    sf = InMemorySecondFactorStore()
    tokens = InMemoryTokenStore(clock=clock)
    logout_calls: list[str] = []
    app = create_app(
        ApiSettings(directory_labels={"main": "Main directory"}, admin_dns=[user_dn]),
        {"main": directory},
        sessions=sessions,
        second_factor_store=sf,
        token_store=tokens,
        mailer=mailer,
        limiter=RateLimiter(free_attempts=3, base_delay=2.0, max_delay=60.0, clock=clock),
        logout_hooks=[lambda s: logout_calls.append(s.user_dn)],
        clock=clock,
    )
    client = TestClient(app, base_url="https://testserver", raise_server_exceptions=False)
    result = Env(client, directory, mailer, sessions, sf, tokens, clock, user_dn)
    result.logout_calls = logout_calls
    result.csrf_token = str(client.get("/api/v2/auth/csrf").json()["token"])
    return result
