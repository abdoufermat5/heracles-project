"""Building blocks of the Heracles LDAP schema (see :mod:`heracles.schema.definitions`)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Final

OID_BASE: Final = "2.25.147659383274657253636041013514546701909"
"""Root of every Heracles OID.

A ``2.25`` arc is derived from a random UUID (ITU-T X.667): it is globally unique
without any registration. It is permanent: changing it would make every deployed
directory incompatible with the shipped schema.
"""

ATTRIBUTE_ARC: Final = f"{OID_BASE}.1"
OBJECT_CLASS_ARC: Final = f"{OID_BASE}.2"

_DIRECTORY_STRING: Final = "1.3.6.1.4.1.1466.115.121.1.15"
_IA5_STRING: Final = "1.3.6.1.4.1.1466.115.121.1.26"
_INTEGER: Final = "1.3.6.1.4.1.1466.115.121.1.27"
_BOOLEAN: Final = "1.3.6.1.4.1.1466.115.121.1.7"
_GENERALIZED_TIME: Final = "1.3.6.1.4.1.1466.115.121.1.24"
_DN: Final = "1.3.6.1.4.1.1466.115.121.1.12"
_OCTET_STRING: Final = "1.3.6.1.4.1.1466.115.121.1.40"


class Syntax(Enum):
    """LDAP syntax plus matching rules: ``(syntax oid, equality, ordering, substr)``."""

    STRING = (_DIRECTORY_STRING, "caseIgnoreMatch", None, "caseIgnoreSubstringsMatch")
    """Case-insensitive text (the default)."""
    EXACT = (_DIRECTORY_STRING, "caseExactMatch", None, "caseExactSubstringsMatch")
    """Case-sensitive text (tokens, hashes, encoded values)."""
    IA5 = (_IA5_STRING, "caseIgnoreIA5Match", None, "caseIgnoreIA5SubstringsMatch")
    """ASCII text such as e-mail addresses."""
    INTEGER = (_INTEGER, "integerMatch", "integerOrderingMatch", None)
    BOOLEAN = (_BOOLEAN, "booleanMatch", None, None)
    """``TRUE`` / ``FALSE``."""
    TIME = (_GENERALIZED_TIME, "generalizedTimeMatch", "generalizedTimeOrderingMatch", None)
    """GeneralizedTime (``YYYYMMDDHHMMSSZ``)."""
    DN = (_DN, "distinguishedNameMatch", None, None)
    BINARY = (_OCTET_STRING, "octetStringMatch", None, None)
    """Raw bytes (images, compressed data)."""
    SECRET = (_OCTET_STRING, "octetStringMatch", None, None)
    """Passwords and other secrets (bytes, never searched by substring)."""

    @property
    def oid(self) -> str:
        return self.value[0]

    @property
    def equality(self) -> str:
        return self.value[1]

    @property
    def ordering(self) -> str | None:
        return self.value[2]

    @property
    def substr(self) -> str | None:
        return self.value[3]


@dataclass(frozen=True, slots=True)
class AttributeType:
    """One attribute type; ``number`` is the last arc of its OID (never reused)."""

    number: int
    name: str
    syntax: Syntax = Syntax.STRING
    single: bool = False
    desc: str = ""

    @property
    def oid(self) -> str:
        return f"{ATTRIBUTE_ARC}.{self.number}"


@dataclass(frozen=True, slots=True)
class ObjectClass:
    """One objectClass; ``number`` is the last arc of its OID (never reused)."""

    STRUCTURAL: ClassVar[str] = "STRUCTURAL"
    AUXILIARY: ClassVar[str] = "AUXILIARY"

    number: int
    name: str
    kind: str
    must: tuple[str, ...] = ()
    may: tuple[str, ...] = ()
    sup: str = "top"
    desc: str = ""

    @property
    def oid(self) -> str:
        return f"{OBJECT_CLASS_ARC}.{self.number}"
