"""Data written through the real stores, and the checks that it came back (backup tests)."""

from __future__ import annotations

from datetime import UTC, datetime

from heracles.auth.api_tokens import ApiToken
from heracles.auth.api_tokens_db import SqlApiTokenStore
from heracles.auth.second_factor import WebAuthnCredential
from heracles.auth.second_factor_db import SqliteSecondFactorStore
from heracles.auth.sessions_db import SqliteSessionStore
from heracles.objects.activation import PluginOverrideStore
from heracles.storage import Database
from heracles.tasks.scheduler import RunRecord, TaskStore
from heracles_plugins.access.requests import APPROVED, AccessRequestStore
from heracles_plugins.access.reviews import Campaign, Item, ReviewStore

DN = "uid=jdoe,ou=people,dc=example,dc=com"
APPROVER = "uid=boss,ou=people,dc=example,dc=com"
GROUP = "cn=staff,ou=groups,dc=example,dc=com"


def seed(db: Database) -> str:
    """Fill every kind of state the console keeps; return the id of the session created."""
    second = SqliteSecondFactorStore(db)
    second.set_totp_secret(DN, "JBSWY3DPEHPK3PXP")
    second.set_last_totp_step(DN, 41_000_000)
    second.set_recovery_hashes(DN, ["hash-a", "hash-b"])
    second.add_webauthn_credential(
        DN, WebAuthnCredential(b"\x00\xffkey", b"\x01public\x02", 3, "Desk")
    )

    SqlApiTokenStore(db).add(
        ApiToken(
            id="tok1",
            owner_dn=DN,
            directory_id="main",
            name="ci",
            scope="write",
            types=("user", "group"),
            created_at=1_700_000_000.5,
            expires_at=1_800_000_000.25,
            created_by=DN,
            secret_hash="sha256:abc",
        )
    )

    requests = AccessRequestStore(db)
    pending = requests.add(
        directory_id="main",
        requester_dn=DN,
        member_dn=DN,
        target_dn=GROUP,
        target_kind="group",
        target_label="Staff",
        reason="needs the shared drive: é€",
        until="2027-01-31",
    )
    requests.decide(pending, APPROVED, by=APPROVER, comment="ok")

    reviews = ReviewStore(db)
    reviews.create(
        Campaign(
            id="camp1",
            directory_id="main",
            name="Q4",
            created_by=APPROVER,
            created_at=1_700_000_000.0,
            deadline=1_800_000_000.0,
            reviewer_rule="owner",
            default_decision="keep",
            status="open",
            selector={"holders": [GROUP]},
        ),
        [Item("camp1", "i1", GROUP, "Staff", "group", DN, APPROVER)],
    )
    (item,) = reviews.items("camp1")
    reviews.decide(item, "revoke", "left the team", APPROVER)

    now = datetime.now(UTC)
    tasks = TaskStore(db)
    tasks.record(RunRecord("main", "access", "", now, now, "ok", {"expired": 2}, []))
    tasks.record(RunRecord("main", "audit", "", now, now, "ok", {"purged": 5}, ["warn"]))

    overrides = PluginOverrideStore(db)
    overrides.set("sudo", False, "admin")
    overrides.set("ssh", True, "admin")

    sessions = SqliteSessionStore(db, idle_timeout=600.0, absolute_timeout=3600.0)
    return sessions.create(DN, "main").id


def check(db: Database, session_id: str) -> None:
    """Assert that the state written by :func:`seed` is in ``db`` (and the session is not)."""
    second = SqliteSecondFactorStore(db)
    assert second.totp_secret(DN) == "JBSWY3DPEHPK3PXP"
    assert second.last_totp_step(DN) == 41_000_000
    assert sorted(second.recovery_hashes(DN)) == ["hash-a", "hash-b"]
    (cred,) = second.webauthn_credentials(DN)
    assert (cred.credential_id, cred.public_key, cred.sign_count) == (
        b"\x00\xffkey",
        b"\x01public\x02",
        3,
    )

    token = SqlApiTokenStore(db).get("tok1")
    assert token is not None
    assert (token.owner_dn, token.scope, token.types) == (DN, "write", ("user", "group"))
    assert (token.created_at, token.expires_at, token.secret_hash) == (
        1_700_000_000.5,
        1_800_000_000.25,
        "sha256:abc",
    )
    assert [t.id for t in SqlApiTokenStore(db).list_for_owner(DN)] == ["tok1"]

    (request,) = AccessRequestStore(db).list("main")
    assert (request.status, request.decided_by, request.until) == (APPROVED, APPROVER, "2027-01-31")
    assert request.reason == "needs the shared drive: é€"
    assert AccessRequestStore(db).pending_for("main", DN, GROUP) is None  # it was decided

    reviews = ReviewStore(db)
    campaign = reviews.get("camp1")
    assert campaign is not None and campaign.selector == {"holders": [GROUP]}
    (item,) = reviews.items("camp1")
    assert (item.decision, item.comment, item.decided_by) == ("revoke", "left the team", APPROVER)
    assert [i.item_id for i in reviews.items_for_reviewer(APPROVER)] == ["i1"]

    tasks = TaskStore(db)
    assert [(r.runner, dict(r.counts)) for r in reversed(tasks.recent())] == [
        ("access", {"expired": 2}),
        ("audit", {"purged": 5}),
    ]
    now = datetime.now(UTC)
    tasks.record(RunRecord("main", "access", "", now, now, "ok", {}, []))  # the serial moved on
    assert [r.id for r in reversed(tasks.recent())] == [1, 2, 3]

    assert PluginOverrideStore(db).load() == {"sudo": False, "ssh": True}

    sessions = SqliteSessionStore(db, idle_timeout=600.0, absolute_timeout=3600.0)
    assert sessions.get(session_id) is None
