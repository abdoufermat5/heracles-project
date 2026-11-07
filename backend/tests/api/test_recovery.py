from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from heracles.ldap.client import Entry
from tests.api.conftest import Env


def _token_from_mail(env: Env) -> tuple[str, str]:
    body = env.mailer.outbox[-1].body
    match = re.search(r"https?://\S+", body)
    assert match
    query = parse_qs(urlparse(match.group(0)).query)
    return query["login"][0], query["token"][0]


def _stored_password(env: Env) -> str | None:
    entry: Entry | None = env.directory.get(env.user_dn)
    assert entry is not None
    return entry.text("userPassword")


def test_request_always_202(env: Env) -> None:
    known = env.post("/api/v2/auth/recovery", {"email": "jdoe@example.com"})
    unknown = env.post("/api/v2/auth/recovery", {"email": "nobody@example.com"})
    empty = env.post("/api/v2/auth/recovery", {"email": ""})
    bad_dir = env.post("/api/v2/auth/recovery", {"email": "jdoe@example.com", "directory": "zzz"})
    assert known.status_code == unknown.status_code == empty.status_code == 202
    assert bad_dir.status_code == 202
    assert known.json() == unknown.json()
    # only the known address received mail
    assert [m.to for m in env.mailer.outbox] == ["jdoe@example.com"]


def test_ambiguous_address_sends_nothing(env: Env) -> None:
    env.directory.add_user("twin", "pw", mail="jdoe@example.com")
    r = env.post("/api/v2/auth/recovery", {"email": "jdoe@example.com"})
    assert r.status_code == 202
    assert env.mailer.outbox == []


def test_request_still_202_when_mail_fails(env: Env) -> None:
    def boom(to: str, subject: str, body: str) -> None:
        raise OSError("smtp down")

    env.mailer.send = boom  # type: ignore[method-assign]
    r = env.post("/api/v2/auth/recovery", {"email": "jdoe@example.com"})
    assert r.status_code == 202


def test_full_recovery_flow_and_single_use(env: Env) -> None:
    env.post("/api/v2/auth/recovery", {"email": "jdoe@example.com"})
    login, token = _token_from_mail(env)
    assert login == "jdoe"

    r = env.post(
        "/api/v2/auth/recovery/confirm",
        {"login": login, "token": token, "password": "brand-new-pass"},
    )
    assert r.status_code == 200
    stored = _stored_password(env)
    assert stored is not None
    assert stored.startswith("{SSHA}")

    again = env.post(
        "/api/v2/auth/recovery/confirm",
        {"login": login, "token": token, "password": "another-pass-1"},
    )
    assert again.status_code == 422
    assert again.json()["error"]["code"] == "validation"


def test_token_expires(env: Env) -> None:
    env.post("/api/v2/auth/recovery", {"email": "jdoe@example.com"})
    login, token = _token_from_mail(env)
    env.clock.advance(11 * 60)
    r = env.post(
        "/api/v2/auth/recovery/confirm",
        {"login": login, "token": token, "password": "brand-new-pass"},
    )
    assert r.status_code == 422
    assert _stored_password(env) is None


def test_wrong_token_and_policy_violation(env: Env) -> None:
    env.post("/api/v2/auth/recovery", {"email": "jdoe@example.com"})
    login, token = _token_from_mail(env)
    wrong = env.post(
        "/api/v2/auth/recovery/confirm",
        {"login": login, "token": "wrong", "password": "brand-new-pass"},
    )
    assert wrong.status_code == 422
    weak = env.post(
        "/api/v2/auth/recovery/confirm", {"login": login, "token": token, "password": "abc"}
    )
    assert weak.status_code == 422
    assert "password" in weak.json()["error"]["fields"]
    # a policy failure does not burn the token
    ok = env.post(
        "/api/v2/auth/recovery/confirm",
        {"login": login, "token": token, "password": "brand-new-pass"},
    )
    assert ok.status_code == 200


def test_token_for_other_user_is_rejected(env: Env) -> None:
    env.post("/api/v2/auth/recovery", {"email": "jdoe@example.com"})
    _, token = _token_from_mail(env)
    r = env.post(
        "/api/v2/auth/recovery/confirm",
        {"login": "other", "token": token, "password": "brand-new-pass"},
    )
    assert r.status_code == 422
