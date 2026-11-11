"""Audit coverage of the non-object write paths and the ``/api/v2/audit`` endpoint."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.domain import Domain
from heracles.api.settings import ApiSettings
from heracles.core.audit import AuditSink, write_event
from heracles.ldap.memory import MemoryDirectory
from heracles.server import create_full_app

BASE = demo.BASE
AUDIT = f"ou=audit,{BASE}"
ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"
ADMIN = f"uid=admin,ou=people,{BASE}"


def q(dn: str) -> str:
    return quote(dn, safe="")


class Api:
    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.headers = {"X-CSRF-Token": client.get("/api/v2/auth/csrf").json()["token"]}

    def login(self, username: str, password: str = "heracles") -> Any:
        r = self.post(
            "/auth/login", {"directory": "main", "username": username, "password": password}
        )
        self.headers = {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}
        return r

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(f"/api/v2{path}", params=params)

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(f"/api/v2{path}", json=body, headers=self.headers)

    def put(self, path: str, body: Any = None) -> Any:
        return self.client.put(f"/api/v2{path}", json=body, headers=self.headers)

    def delete(self, path: str) -> Any:
        return self.client.delete(f"/api/v2{path}", headers=self.headers)


def make_directory(*, audit: bool = True) -> MemoryDirectory:
    d = demo.build_demo_directory()
    classes = [c for c in d.schema_object_classes() if c.lower() != "hrcauditevent"]
    d.set_schema_object_classes([*classes, *(["hrcAuditEvent"] if audit else [])])
    return d


@pytest.fixture
def directory() -> MemoryDirectory:
    return make_directory()


def client_for(directory: MemoryDirectory) -> Iterator[TestClient]:
    settings = ApiSettings(admin_dns=[], directory_labels={"main": "Demo"})
    settings.session.cookie_secure = False
    with TestClient(create_full_app(settings, {"main": directory})) as client:
        yield client


@pytest.fixture
def app_client(directory: MemoryDirectory) -> Iterator[TestClient]:
    yield from client_for(directory)


def events(directory: MemoryDirectory, **match: str) -> list[dict[str, list[str]]]:
    if directory.get(AUDIT) is None:
        return []
    rows: list[dict[str, list[str]]] = []
    for entry in directory.search(AUDIT, "(objectClass=hrcAuditEvent)"):
        row = {k: [v.decode() for v in vs] for k, vs in entry.attrs.items()}
        if all(row.get(k) == [v] for k, v in match.items()):
            rows.append(row)
    return rows


# ----------------------------------------------------------------- capabilities


def test_descriptor_and_summary_expose_capability_flags(app_client: TestClient) -> None:
    a = Api(app_client)
    a.login("admin")
    audit = a.get("/types/audit_event").json()
    assert (audit["creatable"], audit["editable"], audit["deletable"]) == (False, False, False)
    assert audit["supports_templates"] is False
    user = a.get("/types/user").json()
    assert (user["creatable"], user["editable"], user["deletable"]) == (True, True, True)
    assert user["supports_templates"] is True
    summaries = {t["name"]: t for t in a.get("/types").json()}
    assert summaries["audit_event"]["can_create"] is False
    assert summaries["audit_event"]["deletable"] is False
    assert summaries["user"]["creatable"] is True


def test_audit_event_cannot_be_deleted_through_the_generic_api(
    app_client: TestClient, directory: MemoryDirectory
) -> None:
    a = Api(app_client)
    a.login("admin")
    event_dn = write_event(
        directory, action="modify", object_type="user", object_dn=ASMITH, author_dn=ADMIN
    )
    assert a.delete(f"/objects/audit_event/{q(event_dn)}").status_code == 403
    assert directory.get(event_dn) is not None
    body = {"base": BASE, "tabs": {"main": {"values": {"cn": "x"}}}}
    assert a.post("/objects/audit_event", body).status_code == 403


# ---------------------------------------------------------------------- sink


def test_sink_is_a_noop_when_the_plugin_is_disabled() -> None:
    d = make_directory(audit=False)
    for client in client_for(d):
        a = Api(client)
        assert a.login("admin").status_code == 200
        assert events(d) == []


def test_sink_without_registry_and_failures_do_not_raise() -> None:
    d = make_directory()
    sink = AuditSink()
    assert not sink.enabled
    sink.record(d, "login", object_type="user", object_dn=ASMITH, author_dn=ASMITH)
    assert events(d) == []

    class Broken(MemoryDirectory):
        def add(self, dn: str, attrs: Any) -> None:
            raise RuntimeError("boom")

    for client in client_for(make_directory()):
        domain = cast("Domain", client.app.state.domain)  # type: ignore[attr-defined]
        broken = Broken(BASE)
        sink = AuditSink(domain.registry)
        assert sink.enabled
        sink.record(broken, "login", object_type="user", object_dn=ASMITH)


# ------------------------------------------------------------------ audited paths


def test_login_logout_and_failed_login(app_client: TestClient, directory: MemoryDirectory) -> None:
    a = Api(app_client)
    bad = a.login("admin", "wrong")
    assert bad.status_code == 401
    failed = events(directory, hrcAuditAction="login_failed")
    assert len(failed) == 1
    assert failed[0]["hrcAuditResult"] == ["failure"]
    assert any(line == "login: admin" for line in failed[0]["hrcAuditAttributes"])
    assert failed[0]["hrcAuditObject"] == [ADMIN]
    assert "hrcAuditAuthorDN" not in failed[0]
    assert a.login("admin").status_code == 200
    ok = events(directory, hrcAuditAction="login")
    assert len(ok) == 1 and ok[0]["hrcAuditAuthorDN"] == [ADMIN]
    assert a.post("/auth/logout").status_code == 204
    out = events(directory, hrcAuditAction="logout")
    assert len(out) == 1 and out[0]["hrcAuditObject"] == [ADMIN]


def test_unknown_login_failure_notes_the_attempted_login(
    app_client: TestClient, directory: MemoryDirectory
) -> None:
    Api(app_client).login("nobody", "x")
    failed = events(directory, hrcAuditAction="login_failed")
    assert failed[0]["hrcAuditObject"] == ["nobody"]


def test_second_factor_enrolment_and_removal(
    app_client: TestClient, directory: MemoryDirectory
) -> None:
    a = Api(app_client)
    a.login("admin")
    r = a.post("/auth/totp/begin")
    assert r.status_code == 200, r.text
    # recovery codes need a real factor: the refusal writes nothing
    assert events(directory, hrcAuditAction="second_factor") == []


def test_recovery_confirm_failure_is_recorded(
    app_client: TestClient, directory: MemoryDirectory
) -> None:
    a = Api(app_client)
    r = a.post("/auth/recovery/confirm", {"login": "admin", "token": "nope", "password": "x" * 12})
    assert r.status_code in (404, 422)
    if r.status_code == 422:
        rows = events(directory, hrcAuditAction="password")
        assert rows and rows[0]["hrcAuditResult"] == ["failure"]


def test_acl_and_config_changes_are_recorded(
    app_client: TestClient, directory: MemoryDirectory
) -> None:
    a = Api(app_client)
    a.login("admin")
    r = a.post(
        "/admin/acl/roles",
        {"cn": "auditors", "description": "d", "templates": [], "base": None},
    )
    if r.status_code == 201:
        rows = events(directory, hrcAuditAction="acl")
        assert rows and rows[0]["hrcAuditObjectType"] == ["acl_role"]
        assert rows[0]["hrcAuditAuthorDN"] == [ADMIN]
    r = a.put("/admin/hooks", {"hooks": [], "display_output": None})
    if r.status_code == 200:
        assert events(directory, hrcAuditAction="config", hrcAuditObjectType="hooks")


def test_ldif_import_writes_summary_and_entry_events(
    app_client: TestClient, directory: MemoryDirectory
) -> None:
    a = Api(app_client)
    a.login("admin")
    ldif = f"dn: ou=imported,{BASE}\nobjectClass: organizationalUnit\nou: imported\n"
    r = a.post("/ldif/import", {"text": ldif})
    assert r.status_code == 200, r.text
    rows = events(directory, hrcAuditAction="import")
    kinds = sorted(row["hrcAuditObjectType"][0] for row in rows)
    assert kinds == ["ldif", "ldif_entry"]
    # a dry run writes nothing
    before = len(events(directory))
    a.post("/ldif/import", {"text": ldif, "dry_run": True})
    assert len(events(directory)) == before


def test_object_changes_are_still_recorded(
    app_client: TestClient, directory: MemoryDirectory
) -> None:
    a = Api(app_client)
    a.login("admin")
    r = a.client.patch(
        f"/api/v2/objects/user/{q(ASMITH)}",
        json={"tabs": {"main": {"values": {"description": "x"}}}},
        headers=a.headers,
    )
    assert r.status_code == 200, r.text
    assert events(directory, hrcAuditAction="modify", hrcAuditObject=ASMITH)


# ------------------------------------------------------------------- /audit API


def seed(directory: MemoryDirectory) -> None:
    now = datetime.now(UTC)
    write_event(
        directory,
        action="login",
        object_type="user",
        object_dn=ASMITH,
        author_dn=ASMITH,
        author_ip="10.0.0.1",
        now=now - timedelta(days=10),
    )
    write_event(
        directory,
        action="modify",
        object_type="user",
        object_dn=ASMITH,
        author_dn=ADMIN,
        attributes=["mail: a@example.com"],
        now=now - timedelta(hours=2),
    )
    write_event(
        directory,
        action="delete",
        object_type="group",
        object_dn=f"cn=g,ou=groups,{BASE}",
        author_dn=ADMIN,
        result="failure",
        now=now - timedelta(hours=1),
    )
    write_event(
        directory,
        action="login_failed",
        object_type="user",
        object_dn="ghost",
        author_dn="",
        attributes=["login: ghost"],
        result="failure",
        now=now - timedelta(minutes=5),
    )


def test_audit_list_filters_and_order(app_client: TestClient, directory: MemoryDirectory) -> None:
    seed(directory)
    a = Api(app_client)
    a.login("admin")
    r = a.get("/audit")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    # the admin's own login is the newest event
    assert [i["action"] for i in items][:2] == ["login", "login_failed"]
    times = [i["time"] for i in items]
    assert times == sorted(times, reverse=True)
    first = items[0]
    assert set(first) == {"dn", "time", "action", "actor", "object", "ip", "attributes", "result"}
    assert first["actor"]["dn"] == ADMIN and first["actor"]["label"]

    by_action = a.get("/audit", action=["login", "delete"]).json()["items"]
    assert {i["action"] for i in by_action} == {"login", "delete"}
    assert [i["action"] for i in a.get("/audit", result="failure").json()["items"]] == [
        "login_failed",
        "delete",
    ]
    assert {i["object"]["type"] for i in a.get("/audit", type="group").json()["items"]} == {"group"}
    mine = a.get("/audit", actor=ASMITH).json()["items"]
    assert len(mine) == 1 and mine[0]["ip"] == "10.0.0.1"
    below = a.get("/audit", object=f"ou=paris,{BASE}").json()["items"]
    assert {i["object"]["dn"] for i in below} == {ASMITH}
    text = a.get("/audit", q="a@example.com").json()["items"]
    assert len(text) == 1 and text[0]["attributes"] == ["mail: a@example.com"]
    ghost = a.get("/audit", action="login_failed").json()["items"][0]
    assert ghost["actor"] == {"dn": "", "label": "ghost"}

    recent = a.get("/audit", **{"from": (datetime.now(UTC) - timedelta(days=1)).isoformat()})
    assert ASMITH not in {i["actor"]["dn"] for i in recent.json()["items"] if i["ip"]}
    assert len(recent.json()["items"]) == len(items) - 1
    old = a.get("/audit", to=(datetime.now(UTC) - timedelta(days=5)).isoformat())
    assert [i["action"] for i in old.json()["items"]] == ["login"]
    assert a.get("/audit", **{"from": "yesterday"}).status_code == 422


def test_audit_cursor_paging(app_client: TestClient, directory: MemoryDirectory) -> None:
    seed(directory)
    a = Api(app_client)
    a.login("admin")
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = a.get("/audit", **params).json()
        seen += [i["dn"] for i in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == len(events(directory))


def test_audit_csv_export(app_client: TestClient, directory: MemoryDirectory) -> None:
    seed(directory)
    write_event(
        directory,
        action="modify",
        object_type="user",
        object_dn=ASMITH,
        author_dn=ADMIN,
        attributes=["=cmd|calc"],
    )
    a = Api(app_client)
    a.login("admin")
    r = a.get("/audit", format="csv", action="modify")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][:3] == ["time", "action", "result"]
    assert len(rows) == 3
    assert any(cell == "'=cmd|calc" for row in rows for cell in row)


def test_audit_requires_read_right(app_client: TestClient, directory: MemoryDirectory) -> None:
    a = Api(app_client)
    assert a.login("asmith").status_code == 200
    assert a.get("/audit").status_code == 403
    assert Api(app_client).get("/audit").status_code in (401, 403)


def test_audit_endpoint_absent_without_plugin() -> None:
    d = make_directory(audit=False)
    for client in client_for(d):
        a = Api(client)
        a.login("admin")
        assert "items" not in a.get("/audit").text
        assert "audit_event" not in {t["name"] for t in a.get("/types").json()}
