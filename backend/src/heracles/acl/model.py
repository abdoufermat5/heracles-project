"""ACL data model: role template values and assignment values."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from heracles.acl.rights import NO_RIGHTS, Rights

ALL_USERS = "*"
"""Member literal meaning every user."""

ALL_OBJECTS = "all"
"""Object key of the block that applies to every object type."""


class AclScope(StrEnum):
    """Scope of an assignment."""

    SUBTREE = "subtree"
    BASE = "base"


@dataclass(frozen=True, slots=True)
class AclBlock:
    """Rights on one object key: object-level rights plus per-attribute rights."""

    object: str
    rights: Rights = NO_RIGHTS
    attributes: tuple[tuple[str, Rights], ...] = ()
    #: Object-level rights that only apply to the user's own entry and that were merged into
    #: a block holding rights for everybody (``user/user;r`` + ``user/user;sw``): ``rights``
    #: then stays the part that applies to every entry.
    self_rights: Rights = NO_RIGHTS

    @property
    def is_self(self) -> bool:
        """True when the block only applies to the connected user's own entry."""
        return self.rights.self_only

    def object_rights(self, *, own: bool = True) -> Rights:
        """Object-level rights that apply to an entry (``own``: the user's own entry)."""
        return self.rights.union(self.self_rights) if own else self.rights

    def merge(self, other: AclBlock) -> AclBlock:
        """Merge two blocks of the same object key, keeping self-only rights apart.

        Rights flagged ``s`` stay confined to the user's own entry; the ones that apply to
        every entry are never widened or narrowed by the other block's flag.
        """
        everyone = [b for b in (self, other) if not b.is_self]
        selfish = [b for b in (self, other) if b.is_self]
        if not everyone or not selfish:
            return AclBlock(
                self.object,
                self.rights.union(other.rights),
                self.attributes + other.attributes,
                self.self_rights.union(other.self_rights),
            )
        rights = NO_RIGHTS
        self_rights = NO_RIGHTS
        attributes: list[tuple[str, Rights]] = []
        for b in everyone:
            rights = rights.union(b.rights)
            self_rights = self_rights.union(b.self_rights)
            attributes.extend(b.attributes)
        for b in selfish:
            self_rights = self_rights.union(b.rights.without_self())
            self_rights = self_rights.union(b.self_rights)
            attributes.extend((n, replace(r, self_only=True)) for n, r in b.attributes)
        return AclBlock(self.object, rights, tuple(attributes), self_rights.without_self())

    def attribute_rights(self, attribute: str, *, own: bool = True) -> Rights:
        """Union of the rights granted on ``attribute`` (case-insensitive).

        An attribute entry flagged ``s`` only counts when ``own`` is true.
        """
        lname = attribute.lower()
        result = NO_RIGHTS
        for name, rights in self.attributes:
            if name.lower() == lname and (own or not rights.self_only):
                result = result.union(rights)
        return result

    def all_rights(self, *, own: bool = True) -> Rights:
        """Union of object-level and every attribute-level right."""
        result = self.object_rights(own=own)
        for _, rights in self.attributes:
            if own or not rights.self_only:
                result = result.union(rights)
        return result


@dataclass(frozen=True, slots=True)
class RoleTemplateValue:
    """One value of a role's template attribute: ``<index>:<blocks>``."""

    index: int
    blocks: tuple[AclBlock, ...]

    def block_map(self) -> dict[str, AclBlock]:
        """Blocks by object key; a repeated key is merged into one block."""
        result: dict[str, AclBlock] = {}
        for block in self.blocks:
            previous = result.get(block.object)
            if previous is None:
                result[block.object] = block
            else:
                result[block.object] = previous.merge(block)
        return result


@dataclass(frozen=True, slots=True)
class AclAssignment:
    """One value of the assignment attribute (rights of a role on a DN)."""

    index: int
    scope: AclScope
    role_dn: str
    members: tuple[str, ...]  # DNs, or ``"*"`` for all users
    user_filter: str | None = None
    target_filter: str | None = None

    @property
    def applies_to_everyone(self) -> bool:
        return ALL_USERS in self.members


@dataclass(frozen=True, slots=True)
class Ignored:
    """Result for a value that cannot be used; callers must skip it."""

    raw: str
    reason: str


@dataclass(frozen=True, slots=True)
class AclWarning:
    """Administrator-visible problem found while resolving ACLs."""

    code: str
    message: str
    dn: str = ""


@dataclass(frozen=True, slots=True)
class Rule:
    """A role block map attached to a target DN."""

    origin: str  # normalised DN the rule is attached to
    scope: AclScope
    blocks: dict[str, AclBlock]
