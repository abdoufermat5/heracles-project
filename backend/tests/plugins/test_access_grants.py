"""Time-bound grants: end dates on memberships and ACL assignments, and their expiry."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from heracles.acl.model import AclAssignment, AclScope
from heracles.acl.parser import parse_assignment, serialise_assignment
from heracles.ldap.memory import MemoryDirectory
from heracles_plugins.access import grants as g

BASE = "dc=test"
ANN = f"uid=ann,ou=people,{BASE}"
BOB = f"uid=bob,ou=people,{BASE}"
GROUP = f"cn=devs,ou=groups,{BASE}"
ROLE = f"cn=oncall,ou=roles,{BASE}"
ACL_ROLE = f"cn=editors,ou=aclroles,{BASE}"
NOW = datetime(2030, 6, 15, 8, 0, tzinfo=UTC)


def acl_value(*members: str) -> bytes:
    return serialise_assignment(
        AclAssignment(index=0, scope=AclScope("subtree"), role_dn=ACL_ROLE, members=members)
    ).encode()


@pytest.fixture
def directory() -> MemoryDirectory:
    d = MemoryDirectory(BASE)
    d.add(BASE, {"objectClass": [b"domain"], "dc": [b"test"]})
    for ou in ("people", "groups", "roles"):
        d.add(f"ou={ou},{BASE}", {"objectClass": [b"organizationalUnit"], "ou": [ou.encode()]})
    for uid in ("ann", "bob"):
        d.add(
            f"uid={uid},ou=people,{BASE}",
            {
                "objectClass": [b"inetOrgPerson"],
                "uid": [uid.encode()],
                "cn": [uid.encode()],
                "sn": [b"x"],
            },
        )
    d.add(
        GROUP,
        {"objectClass": [b"groupOfNames"], "cn": [b"devs"], "member": [ANN.encode(), BOB.encode()]},
    )
    d.add(
        ROLE,
        {"objectClass": [b"organizationalRole"], "cn": [b"oncall"], "roleOccupant": [ANN.encode()]},
    )
    d.modify(
        f"ou=groups,{BASE}",
        [
            g.Modification("add", "objectClass", [b"hrcAcl"]),
            g.Modification("add", "hrcAclEntry", [acl_value(ANN, BOB)]),
        ],
    )
    return d


def dates(d: MemoryDirectory, dn: str) -> list[str]:
    entry = d.get(dn)
    assert entry is not None
    return entry.texts(g.GRANT_ATTR)


def test_value_round_trip() -> None:
    grant = g.Grant(GROUP, "member", ANN, NOW)
    assert grant.value() == f"20300615080000Z member {ANN}"
    assert g.parse_grant(GROUP, grant.value()) == grant
    acl = g.Grant(GROUP, g.ACL_KIND, ANN, NOW, acl_scope="subtree", acl_role=ACL_ROLE)
    assert g.parse_grant(GROUP, acl.value()) == acl
    assert g.parse_grant(GROUP, "garbage") is None
    assert g.parse_grant(GROUP, f"20300615080000Z owner {ANN}") is None


def test_set_and_clear_end_date(directory: MemoryDirectory) -> None:
    g.set_end_date(directory, GROUP, "member", "UID=ann, ou=people, dc=test", NOW)
    entry = directory.get(GROUP)
    assert entry is not None and entry.has_object_class(g.GRANT_CLASS)
    assert dates(directory, GROUP) == ["20300615080000Z member UID=ann, ou=people, dc=test"]
    # a new date replaces the old one
    g.set_end_date(directory, GROUP, "member", ANN, NOW + timedelta(days=1))
    assert dates(directory, GROUP) == [f"20300616080000Z member {ANN}"]
    g.set_end_date(directory, GROUP, "member", ANN, None)
    assert dates(directory, GROUP) == []


def test_end_date_needs_an_existing_grant(directory: MemoryDirectory) -> None:
    with pytest.raises(g.GrantError):
        g.set_end_date(directory, ROLE, "roleOccupant", BOB, NOW)
    with pytest.raises(g.GrantError):
        g.set_end_date(directory, GROUP, "owner", ANN, NOW)
    with pytest.raises(g.GrantError):
        g.set_end_date(directory, f"ou=groups,{BASE}", g.ACL_KIND, ANN, NOW)  # no role given


def test_expiry_removes_only_what_is_due(directory: MemoryDirectory) -> None:
    g.set_end_date(directory, GROUP, "member", ANN, NOW - timedelta(minutes=1))
    g.set_end_date(directory, GROUP, "member", BOB, NOW + timedelta(days=3))
    g.set_end_date(directory, ROLE, "roleOccupant", ANN, NOW - timedelta(days=1))
    report = g.expire_grants(directory, NOW)
    assert report.expired == 2 and not report.errors
    group = directory.get(GROUP)
    role = directory.get(ROLE)
    assert group is not None and role is not None
    assert group.texts("member") == [BOB]
    assert dates(directory, GROUP) == [f"20300618080000Z member {BOB}"]
    assert role.get("roleOccupant") == [] and dates(directory, ROLE) == []
    assert g.expire_grants(directory, NOW).expired == 0


def test_acl_assignment_member_expires(directory: MemoryDirectory) -> None:
    holder = f"ou=groups,{BASE}"
    g.set_end_date(
        directory,
        holder,
        g.ACL_KIND,
        ANN,
        NOW - timedelta(seconds=1),
        acl_scope="subtree",
        acl_role=ACL_ROLE,
    )
    assert g.expire_grants(directory, NOW).expired == 1
    entry = directory.get(holder)
    assert entry is not None
    (raw,) = entry.texts("hrcAclEntry")
    parsed = parse_assignment(raw)
    assert isinstance(parsed, AclAssignment) and parsed.members == (BOB,)
    # the last member going removes the assignment
    g.set_end_date(directory, holder, g.ACL_KIND, BOB, NOW, acl_scope="subtree", acl_role=ACL_ROLE)
    g.expire_grants(directory, NOW + timedelta(seconds=1))
    entry = directory.get(holder)
    assert entry is not None and entry.get("hrcAclEntry") == []


def test_dates_left_without_a_grant_are_dropped(directory: MemoryDirectory) -> None:
    g.set_end_date(directory, GROUP, "member", ANN, NOW + timedelta(days=30))
    directory.modify(GROUP, [g.Modification("delete", "member", [ANN.encode()])])
    report = g.expire_grants(directory, NOW)
    assert report.dropped == 1 and report.expired == 0
    assert dates(directory, GROUP) == []


def test_dated_memberships_of_a_person(directory: MemoryDirectory) -> None:
    g.set_end_date(directory, GROUP, "member", ANN, NOW)
    g.set_end_date(directory, ROLE, "roleOccupant", ANN, NOW)
    g.set_end_date(directory, GROUP, "member", BOB, NOW)
    found = {(x.holder, x.kind) for x in g.dated_memberships(directory, ANN)}
    assert found == {(GROUP, "member"), (ROLE, "roleOccupant")}


def test_removed_memberships_name_their_dates(directory: MemoryDirectory) -> None:
    g.set_end_date(directory, GROUP, "member", ANN, NOW)
    g.set_end_date(directory, GROUP, "member", BOB, NOW)
    entry = directory.get(GROUP)
    assert entry is not None
    assert g.end_dates_for_removed(entry, [("member", ANN)]) == [
        f"20300615080000Z member {ANN}".encode()
    ]


def test_runner_expires_through_the_auditing_directory(directory: MemoryDirectory) -> None:
    import heracles_plugins.access as access
    import heracles_plugins.audit as audit
    from heracles.core.audit import AuditSink
    from heracles.objects import TypeRegistry
    from heracles.objects.builtin import register_builtin_types
    from heracles.objects.task_runner import TaskRunContext
    from heracles.tasks.auditing import AuditingDirectory

    directory.set_schema_object_classes(
        [*directory.schema_object_classes(), "hrcAuditEvent", "hrcGrantExpiries"]
    )
    registry = TypeRegistry()
    register_builtin_types(registry)
    classes = {c.lower() for c in directory.schema_object_classes()}
    registry.register_plugin(audit.plugin(), classes)
    registry.register_plugin(access.plugin(), classes)
    g.set_end_date(directory, GROUP, "member", ANN, NOW - timedelta(minutes=1))
    wrapped = AuditingDirectory(directory, AuditSink(registry), source="task access")
    ctx = TaskRunContext(directory=wrapped, now=NOW, settings=None, mailer=None, registry=registry)
    report = access._run(ctx)  # pyright: ignore[reportPrivateUsage]
    assert report.grants_expired == 1
    events = list(directory.search(f"ou=audit,{BASE}", "(hrcAuditAction=modify)"))
    lines = [line for e in events for line in e.texts("hrcAuditAttributes")]
    assert f"delete member: {ANN}" in lines and "source: task access" in lines
