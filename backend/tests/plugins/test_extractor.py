"""Extractor plugin: CSV content, file and mail delivery, safety, schedule, CRUD."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import heracles_plugins.extractor as ex
from heracles.auth.mail import MemoryMailer
from heracles.ldap.memory import MemoryDirectory
from heracles.objects import ObjectService, ObjectValidationError, TypeRegistry
from heracles.objects.builtin import register_builtin_types

BASE = "dc=test"
PEOPLE = f"ou=people,{BASE}"
GROUPS = f"ou=groups,{BASE}"
TASKS = f"ou=tasks,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)
TASK_DN = f"cn=export,{TASKS}"


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.set_schema_object_classes([*d.schema_object_classes(), "fdExtractorTasks"])
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    for dn, ou in ((PEOPLE, "people"), (GROUPS, "groups"), (TASKS, "tasks")):
        d.add(dn, {"objectClass": [b"organizationalUnit"], "ou": [ou.encode()]})
    return d


def add_user(d: MemoryDirectory, uid: str, **extra: list[str]) -> str:
    dn = f"uid={uid},{PEOPLE}"
    attrs: dict[str, list[bytes]] = {
        "objectClass": [b"inetOrgPerson"],
        "uid": [uid.encode()],
        "cn": [f"{uid.title()} Doe".encode()],
        "sn": [b"Doe"],
        "userPassword": [b"{SSHA}secret"],
    }
    attrs.update({k: [v.encode() for v in vs] for k, vs in extra.items()})
    d.add(dn, attrs)
    return dn


def add_task(d: MemoryDirectory, members: list[str], attributes: list[str], **extra: str) -> None:
    attrs: dict[str, list[bytes]] = {
        "objectClass": [b"fdTasks", b"fdExtractorTasks"],
        "cn": [b"export"],
        "fdTasksStatus": [b"Activated"],
        "fdExtractorTaskMembers": [m.encode() for m in members],
        "fdExtractorTaskAttributes": [a.encode() for a in attributes],
    }
    for key, value in extra.items():
        attrs[key] = [v.encode() for v in value.split("|")]
    d.add(TASK_DN, attrs)


def test_csv_to_a_file(directory: MemoryDirectory, tmp_path: Path) -> None:
    a = add_user(directory, "alice", mail=["a@example.com", "alice@example.com"])
    b = add_user(directory, "bob")
    add_task(directory, [b, a], ["uid", "cn", "mail"])
    settings = ex.ExtractorSettings(export_directory=str(tmp_path / "out"))
    report = ex.run_extractor(directory, MemoryMailer(), NOW, settings)
    assert report.tasks_run == 1
    record = report.extractions[0]
    assert record.rows == 2 and record.path is not None
    path = Path(record.path)
    assert path.name == "export-20300615T080000Z.csv"
    assert path.read_text() == (
        "uid,cn,mail\nalice,Alice Doe,a@example.com; alice@example.com\nbob,Bob Doe,\n"
    )
    assert path.stat().st_mode & 0o777 == 0o600


def test_mail_delivery_and_expansion(directory: MemoryDirectory) -> None:
    a = add_user(directory, "alice")
    b = add_user(directory, "bob")
    boss = add_user(directory, "boss", mail=["boss@example.com"])
    directory.add(
        f"cn=team,{GROUPS}",
        {"objectClass": [b"groupOfNames"], "cn": [b"team"], "member": [a.encode(), b.encode()]},
    )
    add_task(
        directory,
        [f"cn=team,{GROUPS}"],
        ["uid", "sn"],
        fdExtractorRecipientsMembers=boss,
        fdExtractorEmailSender="noreply@example.com",
        fdExtractorTaskFormat="tsv",
    )
    mailer = MemoryMailer()
    report = ex.run_extractor(directory, mailer, NOW, ex.ExtractorSettings())
    assert report.mails_sent == 1 and report.extractions[0].path is None
    mail = mailer.outbox[0]
    assert mail.to == "boss@example.com" and mail.sender == "noreply@example.com"
    assert mail.subject == "Heracles export: export"
    assert mail.body == "uid\tsn\nalice\tDoe\nbob\tDoe\n"


def test_formula_cells_are_neutralised_and_secrets_never_exported(
    directory: MemoryDirectory, tmp_path: Path
) -> None:
    a = add_user(directory, "alice", description=["=HYPERLINK(1)"], telephoneNumber=["+33 1 23"])
    add_task(directory, [a], ["telephoneNumber", "userPassword", "description"])
    settings = ex.ExtractorSettings(
        attributes=("telephoneNumber", "userPassword", "description"),
        export_directory=str(tmp_path),
    )
    report = ex.run_extractor(directory, MemoryMailer(), NOW, settings)
    assert report.extractions[0].path is not None
    text = Path(report.extractions[0].path).read_text()
    assert text.splitlines()[0] == "telephoneNumber,description"
    assert "'+33 1 23" in text
    assert "SSHA" not in text
    assert "'=HYPERLINK(1)" in text


def test_attributes_outside_the_settings_are_dropped(
    directory: MemoryDirectory, tmp_path: Path
) -> None:
    a = add_user(directory, "alice", description=["secret note"])
    add_task(directory, [a], ["uid", "description"])
    report = ex.run_extractor(
        directory, MemoryMailer(), NOW, ex.ExtractorSettings(export_directory=str(tmp_path))
    )
    assert report.extractions[0].path is not None
    assert Path(report.extractions[0].path).read_text() == "uid\nalice\n"


def test_no_destination_no_attribute_and_write_failure(
    directory: MemoryDirectory, tmp_path: Path
) -> None:
    a = add_user(directory, "alice")
    add_task(directory, [a], ["uid"])
    report = ex.run_extractor(directory, MemoryMailer(), NOW, ex.ExtractorSettings())
    assert report.tasks_run == 0 and "no destination" in report.errors[0]
    blocker = tmp_path / "file"
    blocker.write_text("x")
    report = ex.run_extractor(
        directory, MemoryMailer(), NOW, ex.ExtractorSettings(export_directory=str(blocker / "sub"))
    )
    assert report.tasks_run == 0 and "cannot write" in report.errors[0]
    directory.delete(TASK_DN)
    add_task(directory, [a], ["userPassword"])
    report = ex.run_extractor(
        directory, MemoryMailer(), NOW, ex.ExtractorSettings(export_directory=str(tmp_path))
    )
    assert report.tasks_run == 0 and "no exported attribute" in report.errors[0]


def test_task_runs_once_and_is_deactivated_when_not_repeatable(
    directory: MemoryDirectory, tmp_path: Path
) -> None:
    a = add_user(directory, "alice")
    add_task(directory, [a], ["uid"])
    settings = ex.ExtractorSettings(export_directory=str(tmp_path))
    assert ex.run_extractor(directory, MemoryMailer(), NOW, settings).tasks_run == 1
    assert ex.run_extractor(directory, MemoryMailer(), NOW, settings).tasks_run == 0
    entry = directory.get(TASK_DN)
    assert entry is not None and entry.text("fdTasksStatus") == "Deactivated"


def test_render_csv_quotes_values() -> None:
    from heracles.ldap.client import Entry

    user = Entry("uid=a", {"cn": [b'Doe, "J"'], "uid": [b"a"]})
    assert ex.render_csv([user], ["uid", "cn"]) == 'uid,cn\na,"Doe, ""J"""\n'


def test_task_type_and_validation(directory: MemoryDirectory) -> None:
    registry = TypeRegistry()
    register_builtin_types(registry)
    assert registry.register_plugin(
        ex.plugin(), {c.lower() for c in directory.schema_object_classes()}
    ).enabled
    info = registry.get("extractor_task")
    assert info.acl_object(info.main_tab) == "tasks/extractorTask"
    assert info.type.filter == "(&(objectClass=fdTasks)(objectClass=fdExtractorTasks))"
    a = add_user(directory, "alice")
    service = ObjectService(directory, registry)
    dn = service.create(
        "extractor_task",
        BASE,
        {
            "main": {
                "values": {
                    "cn": "export",
                    "fdExtractorTaskMembers": [a],
                    "fdExtractorTaskAttributes": ["uid", "mail"],
                    "fdExtractorTaskFormat": "csv",
                }
            }
        },
    )
    entry = directory.get(dn)
    assert entry is not None and entry.texts("fdExtractorTaskAttributes") == ["uid", "mail"]
    with pytest.raises(ObjectValidationError):
        service.create(
            "extractor_task",
            BASE,
            {
                "main": {
                    "values": {
                        "cn": "bad",
                        "fdExtractorTaskMembers": [a],
                        "fdExtractorTaskAttributes": ["userPassword"],
                    }
                }
            },
        )
