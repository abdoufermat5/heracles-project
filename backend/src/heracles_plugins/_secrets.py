"""Which attribute names hold secrets (shared by the plugins that copy attribute values).

Password hashes, clear-text service passwords and Kerberos keys must never reach an audit
event, an export or a rule whose outcome is visible. Names are matched by fragment because
plugins add their own (``hrcSmbNTPassword``, ``hrcIpmiPassword``, ...).
"""

from __future__ import annotations

from collections.abc import Iterable

from heracles.attributes import JSON, StringAttr

SECRET_NAME_FRAGMENTS = ("password", "secret", "principalkey")


def is_secret_name(name: str, extra: Iterable[str] = ()) -> bool:
    """True if ``name`` (options such as ``;binary`` ignored) is listed in ``extra`` or looks
    like a secret."""
    lowered = name.partition(";")[0].strip().lower()
    return lowered in {e.lower() for e in extra} or any(
        fragment in lowered for fragment in SECRET_NAME_FRAGMENTS
    )


class CleartextSecretAttr(StringAttr):
    """A service secret stored in clear text and never sent back to clients.

    Write-only like a password attribute, but with the text stored as given (a mail
    server reads its administrative password in clear). The empty value keeps the stored
    secret: a client that does not know it cannot erase it by accident.
    """

    write_only = True

    def from_ldap(self, values: list[bytes]) -> str | None:
        return None

    def to_json(self, value: str | None) -> JSON:
        return None

    def validate(self, value: str | None) -> list[str]:
        if value is None:
            return []  # unchanged; "required" is enforced by the service on creation
        return super().validate(value)
