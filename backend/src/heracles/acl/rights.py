"""Immutable access-rights value."""

from __future__ import annotations

from dataclasses import dataclass, field

_ORDER = "rwcdmt"


class RightsParseError(ValueError):
    """Raised when a rights string contains an unknown letter."""


@dataclass(frozen=True, slots=True)
class Rights:
    """A set of rights: read, write, create, delete, move, template + self flag.

    ``self_only`` is the ``s`` flag: the block carrying these rights only applies
    when the target object is the connected user. Rights merge by union.
    """

    read: bool = False
    write: bool = False
    create: bool = False
    delete: bool = False
    move: bool = False
    template: bool = False
    self_only: bool = False
    # Original spelling, kept so that serialisation round-trips exactly.
    spelling: str | None = field(default=None, compare=False, repr=False)

    @classmethod
    def parse(cls, text: str) -> Rights:
        """Parse a rights string such as ``"cmdrw"`` or ``"sr"``."""
        unknown = {ch for ch in text if ch not in _ORDER + "s"}
        if unknown:
            raise RightsParseError(f"unknown rights letters: {''.join(sorted(unknown))}")
        return cls(
            read="r" in text,
            write="w" in text,
            create="c" in text,
            delete="d" in text,
            move="m" in text,
            template="t" in text,
            self_only="s" in text,
            spelling=text,
        )

    @classmethod
    def none(cls) -> Rights:
        """No rights."""
        return cls()

    @classmethod
    def full(cls) -> Rights:
        """Full rights: r, w, c, d, m."""
        return cls(read=True, write=True, create=True, delete=True, move=True)

    def canonical(self) -> str:
        """Canonical string: ``s`` first, then the subset of ``rwcdmt`` in that order."""
        flags = (self.read, self.write, self.create, self.delete, self.move, self.template)
        letters = "".join(ch for ch, on in zip(_ORDER, flags, strict=True) if on)
        return ("s" if self.self_only else "") + letters

    def __str__(self) -> str:
        return self.spelling if self.spelling is not None else self.canonical()

    def union(self, other: Rights) -> Rights:
        """Merge by OR (the self flag is OR-ed too; evaluation strips it)."""
        return Rights(
            read=self.read or other.read,
            write=self.write or other.write,
            create=self.create or other.create,
            delete=self.delete or other.delete,
            move=self.move or other.move,
            template=self.template or other.template,
            self_only=self.self_only or other.self_only,
        )

    def __or__(self, other: Rights) -> Rights:
        return self.union(other)

    @property
    def is_full(self) -> bool:
        """True when r, w, c, d and m are all set."""
        return self.read and self.write and self.create and self.delete and self.move

    @property
    def is_empty(self) -> bool:
        """True when no right letter is set (the self flag is ignored)."""
        return not (
            self.read or self.write or self.create or self.delete or self.move or self.template
        )

    def read_only(self) -> Rights:
        """Strip write, create, delete and move."""
        return Rights(read=self.read, template=self.template, self_only=self.self_only)

    def without_self(self) -> Rights:
        """Same rights with the self flag cleared."""
        return Rights(
            self.read, self.write, self.create, self.delete, self.move, self.template, False
        )

    def issubset(self, other: Rights) -> bool:
        """True when every right letter set here is also set in ``other``."""
        return (
            (not self.read or other.read)
            and (not self.write or other.write)
            and (not self.create or other.create)
            and (not self.delete or other.delete)
            and (not self.move or other.move)
            and (not self.template or other.template)
        )


NO_RIGHTS = Rights()
FULL_RIGHTS = Rights.full()
