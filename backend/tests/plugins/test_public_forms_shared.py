"""Public form challenges and limits shared by replicas through the application database."""

from __future__ import annotations

from pathlib import Path

from heracles.storage import Database
from heracles_plugins.public_forms.captcha import Captcha, solve
from heracles_plugins.public_forms.shared import (
    DbNonceStore,
    DbSubmissionWindow,
    load_secret,
)


def _replica(path: Path, now: list[float]) -> tuple[Captcha, DbSubmissionWindow]:
    database = Database(path)
    clock = lambda: now[0]  # noqa: E731
    captcha = Captcha(
        load_secret(database),
        difficulty=6,
        min_fill=0,
        clock=clock,
        nonces=DbNonceStore(database, clock),
    )
    return captcha, DbSubmissionWindow(database, 2, 3600, clock)


def test_a_challenge_verifies_on_another_replica_and_only_once(tmp_path: Path) -> None:
    now = [1_900_000_000.0]
    a, _ = _replica(tmp_path / "h.db", now)
    b, _ = _replica(tmp_path / "h.db", now)
    c = a.new_challenge()
    answer = str(solve(c["nonce"], c["difficulty"]))
    assert b.verify(c["token"], answer)  # same secret, issued elsewhere
    assert not a.verify(c["token"], answer)  # the nonce is spent for every replica


def test_the_submission_limit_is_shared(tmp_path: Path) -> None:
    now = [1_900_000_000.0]
    _, a = _replica(tmp_path / "h.db", now)
    _, b = _replica(tmp_path / "h.db", now)
    a.record("1.2.3.4")
    b.record("1.2.3.4")
    assert a.retry_after("1.2.3.4") > 0 and b.retry_after("1.2.3.4") > 0
    assert a.retry_after("5.6.7.8") == 0
    now[0] += 3601
    assert a.retry_after("1.2.3.4") == 0
