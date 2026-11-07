"""Directory access contract.

Every module talks to LDAP through :class:`DirectoryClient`. Two
implementations are provided by the ``ldap`` package:

* ``heracles.ldap.pyldap.PyLdapDirectory`` — real server (python-ldap);
* ``heracles.ldap.memory.MemoryDirectory`` — in-memory fake for tests.

This file is a shared contract: change it only in coordination with every
stream (see docs/specs/00-architecture.md).
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

AttrValues = list[bytes]
Attributes = dict[str, AttrValues]


class Scope(StrEnum):
    """LDAP search scope."""

    BASE = "base"
    ONE = "one"
    SUBTREE = "sub"


@dataclass(slots=True)
class Entry:
    """An LDAP entry. Attribute names are matched case-insensitively."""

    dn: str
    attrs: Attributes = field(default_factory=lambda: {})

    def get(self, name: str) -> AttrValues:
        """Return values of ``name`` (case-insensitive), or an empty list."""
        lname = name.lower()
        for key, values in self.attrs.items():
            if key.lower() == lname:
                return values
        return []

    def first(self, name: str) -> bytes | None:
        """Return the first value of ``name`` or ``None``."""
        values = self.get(name)
        return values[0] if values else None

    def text(self, name: str) -> str | None:
        """Return the first value of ``name`` decoded as UTF-8, or ``None``."""
        value = self.first(name)
        return value.decode("utf-8") if value is not None else None

    def texts(self, name: str) -> list[str]:
        """Return all values of ``name`` decoded as UTF-8."""
        return [v.decode("utf-8") for v in self.get(name)]

    def has_object_class(self, oc: str) -> bool:
        """Case-insensitive objectClass membership test."""
        loc = oc.lower()
        return any(v.decode("utf-8").lower() == loc for v in self.get("objectClass"))


@dataclass(frozen=True, slots=True)
class Modification:
    """One change of a ``modify`` operation."""

    op: Literal["add", "replace", "delete"]
    attr: str
    values: Sequence[bytes] = ()  # empty + delete => delete whole attribute


class DirectoryError(Exception):
    """Base error for directory operations."""


class NoSuchObjectError(DirectoryError):
    """The target entry does not exist."""


class AlreadyExistsError(DirectoryError):
    """The entry to add already exists."""


class InvalidCredentialsError(DirectoryError):
    """Bind failed because of wrong credentials."""


class SizeLimitExceededError(DirectoryError):
    """A search returned more entries than allowed."""


@runtime_checkable
class DirectoryClient(Protocol):
    """Synchronous directory access (run it in a worker thread from async code)."""

    @property
    def base_dn(self) -> str:
        """Root DN managed by Heracles for this directory."""
        ...

    def search(
        self,
        base: str,
        filterstr: str = "(objectClass=*)",
        scope: Scope = Scope.SUBTREE,
        attrs: Sequence[str] | None = None,
        *,
        size_limit: int = 0,
        page_size: int = 500,
    ) -> Iterator[Entry]:
        """Iterate matching entries (paged). ``size_limit`` 0 = unlimited.

        Raises :class:`SizeLimitExceededError` when ``size_limit`` is exceeded and
        :class:`NoSuchObjectError` when ``base`` does not exist.
        """
        ...

    def get(self, dn: str, attrs: Sequence[str] | None = None) -> Entry | None:
        """Read one entry (base search), or ``None`` if it does not exist."""
        ...

    def add(self, dn: str, attrs: Mapping[str, Sequence[bytes]]) -> None:
        """Create an entry."""
        ...

    def modify(self, dn: str, changes: Sequence[Modification]) -> None:
        """Apply all changes atomically on one entry."""
        ...

    def delete(self, dn: str, *, recursive: bool = False) -> None:
        """Delete an entry (and its subtree when ``recursive``)."""
        ...

    def rename(self, dn: str, new_rdn: str, new_superior: str | None = None) -> str:
        """modrdn (delete old RDN value); returns the new DN."""
        ...

    def check_password(self, dn: str, password: str) -> bool:
        """Bind as ``dn`` on a separate connection; True on success."""
        ...

    def schema_object_classes(self) -> set[str]:
        """Lower-cased names of objectClasses known by the server schema."""
        ...
