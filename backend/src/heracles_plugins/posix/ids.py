"""Unix id allocation ("traditional" method)."""

from __future__ import annotations

from heracles.ldap.client import DirectoryClient, NoSuchObjectError
from heracles.ldap.filter import escape_filter_value

#: Always considered taken (``nobody`` / ``nogroup``).
RESERVED_IDS = frozenset({65534})
MAX_ID = 2**32


class IdAllocationError(RuntimeError):
    """No free id in the configured range."""


def parse_range(spec: str | int) -> tuple[int, int]:
    """``"1100"`` → (1100, 2**32); ``"1100-2000"`` → (1100, 2000)."""
    text = str(spec).strip()
    low, sep, high = text.partition("-")
    base = int(low)
    return base, (int(high) if sep and high.strip() else MAX_ID)


def used_ids(directory: DirectoryClient, object_class: str, attr: str) -> set[int]:
    """Every numeric ``attr`` value on entries of ``object_class`` under the base."""
    found: set[int] = set(RESERVED_IDS)
    flt = f"(&(objectClass={escape_filter_value(object_class)})({attr}=*))"
    try:
        for entry in directory.search(directory.base_dn, flt, attrs=[attr]):
            for value in entry.texts(attr):
                if value.strip().isdigit():
                    found.add(int(value))
    except NoSuchObjectError:
        pass
    return found


def next_free_id(
    directory: DirectoryClient,
    object_class: str,
    attr: str,
    *,
    base: str | int,
    min_id: int = 0,
    reserved: set[int] | None = None,
) -> int:
    """First free id strictly greater than the range base (and ≥ ``min_id``)."""
    low, high = parse_range(base)
    taken = used_ids(directory, object_class, attr) | (reserved or set())
    candidate = max(low + 1, min_id)
    while candidate < high:
        if candidate not in taken:
            return candidate
        candidate += 1
    raise IdAllocationError(f"no free {attr} in range {low}-{high}")
