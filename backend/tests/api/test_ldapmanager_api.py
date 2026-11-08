"""LDIF export / import, CSV import and the raw LDIF of one object on the demo application."""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from typing import Any, cast
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from heracles import demo
from heracles.ldap.ldif import parse_ldif
from heracles.ldap.memory import MemoryDirectory
from heracles.server import build_demo_app

BASE = demo.BASE
ASMITH = f"uid=asmith,ou=people,ou=paris,{BASE}"
CDUPONT = f"uid=cdupont,ou=people,ou=lyon,{BASE}"


def q(dn: str) -> str:
    return quote(dn, safe="")


class Api:
    def __init__(self, app: FastAPI) -> None:
        self.app = app
        self.client = TestClient(app)
        self.headers = {"X-CSRF-Token": str(self.client.get("/api/v2/auth/csrf").json()["token"])}

    def login(self, user: str) -> Api:
        r = self.client.post(
            "/api/v2/auth/login",
            json={"directory": "main", "username": user, "password": "heracles"},
            headers=self.headers,
        )
        assert r.status_code == 200, r.text
        self.headers = {"X-CSRF-Token": str(self.client.get("/api/v2/auth/csrf").json()["token"])}
        return self

    def get(self, path: str, **params: Any) -> Any:
        return self.client.get(f"/api/v2{path}", params=params)

    def post(self, path: str, body: Any) -> Any:
        return self.client.post(f"/api/v2{path}", json=body, headers=self.headers)

    @property
    def directory(self) -> MemoryDirectory:
        return cast("MemoryDirectory", self.app.state.heracles.directories["main"])


@pytest.fixture
def app() -> Iterator[FastAPI]:
    yield build_demo_app()


@pytest.fixture
def admin(app: FastAPI) -> Api:
    return Api(app).login("admin")


# -- access -------------------------------------------------------------------------------------
def test_access_flags(app: FastAPI) -> None:
    assert Api(app).login("admin").get("/ldapmanager/access").json() == {
        "ldif_export": True,
        "ldif_import": True,
        "csv_import": True,
    }
    assert Api(app).login("bmartin").get("/ldapmanager/access").json() == {
        "ldif_export": False,
        "ldif_import": False,
        "csv_import": False,
    }


def test_requires_authentication(app: FastAPI) -> None:
    anonymous = Api(app)
    assert anonymous.get("/ldif/export").status_code == 401
    assert anonymous.post("/ldif/import", {"text": "x"}).status_code == 401
    assert anonymous.get(f"/objects/user/{q(ASMITH)}/ldif").status_code == 401


# -- export -------------------------------------------------------------------------------------
def test_export_single_entry(admin: Api) -> None:
    r = admin.get("/ldif/export", base=ASMITH, scope="base")
    assert r.status_code == 200
    assert r.headers["content-disposition"].startswith("attachment")
    [entry] = parse_ldif(r.text)
    assert entry.dn == ASMITH and entry.text("uid") == "asmith"
    assert entry.get("userPassword") == []  # secrets are never exported


def test_export_subtree_with_filter_and_wrap(admin: Api) -> None:
    r = admin.get(
        "/ldif/export",
        base=f"ou=paris,{BASE}",
        filter="(objectClass=inetOrgPerson)",
        wrap=0,
    )
    entries = parse_ldif(r.text)
    assert {e.dn for e in entries} == {ASMITH, f"uid=bmartin,ou=people,ou=paris,{BASE}"}
    one = admin.get("/ldif/export", base=f"ou=paris,{BASE}", scope="one")
    assert {e.dn for e in parse_ldif(one.text)} == {
        f"ou=people,ou=paris,{BASE}",
        f"ou=groups,ou=paris,{BASE}",
        f"ou=roles,ou=paris,{BASE}",
    }
    wrapped = admin.get("/ldif/export", base=ASMITH, scope="base", wrap=20)
    assert all(len(line) <= 20 for line in wrapped.text.splitlines())


def test_export_errors(admin: Api) -> None:
    assert admin.get("/ldif/export", filter="(uid=").status_code == 422
    assert admin.get("/ldif/export", base=f"ou=ghost,{BASE}").status_code == 404
    assert admin.get("/ldif/export", scope="nope").status_code == 422


def test_export_requires_rights(app: FastAPI) -> None:
    assert Api(app).login("bmartin").get("/ldif/export").status_code == 403
    assert Api(app).login("helpdesk").get("/ldif/export").status_code == 403


def test_export_only_returns_readable_entries_and_attributes(app: FastAPI) -> None:
    """A manager with LDIF rights still only gets what the type ACLs allow reading."""
    api = Api(app).login("admin")
    directory = api.directory
    # grant "helpdesk" the LDIF read right through an extra ACL role on the whole base
    from heracles.acl import serialise_assignment, serialise_role_value
    from heracles.acl.model import AclAssignment, AclScope, RoleTemplateValue
    from heracles.acl.parser import parse_role_value
    from heracles.ldap.client import Modification
    from heracles.schema.legacy import ATTR, OC

    role = parse_role_value("0:ldif/ldifManager;r,user/user;r#userPassword;r")
    assert isinstance(role, RoleTemplateValue)
    role_dn = f"cn=ldif-reader,ou=aclroles,{BASE}"
    directory.add(
        role_dn,
        {
            "objectClass": [OC.ACL_ROLE.encode()],
            "cn": [b"ldif-reader"],
            ATTR.ACL_TEMPLATE: [serialise_role_value(role).encode()],
        },
    )
    helpdesk = f"uid=helpdesk,ou=people,{BASE}"
    value = serialise_assignment(
        AclAssignment(index=9, scope=AclScope.SUBTREE, role_dn=role_dn, members=(helpdesk,))
    ).encode()
    directory.modify(BASE, [Modification("add", ATTR.ACL_ENTRY, [value])])
    reader = Api(app).login("helpdesk")
    r = reader.get("/ldif/export", base=f"ou=paris,{BASE}")
    assert r.status_code == 200
    entries = parse_ldif(r.text)
    users = [e for e in entries if e.has_object_class("inetOrgPerson")]
    assert users and all(e.get("userPassword") == [] for e in users)  # write-only: hidden
    groups_ou = [e for e in entries if e.dn == f"ou=groups,ou=paris,{BASE}"]
    assert groups_ou  # containers need the LDIF right only
    # a filter on an attribute the reader cannot see must not select (or exclude) entries
    for hidden in ("(userPassword=*)", "(!(userPassword=*))", "(&(uid=*)(userPassword;x=*))"):
        probe = reader.get("/ldif/export", base=f"ou=paris,{BASE}", filter=hidden)
        probed = parse_ldif(probe.text)
        assert not [e for e in probed if e.has_object_class("inetOrgPerson")], hidden
    visible = reader.get("/ldif/export", base=f"ou=paris,{BASE}", filter="(uid=asmith)")
    assert [e.dn for e in parse_ldif(visible.text)] == [ASMITH]
    # secrets are never exported, so nobody (administrators included) may test them
    root = Api(app).login("admin").get("/ldif/export", base=ASMITH, filter="(userPassword=*)")
    assert parse_ldif(root.text) == []
    assert (
        reader.post("/ldif/import", {"text": f"dn: ou=x,{BASE}\nobjectClass: top\n"}).status_code
        == 403
    )


# -- raw LDIF of one object ---------------------------------------------------------------------
def test_object_ldif(admin: Api) -> None:
    r = admin.get(f"/objects/user/{q(ASMITH)}/ldif")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    [entry] = parse_ldif(r.text)
    assert entry.dn == ASMITH and entry.text("mail") == "asmith@heracles.test"
    assert entry.get("userPassword") == []


def test_object_ldif_omits_hidden_attributes_and_checks_rights(app: FastAPI) -> None:
    helpdesk = Api(app).login("helpdesk")  # read on user/user
    r = helpdesk.get(f"/objects/user/{q(ASMITH)}/ldif")
    assert r.status_code == 200
    assert parse_ldif(r.text)[0].get("userPassword") == []
    regular = Api(app).login("bmartin")
    own = regular.get(f"/objects/user/{q(f'uid=bmartin,ou=people,ou=paris,{BASE}')}/ldif")
    assert own.status_code == 200  # self-service read
    other = regular.get(f"/objects/user/{q(ASMITH)}/ldif")
    assert other.status_code == 403


def test_object_ldif_not_found(admin: Api) -> None:
    assert admin.get(f"/objects/user/{q('uid=ghost,' + BASE)}/ldif").status_code == 404
    assert admin.get(f"/objects/nope/{q(ASMITH)}/ldif").status_code == 404
    # right entry, wrong type
    assert admin.get(f"/objects/group/{q(ASMITH)}/ldif").status_code == 404


# -- LDIF import --------------------------------------------------------------------------------
NEW_LDIF = f"""\
dn: ou=imported,{BASE}
objectClass: organizationalUnit
ou: imported

dn: ou=ghost,ou=nowhere,{BASE}
objectClass: organizationalUnit
ou: ghost
"""


def test_import_dry_run_then_apply(admin: Api) -> None:
    body = {"text": NEW_LDIF}
    plan = admin.post("/ldif/import", {**body, "dry_run": True}).json()
    assert plan["dry_run"] is True
    assert plan["summary"] == {"add": 1, "modify": 0, "unchanged": 0, "exists": 0, "error": 1}
    assert [r["action"] for r in plan["results"]] == ["add", "error"]
    assert admin.directory.get(f"ou=imported,{BASE}") is None
    done = admin.post("/ldif/import", body).json()
    assert done["summary"]["add"] == 1
    assert admin.directory.get(f"ou=imported,{BASE}") is not None


def test_import_overwrite_options(admin: Api) -> None:
    text = (
        f"dn: ou=paris,{BASE}\nobjectClass: organizationalUnit\n"
        "objectClass: gosaDepartment\nou: paris\nl: Paris\n"
    )
    first = admin.post("/ldif/import", {"text": text}).json()
    assert first["results"][0]["action"] == "exists"
    second = admin.post("/ldif/import", {"text": text, "overwrite": True}).json()
    assert second["results"][0] == {
        "index": 1,
        "dn": f"ou=paris,{BASE}",
        "action": "modify",
        "changes": ["l"],
        "error": None,
    }
    third = admin.post(
        "/ldif/import", {"text": text, "overwrite": True, "remove_missing": True}
    ).json()
    assert third["results"][0]["changes"] == ["description"]


def test_import_validation_errors(admin: Api) -> None:
    assert admin.post("/ldif/import", {"text": "not ldif at all"}).status_code == 422
    assert admin.post("/ldif/import", {"text": "# nothing\n"}).status_code == 422
    assert admin.post("/ldif/import", {}).status_code == 422


def test_import_requires_write_rights(app: FastAPI) -> None:
    for login in ("bmartin", "helpdesk"):
        r = Api(app).login(login).post("/ldif/import", {"text": NEW_LDIF})
        assert r.status_code == 403


def _grant_ldif_write(app: FastAPI, member_uid: str) -> None:
    from heracles.acl import serialise_assignment, serialise_role_value
    from heracles.acl.model import AclAssignment, AclScope, RoleTemplateValue
    from heracles.acl.parser import parse_role_value
    from heracles.ldap.client import Modification
    from heracles.schema.legacy import ATTR, OC

    api = Api(app).login("admin")
    role = parse_role_value("0:ldif/ldifManager;rw")
    assert isinstance(role, RoleTemplateValue)
    role_dn = f"cn=ldif-writer,ou=aclroles,{BASE}"
    api.directory.add(
        role_dn,
        {
            "objectClass": [OC.ACL_ROLE.encode()],
            "cn": [b"ldif-writer"],
            ATTR.ACL_TEMPLATE: [serialise_role_value(role).encode()],
        },
    )
    member = f"uid={member_uid},ou=people,{BASE}"
    value = serialise_assignment(
        AclAssignment(index=9, scope=AclScope.SUBTREE, role_dn=role_dn, members=(member,))
    ).encode()
    api.directory.modify(BASE, [Modification("add", ATTR.ACL_ENTRY, [value])])


def test_import_cannot_define_triggers_unless_administrator(app: FastAPI) -> None:
    """Raw LDIF write rights must not become command execution through the trigger list."""
    _grant_ldif_write(app, "helpdesk")
    hook_text = (
        f"dn: ou=sneaky,{BASE}\nobjectClass: organizationalUnit\nou: sneaky\n"
        "fdTabHook: user|postcreate|touch /tmp/pwned\n"
    )
    config_text = (
        f"dn: cn=config,ou=fusiondirectory,{BASE}\nobjectClass: fusionDirectoryConf\ncn: config\n"
    )
    helpdesk = Api(app).login("helpdesk")
    # the right itself works for ordinary entries
    ok = helpdesk.post("/ldif/import", {"text": NEW_LDIF}).json()
    assert ok["summary"]["add"] == 1
    for text in (hook_text, config_text):
        body = helpdesk.post("/ldif/import", {"text": text}).json()
        assert body["summary"]["error"] == 1 and body["summary"]["add"] == 0
        assert "administrator" in body["results"][0]["error"]
    assert helpdesk.directory.get(f"ou=sneaky,{BASE}") is None


def test_import_of_triggers_is_allowed_for_administrators(admin: Api) -> None:
    text = (
        f"dn: ou=hooked,{BASE}\nobjectClass: organizationalUnit\nou: hooked\n"
        "fdTabHook: user|postcreate|true\n"
    )
    body = admin.post("/ldif/import", {"text": text}).json()
    assert "administrator" not in str(body["results"][0]["error"]), body


# -- CSV import ---------------------------------------------------------------------------------
CSV_TEXT = "login,first,last,mail\nzed,Zed,Zulu,zed@x.org\nbad,,Nobody,\nzoe,Zoe,Zulu,zoe@x.org\n"
MAPPING = [
    {"column": 0, "field": "main.uid"},
    {"column": 1, "field": "main.givenName"},
    {"column": 2, "field": "main.sn"},
    {"column": 3, "field": "main.mail"},
]


def test_csv_parse_preview(admin: Api) -> None:
    r = admin.post("/csv/parse", {"text": CSV_TEXT}).json()
    assert r["columns"] == ["login", "first", "last", "mail"]
    assert r["total"] == 3 and r["rows"][0] == ["zed", "Zed", "Zulu", "zed@x.org"]
    assert admin.post("/csv/parse", {"text": "a", "separator": "?"}).status_code == 422


def test_csv_fields(admin: Api) -> None:
    fields = admin.get("/csv/user/fields").json()
    keys = {f["key"] for f in fields}
    assert {"main.uid", "main.sn", "main.givenName"} <= keys
    sn = next(f for f in fields if f["key"] == "main.sn")
    assert sn["required"] is True and sn["multivalued"] is False
    assert admin.get("/csv/nope/fields").status_code == 404


def test_csv_import_reports_per_line(admin: Api) -> None:
    r = admin.post(
        "/csv/user/import",
        {
            "text": CSV_TEXT,
            "mapping": MAPPING,
            "fixed": {"main.description": "from csv"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 2 and body["failed"] == 1
    lines = {item["line"]: item for item in body["results"]}
    assert lines[2]["dn"] == f"uid=zed,ou=people,{BASE}" and lines[2]["error"] is None
    assert lines[3]["dn"] is None and "givenName" in lines[3]["error"]
    created = admin.directory.get(f"uid=zed,ou=people,{BASE}")
    assert created is not None
    assert created.text("description") == "from csv" and created.text("mail") == "zed@x.org"


def test_csv_import_uses_the_department_column(admin: Api) -> None:
    text = f'login,first,last,dept\nzed,Zed,Zulu,"ou=lyon,{BASE}"\n'
    mapping = [*MAPPING[:3], {"column": 3, "field": "main.base"}]
    body = admin.post("/csv/user/import", {"text": text, "mapping": mapping}).json()
    assert body["imported"] == 1
    assert body["results"][0]["dn"] == f"uid=zed,ou=people,ou=lyon,{BASE}"


def test_csv_import_rejects_bad_mappings(admin: Api) -> None:
    bad = admin.post(
        "/csv/user/import",
        {"text": CSV_TEXT, "mapping": [{"column": 0, "field": "main.nope"}]},
    )
    assert bad.status_code == 422 and "mapping.main.nope" in bad.json()["error"]["fields"]
    far = admin.post(
        "/csv/user/import", {"text": CSV_TEXT, "mapping": [{"column": 9, "field": "main.uid"}]}
    )
    assert far.status_code == 422
    unknown = admin.post(
        "/csv/user/import", {"text": CSV_TEXT, "mapping": MAPPING, "fixed": {"x.y": "1"}}
    )
    assert unknown.status_code == 422
    assert admin.post("/csv/nope/import", {"text": CSV_TEXT, "mapping": []}).status_code == 404


def test_csv_import_requires_rights(app: FastAPI) -> None:
    r = Api(app).login("helpdesk").post("/csv/user/import", {"text": CSV_TEXT, "mapping": MAPPING})
    assert r.status_code == 403


def test_csv_import_goes_through_acls(app: FastAPI) -> None:
    """Even with the CSV right, creating objects needs the create right of the type."""
    api = Api(app).login("admin")
    from heracles.acl import serialise_assignment, serialise_role_value
    from heracles.acl.model import AclAssignment, AclScope, RoleTemplateValue
    from heracles.acl.parser import parse_role_value
    from heracles.ldap.client import Modification
    from heracles.schema.legacy import ATTR, OC

    role = parse_role_value("0:csv/csvImport;rw")
    assert isinstance(role, RoleTemplateValue)
    role_dn = f"cn=csv-only,ou=aclroles,{BASE}"
    api.directory.add(
        role_dn,
        {
            "objectClass": [OC.ACL_ROLE.encode()],
            "cn": [b"csv-only"],
            ATTR.ACL_TEMPLATE: [serialise_role_value(role).encode()],
        },
    )
    member = f"uid=helpdesk,ou=people,{BASE}"
    value = serialise_assignment(
        AclAssignment(index=9, scope=AclScope.SUBTREE, role_dn=role_dn, members=(member,))
    ).encode()
    api.directory.modify(BASE, [Modification("add", ATTR.ACL_ENTRY, [value])])
    result = (
        Api(app)
        .login("helpdesk")
        .post("/csv/user/import", {"text": CSV_TEXT, "mapping": MAPPING})
        .json()
    )
    assert result["imported"] == 0 and result["failed"] == 3
    assert api.directory.get(f"uid=zed,ou=people,{BASE}") is None


def test_csv_import_with_a_template(admin: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def template_fields(ctx: object, type_name: str, template_dn: str) -> dict[str, list[str]]:
        return {"main": ["uid", "sn", "givenName"]}

    def apply_template(
        ctx: object, type_name: str, template_dn: str, values: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        seen["values"] = values
        return {"main": {**values["main"], "description": "from template"}}

    module = types.ModuleType("heracles.objects.templates")
    module.template_fields = template_fields  # type: ignore[attr-defined]
    module.apply_template = apply_template  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "heracles.objects.templates", module)
    tpl = f"cn=tpl,{BASE}"
    fields = admin.get("/csv/user/fields", template=tpl).json()
    assert {f["key"] for f in fields} == {"main.uid", "main.sn", "main.givenName"}
    ok = admin.post(
        "/csv/user/import", {"text": CSV_TEXT, "mapping": MAPPING[:3], "template": tpl}
    ).json()
    assert ok["imported"] == 2 and ok["failed"] == 1
    created = admin.directory.get(f"uid=zed,ou=people,{BASE}")
    assert created is not None and created.text("description") == "from template"
    # a field that the template does not ask for cannot be mapped
    refused = admin.post(
        "/csv/user/import", {"text": CSV_TEXT, "mapping": MAPPING, "template": tpl}
    )
    assert refused.status_code == 422


def test_csv_templates_unavailable(admin: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "heracles.objects.templates", None)
    assert admin.get("/csv/user/fields", template=f"cn=t,{BASE}").status_code == 501
