"""The S-04 rule for search filters, shared by API v1 and v2.

Kept out of the ``heracles.api.v1`` package: importing that package loads its routers,
which import API v2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from heracles.attributes import AnyAttribute
    from heracles.objects import TypeInfo
    from heracles.objects.model import Tab


def _find_attribute(tab: type[Tab], name: str) -> AnyAttribute | None:
    exact = tab.attribute(name)
    if exact is not None:
        return exact
    wanted = name.lower()
    return next((a for a in tab.attributes() if a.name.lower() == wanted), None)


#: Attributes any reader of an entry may test in a search filter.
OPEN_FILTER_ATTRS = frozenset({"objectclass"})


def filter_checks(info: TypeInfo, names: set[str]) -> list[tuple[str, str]]:
    """``(tab, attribute)`` pairs a search filter tests, to be readable by the caller.

    A filter is an oracle on the attributes it names: without this check a user could
    probe the value of an attribute the ACLs hide (a password hash, say) one character
    at a time. Unknown and write-only attributes raise ``ValueError(<name>)``.
    """
    checks: list[tuple[str, str]] = []
    for name in sorted(names - OPEN_FILTER_ATTRS):
        found = next(
            ((t, a) for t in info.tabs if (a := _find_attribute(t, name)) is not None), None
        )
        if found is None or found[1].write_only:
            raise ValueError(name)
        checks.append((found[0].name, found[1].name))
    return checks
