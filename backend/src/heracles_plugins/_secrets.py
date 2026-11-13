"""Which attribute names hold secrets (shared by the plugins that copy attribute values).

Password hashes, clear-text service passwords and Kerberos keys must never reach an audit
event, an export or a rule whose outcome is visible. Names are matched by fragment because
plugins add their own (``sambaNTPassword``, ``hrcIpmiPassword``, ...).
"""

from __future__ import annotations

from collections.abc import Iterable

SECRET_NAME_FRAGMENTS = ("password", "secret", "principalkey")


def is_secret_name(name: str, extra: Iterable[str] = ()) -> bool:
    """True if ``name`` (options such as ``;binary`` ignored) is listed in ``extra`` or looks
    like a secret."""
    lowered = name.partition(";")[0].strip().lower()
    return lowered in {e.lower() for e in extra} or any(
        fragment in lowered for fragment in SECRET_NAME_FRAGMENTS
    )
