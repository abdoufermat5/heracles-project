"""ACL data model: role template values and assignment values."""

from __future__ import annotations

from dataclasses import dataclass
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

    @property
    def is_self(self) -> bool:
        """True when the block only applies to the connected user's own entry."""
        return self.rights.self_only

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
        result = self.rights
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
                result[block.object] = AclBlock(
                    block.object,
                    previous.rights.union(block.rights),
                    previous.attributes + block.attributes,
                )
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
