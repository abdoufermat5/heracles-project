"""Object writes that can change ACLs bump the directory-wide ACL counter."""

from __future__ import annotations

from heracles.api.domain import AclChanges
from heracles.objects.policy import EventContext
from heracles.objects.state import ObjectState
from heracles.schema import names as schema


def _state(*classes: str) -> ObjectState:
    return ObjectState.build("cn=x,dc=example,dc=org", "t", {}, {}, list(classes))


def test_acl_changes_only_for_acl_entries_and_deletes() -> None:
    calls: list[None] = []
    hook = AclChanges(lambda: calls.append(None))
    plain, role = _state("inetOrgPerson"), _state(schema.OC.ACL_ROLE)
    holder = _state("organizationalUnit", schema.OC.ACL_ASSIGNMENT)

    hook.post_create(EventContext("t", "dn", None, plain))
    hook.post_modify(EventContext("t", "dn", plain, plain))
    assert calls == []
    hook.post_create(EventContext("t", "dn", None, role))
    hook.post_modify(EventContext("t", "dn", holder, plain))  # assignments removed
    hook.post_delete(EventContext("t", "dn", plain, None))  # references are dropped
    assert len(calls) == 3
