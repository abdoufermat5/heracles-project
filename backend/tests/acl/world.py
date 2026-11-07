"""Test fixture builder: a small directory plus helpers to assemble ACLs."""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence

from heracles.acl import (
    AclEvaluator,
    AclResolver,
    LdapAclDirectory,
    ResolvedAcl,
)
from tests.acl.fakes import MemoryClient

BASE = "dc=example,dc=org"
ROLES = f"ou=aclroles,{BASE}"
CATEGORY_TABS: dict[str, list[str]] = {
    "user": ["user", "posixAccount", "mailAccount"],
    "group": ["ogroup"],
    "department": ["department"],
}


def b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


class World:
    def __init__(self) -> None:
        self.client = MemoryClient(BASE)
        self.client.put(BASE, objectClass=["dcObject", "organization"])
        self.client.put(ROLES, objectClass=["organizationalUnit"])
        self._counter = 0

    # -- entries ---------------------------------------------------------
    def ensure(self, dn: str) -> None:
        if self.client.get(dn) is None:
            self.client.put(dn, objectClass=["organizationalUnit"])

    def user(self, uid: str, ou: str = "ou=people", **attrs: Sequence[str]) -> str:
        dn = f"uid={uid},{ou},{BASE}"
        self.ensure(f"{ou},{BASE}")
        self.client.put(dn, objectClass=["inetOrgPerson"], uid=[uid], **attrs)
        return dn

    def group(self, cn: str, members: Sequence[str]) -> str:
        dn = f"cn={cn},ou=groups,{BASE}"
        self.ensure(f"ou=groups,{BASE}")
        self.client.put(dn, objectClass=["groupOfNames"], member=list(members))
        return dn

    def posix_group(self, cn: str, uids: Sequence[str]) -> str:
        dn = f"cn={cn},ou=groups,{BASE}"
        self.ensure(f"ou=groups,{BASE}")
        self.client.put(dn, objectClass=["posixGroup"], memberUid=list(uids))
        return dn

    def occupation(self, cn: str, occupants: Sequence[str]) -> str:
        dn = f"cn={cn},ou=roles,{BASE}"
        self.ensure(f"ou=roles,{BASE}")
        self.client.put(dn, objectClass=["organizationalRole"], roleOccupant=list(occupants))
        return dn

    def acl_role(self, cn: str, *values: str) -> str:
        dn = f"cn={cn},{ROLES}"
        self.client.put(dn, objectClass=["gosaRole"], gosaAclTemplate=list(values))
        return dn

    def assign(
        self,
        on: str,
        role_dn: str,
        members: Sequence[str],
        scope: str = "subtree",
        userfilter: str | None = None,
        targetfilter: str | None = None,
        *,
        raw_members: bool = False,
    ) -> str:
        """Add an assignment value on ``on`` (members are plain DNs or ``*``)."""
        self.ensure(on)
        self._counter += 1
        ms = ",".join(members if raw_members else [b64(m) for m in members])
        value = f"{self._counter}:{scope}:{b64(role_dn)}:{ms}"
        if userfilter is not None or targetfilter is not None:
            value += ":" + (b64(userfilter) if userfilter else "")
        if targetfilter is not None:
            value += ":" + b64(targetfilter)
        self.add_value(on, value)
        return value

    def add_value(self, on: str, value: str) -> None:
        entry = self.client.get(on)
        assert entry is not None
        classes = entry.attrs.setdefault("objectClass", [])
        if b"gosaAcl" not in classes:
            classes.append(b"gosaAcl")
        entry.attrs.setdefault("gosaAclEntry", []).append(value.encode())

    # -- resolution ------------------------------------------------------
    def resolve(
        self,
        user_dn: str,
        *,
        uid: str | None = None,
        attrs: Mapping[str, Sequence[str]] | None = None,
        limit: int = 100,
    ) -> ResolvedAcl:
        resolver = AclResolver(LdapAclDirectory(self.client), target_limit=limit)
        return resolver.resolve(user_dn, uid=uid, user_attrs=attrs)

    def evaluator(
        self,
        user_dn: str,
        *,
        uid: str | None = None,
        attrs: Mapping[str, Sequence[str]] | None = None,
        limit: int = 100,
    ) -> AclEvaluator:
        resolved = self.resolve(user_dn, uid=uid, attrs=attrs, limit=limit)
        return AclEvaluator(resolved, category_tabs=CATEGORY_TABS)
