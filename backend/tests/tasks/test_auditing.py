"""Writes of scheduled task runners are recorded in the audit log."""

from __future__ import annotations

from heracles import demo
from heracles.core.audit import EVENT_CLASS, AuditSink, audit_container
from heracles.ldap.client import DirectoryClient, Entry, Modification, NoSuchObjectError, Scope
from heracles.objects import TypeRegistry
from heracles.objects.builtin import register_builtin_types
from heracles.tasks.auditing import AuditingDirectory


def setup(enabled: tuple[str, ...] = ("audit",)) -> tuple[DirectoryClient, AuditingDirectory]:
    directory = demo.build_demo_directory()
    registry = TypeRegistry()
    register_builtin_types(registry)
    registry.load_plugins(directory, enabled_names=enabled)
    return directory, AuditingDirectory(directory, AuditSink(registry), source="task lifecycle")


def events(directory: DirectoryClient) -> list[Entry]:
    try:
        return list(
            directory.search(audit_container(directory), f"(objectClass={EVENT_CLASS})", Scope.ONE)
        )
    except NoSuchObjectError:
        return []


def a_user(directory: DirectoryClient) -> str:
    return next(directory.search(demo.BASE, "(objectClass=inetOrgPerson)", Scope.SUBTREE)).dn


def test_runner_writes_are_recorded_with_their_source() -> None:
    directory, wrapped = setup()
    user = a_user(directory)
    wrapped.modify(
        user,
        [
            Modification("replace", "description", [b"expired"]),
            Modification("replace", "userPassword", [b"{SSHA}secret"]),
        ],
    )
    [event] = events(directory)
    assert event.text("hrcAuditAction") == "modify"
    assert event.text("hrcAuditObject") == user
    assert event.text("hrcAuditAuthorDN") is None
    lines = event.texts("hrcAuditAttributes")
    assert "replace description: expired" in lines
    assert "replace userPassword: ***" in lines
    assert "source: task lifecycle" in lines


def test_bookkeeping_and_the_log_itself_are_not_recorded() -> None:
    directory, wrapped = setup()
    user = a_user(directory)
    wrapped.modify(user, [Modification("replace", "hrcTasksLastExec", [b"20260101000000Z"])])
    assert events(directory) == []
    wrapped.modify(user, [Modification("replace", "description", [b"x"])])
    [event] = events(directory)
    wrapped.delete(event.dn)  # a retention purge
    assert events(directory) == []


def test_nothing_is_recorded_without_the_audit_plugin() -> None:
    directory, wrapped = setup(enabled=())
    wrapped.modify(a_user(directory), [Modification("replace", "description", [b"x"])])
    assert events(directory) == []
