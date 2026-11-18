"""Server refusal of invalid values: triggers, tasks, health fixes, import and export."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles import demo
from heracles.api.settings import ApiSettings, PluginsSettings, TriggersSettings
from heracles.core import config_store
from heracles.demo import BASE
from heracles.ldap.memory import MemoryDirectory
from heracles.server import build_demo_app, create_full_app
from heracles.triggers import MAX_COMMAND_LENGTH

ADMIN = f"uid=admin,ou=people,{BASE}"
CSV_TEXT = "login,first,last\nzed,Zed,Zulu\nzoe,Zoe,Zulu\n"
MAPPING = [
    {"column": 0, "field": "main.uid"},
    {"column": 1, "field": "main.givenName"},
    {"column": 2, "field": "main.sn"},
]


class Api:
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.client = TestClient(app, base_url="http://testserver")
        self.headers = {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}
        r = self.client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": "admin", "password": "heracles"},
            headers=self.headers,
        )
        assert r.status_code == 200, r.text
        self.headers = {"X-CSRF-Token": self.client.get("/api/v2/auth/csrf").json()["token"]}

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(f"/api/v2{path}", params=params)

    def post(self, path: str, body: Any = None) -> Any:
        return self.client.post(f"/api/v2{path}", json=body, headers=self.headers)

    def put(self, path: str, body: Any) -> Any:
        return self.client.put(f"/api/v2{path}", json=body, headers=self.headers)

    @property
    def directory(self) -> MemoryDirectory:
        return cast("MemoryDirectory", self.app.state.heracles.directories["main"])


@pytest.fixture
def api() -> Iterator[Api]:
    app = build_demo_app()
    with TestClient(app):
        yield Api(app)


@pytest.fixture
def hook_api(tmp_path: Path) -> Iterator[Api]:
    """The demo administrator as a bootstrap administrator, with an approved scripts directory."""
    (tmp_path / "true.sh").write_text("#!/bin/sh\ntrue\n")
    (tmp_path / "true.sh").chmod(0o755)
    settings = ApiSettings(
        admin_dns=[ADMIN],
        directory_labels={"main": "Demo directory"},
        plugins=PluginsSettings(enabled=["*"]),
        triggers=TriggersSettings(scripts_dir=tmp_path),
    )
    settings.session.cookie_secure = False
    app = create_full_app(settings, {"main": demo.build_demo_directory()})
    with TestClient(app):
        yield Api(app)


def fields_of(response: Any) -> dict[str, str]:
    assert response.status_code == 422, response.text
    return cast("dict[str, str]", response.json()["error"]["fields"])


# ---------------------------------------------------------------- triggers


def hook(**kw: Any) -> dict[str, Any]:
    return {"tab": "user", "mode": "postcreate", "command": "true.sh", **kw}


@pytest.mark.parametrize(
    ("item", "field"),
    [
        (hook(tab="nowhere"), "tab"),
        (hook(tab=" "), "tab"),
        (hook(tab="a|b"), "tab"),
        (hook(mode="whenever"), "mode"),
        (hook(command="   "), "command"),
        (hook(command="echo a\necho b"), "command"),
        (hook(command="echo %uid%"), "command"),
        (hook(command="/bin/true"), "command"),
        (hook(command="echo a\rb"), "command"),
        (hook(command="echo \x00"), "command"),
        (hook(command="# looks disabled"), "command"),
        (hook(command="x" * (MAX_COMMAND_LENGTH + 1)), "command"),
    ],
)
def test_hook_refused_on_its_own_field(hook_api: Api, item: dict[str, Any], field: str) -> None:
    errors = fields_of(hook_api.put("/admin/hooks", {"hooks": [hook(), item]}))
    assert set(errors) == {f"hooks.1.{field}"}
    assert [
        h["command"] for h in hook_api.get("/admin/hooks").json()["hooks"]
    ] == []  # nothing saved


def test_duplicate_hook_is_refused(hook_api: Api) -> None:
    first = hook()
    errors = fields_of(
        hook_api.put(
            "/admin/hooks", {"hooks": [first, hook(mode="check"), {**first, "enabled": False}]}
        )
    )
    assert errors == {"hooks.2.command": "Same trigger as #1."}


def test_longest_name_is_accepted(hook_api: Api) -> None:
    ok = [hook(command="x" * MAX_COMMAND_LENGTH), hook(command="a.b-c_d", mode="check")]
    assert hook_api.put("/admin/hooks", {"hooks": ok}).status_code == 200


def test_a_tab_already_stored_is_still_accepted(hook_api: Api) -> None:
    config_store.save_config(hook_api.directory, {"tab_hooks": ["legacyTab|postcreate|true.sh"]})
    current = hook_api.get("/admin/hooks").json()
    assert [h["tab"] for h in current["hooks"]] == ["legacyTab"]
    kept = hook_api.put("/admin/hooks", {"hooks": current["hooks"], "display_output": True})
    assert kept.status_code == 200, kept.text
    added = hook_api.put("/admin/hooks", {"hooks": [*current["hooks"], hook(tab="otherLegacy")]})
    assert fields_of(added) == {"hooks.1.tab": "Unknown tab."}


def test_a_stored_shell_command_is_reported_as_not_approved(hook_api: Api) -> None:
    config_store.save_config(hook_api.directory, {"tab_hooks": ["user|postcreate|echo %uid%"]})
    (listed,) = hook_api.get("/admin/hooks").json()["hooks"]
    assert listed["approved"] is False
    refused = hook_api.put("/admin/hooks", {"hooks": [listed]})
    assert fields_of(refused) == {
        "hooks.0.command": "Give the bare file name of an approved script."
    }


# ------------------------------------------------------------------- tasks


def test_task_filters_refuse_unknown_values(api: Api) -> None:
    assert fields_of(api.get("/admin/tasks", kind="nope")) == {"kind": "Unknown task kind."}
    assert fields_of(api.get("/admin/tasks", status="bogus")) == {"status": "Unknown task status."}
    assert api.get("/admin/tasks", kind="audit_task", status="activated").status_code == 200
    assert api.get("/admin/tasks", status="Deactivated").status_code == 200


def test_task_actions_refuse_a_malformed_dn(api: Api) -> None:
    for action in ("run", "retry"):
        r = api.post(f"/admin/tasks/{quote('not a dn', safe='')}/{action}")
        assert set(fields_of(r)) == {"dn"}


# ------------------------------------------------------------------ health


def test_fix_options_are_validated(api: Api) -> None:
    def fix(check: str, **body: Any) -> Any:
        return api.post(f"/admin/checks/{check}/fix", {"dns": [], "options": {}, **body})

    assert set(fields_of(fix("super_admin"))) == {"options.dn"}
    assert set(fields_of(fix("super_admin", options={"dn": "   "}))) == {"options.dn"}
    assert set(fields_of(fix("super_admin", options={"dn": "garbage"}))) == {"options.dn"}
    ghost = f"uid=ghost,ou=people,{BASE}"
    assert fields_of(fix("super_admin", options={"dn": ghost})) == {
        "options.dn": "Choose an existing user."
    }
    outside = fix("super_admin", options={"dn": "uid=x,dc=elsewhere"})
    assert set(fields_of(outside)) == {"options.dn"}
    container = f"ou=people,{BASE}"  # exists but is not a person
    assert set(fields_of(fix("super_admin", options={"dn": container}))) == {"options.dn"}
    extra = fix("super_admin", options={"dn": ADMIN, "uid": "x"})
    assert set(fields_of(extra)) == {"options.uid"}
    assert set(fields_of(fix("default_roles", options={"dn": ADMIN}))) == {"options.dn"}


def test_fix_dns_must_be_reported_by_the_check(api: Api) -> None:
    def fix(check: str, dns: list[str]) -> Any:
        return api.post(f"/admin/checks/{check}/fix", {"dns": dns})

    errors = fields_of(fix("default_roles", ["nonsense", f"cn=other,{BASE}"]))
    assert set(errors) == {"dns.0", "dns.1"}
    offending = next(c for c in api.get("/admin/checks").json() if c["id"] == "default_roles")[
        "dns"
    ]
    ok = fix("default_roles", offending[:1])
    assert ok.status_code == 200, ok.text
    assert len(ok.json()["result"]["fixed"]) == 1
    assert fix("duplicate_ids", []).status_code == 404  # no fix: unchanged


def test_super_admin_fix_with_an_existing_user_runs(api: Api) -> None:
    ok = api.post("/admin/checks/super_admin/fix", {"options": {"dn": ADMIN}})
    assert ok.status_code == 200, ok.text
    assert ok.json()["result"]["fixed"] == [ADMIN]


# ----------------------------------------------------------- import / export


def test_export_refuses_a_malformed_base_and_filter(api: Api) -> None:
    assert set(fields_of(api.get("/ldif/export", base="not a dn"))) == {"base"}
    assert set(fields_of(api.get("/ldif/export", filter="(uid=x"))) == {"filter"}
    assert api.get("/ldif/export", base=f"ou=ghost,{BASE}").status_code == 404
    assert api.get("/ldif/export", base=BASE).status_code == 200


def test_ldif_records_with_a_malformed_dn_are_reported(api: Api) -> None:
    ok_entry = f"dn: ou=ok,{BASE}\nobjectClass: organizationalUnit\nou: ok\n"
    text = f"dn: garbage\nobjectClass: top\n\n{ok_entry}"
    body = api.post("/ldif/import", {"text": text, "dry_run": True}).json()
    assert [(r["action"], r["error"]) for r in body["results"]] == [
        ("error", "Invalid DN"),
        ("add", None),
    ]


def test_csv_separator_is_a_field_error(api: Api) -> None:
    assert set(fields_of(api.post("/csv/parse", {"text": "a", "separator": "?"}))) == {"separator"}
    bad = api.post("/csv/user/import", {"text": CSV_TEXT, "separator": "?", "mapping": MAPPING})
    assert set(fields_of(bad)) == {"separator"}


def test_csv_mapping_duplicates_and_gaps_are_refused(api: Api) -> None:
    def run(**body: Any) -> dict[str, str]:
        payload = {"text": CSV_TEXT, "mapping": MAPPING, **body}
        return fields_of(api.post("/csv/user/import", payload))

    twice = [*MAPPING, {"column": 3 - 1, "field": "main.description"}]
    assert run(mapping=twice) == {
        "mapping.main.description": "This column is already mapped to another field"
    }
    same_field = [*MAPPING, {"column": 1, "field": "main.uid"}]
    assert "mapping.main.uid" in run(mapping=same_field)
    assert run(mapping=[]) == {"mapping": "Map at least one column."}
    missing = run(mapping=MAPPING[:1])
    assert set(missing) == {"mapping.main.givenName", "mapping.main.sn"}
    covered_by_fixed = api.post(
        "/csv/user/import",
        {"text": CSV_TEXT, "mapping": MAPPING[:2], "fixed": {"main.sn": "Fixed"}},
    )
    assert covered_by_fixed.status_code == 200, covered_by_fixed.text
    assert covered_by_fixed.json()["imported"] == 2


def test_csv_without_data_lines_is_refused(api: Api) -> None:
    errors = fields_of(
        api.post("/csv/user/import", {"text": "login,first,last\n", "mapping": MAPPING})
    )
    assert errors == {"text": "The file has no data line."}


def test_csv_fixed_values_are_checked_before_the_run(api: Api) -> None:
    def run(fixed: dict[str, str]) -> dict[str, str]:
        payload = {"text": CSV_TEXT, "mapping": MAPPING, "fixed": fixed}
        return fields_of(api.post("/csv/user/import", payload))

    assert set(run({"main.description": "  "})) == {"fixed.main.description"}
    assert set(run({"ftp_accounts.FTPQuotaFiles": "many"})) == {"fixed.ftp_accounts.FTPQuotaFiles"}
    assert api.directory.get(f"uid=zed,ou=people,{BASE}") is None  # nothing was created


def test_csv_base_and_template_are_validated(api: Api) -> None:
    def run(**body: Any) -> dict[str, str]:
        return fields_of(
            api.post("/csv/user/import", {"text": CSV_TEXT, "mapping": MAPPING, **body})
        )

    assert set(run(base="not a dn")) == {"base"}
    assert run(base=f"ou=ghost,{BASE}") == {"base": "The container does not exist."}
    assert set(run(template="not a dn")) == {"template"}
    assert set(fields_of(api.get("/csv/user/fields", template="not a dn"))) == {"template"}


def test_csv_fields_tell_which_tabs_and_defaults_apply(api: Api) -> None:
    fields = {f["key"]: f for f in api.get("/csv/user/fields").json()}
    assert fields["main.sn"]["tab_optional"] is False and fields["main.sn"]["has_default"] is False
    assert fields["kerberos.krbPrincipalName"]["tab_optional"] is True
    assert fields["ftp_accounts.FTPStatus"]["has_default"] is True
