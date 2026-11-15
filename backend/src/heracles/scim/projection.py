"""``attributes`` / ``excludedAttributes`` (RFC 7644 section 3.4.2.5).

Owner: stream A. Contract: :func:`project` returns a new resource keeping only the listed
attributes (``attributes``) or dropping them (``excludedAttributes``); both are lists of
paths (``userName``, ``name.givenName``, ``emails``, ``urn:...:User:employeeNumber``),
matched case-insensitively. ``always`` attributes are kept whatever is asked (``id``,
``schemas``, and ``meta`` is kept unless excluded explicitly... see RFC 7643 "returned").
Giving both lists is the caller's 400; this function receives at most one non-empty list.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

ALWAYS = ("id", "schemas")


def project(
    resource: Mapping[str, Any],
    attributes: Sequence[str] = (),
    excluded: Sequence[str] = (),
    always: Sequence[str] = ALWAYS,
) -> dict[str, Any]:
    raise NotImplementedError


__all__ = ["ALWAYS", "project"]
