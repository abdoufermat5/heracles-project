"""Method registry: detect the scheme of a stored value, verify, hash."""

from __future__ import annotations

from collections.abc import Iterable

from heracles.auth.passwords.base import PasswordMethod
from heracles.auth.passwords.lock import is_locked, unlock
from heracles.auth.passwords.methods import (
    Argon2Method,
    ClearMethod,
    CryptBlowfishMethod,
    CryptDesMethod,
    CryptMd5Method,
    CryptSha256Method,
    CryptSha512Method,
    EmptyMethod,
    Md5Method,
    SaslMethod,
    ShaMethod,
    SmdMethod,
    Ssha512Method,
    SshaMethod,
)


class UnknownMethodError(KeyError):
    """No method with this id."""


class PasswordMethodRegistry:
    """Ordered collection of methods; the first whose ``matches`` is true wins."""

    def __init__(self, methods: Iterable[PasswordMethod]) -> None:
        self._methods: dict[str, PasswordMethod] = {m.id: m for m in methods}

    @property
    def ids(self) -> list[str]:
        return list(self._methods)

    def hashable_ids(self) -> list[str]:
        return [i for i, m in self._methods.items() if m.can_hash]

    def get(self, method_id: str) -> PasswordMethod:
        try:
            return self._methods[method_id]
        except KeyError:
            raise UnknownMethodError(method_id) from None

    def detect(self, stored: str) -> PasswordMethod | None:
        """Method of a stored value (lock marker ignored), ``None`` if unknown."""
        value = unlock(stored) if is_locked(stored) else stored
        for method in self._methods.values():
            if method.matches(value):
                return method
        return None

    def verify(self, password: str, stored: str) -> bool:
        """Verify against any known scheme; locked values never verify."""
        if is_locked(stored):
            return False
        method = self.detect(stored)
        return method.verify(password, stored) if method is not None else False

    def hash(self, password: str, method_id: str) -> str:
        return self.get(method_id).hash(password)


def default_registry() -> PasswordMethodRegistry:
    # Specific schemes first; ``clear`` last because it also matches any value
    # that carries no scheme tag.
    return PasswordMethodRegistry(
        [
            EmptyMethod(),
            CryptMd5Method(),
            CryptSha256Method(),
            CryptSha512Method(),
            CryptBlowfishMethod(),
            CryptDesMethod(),
            Md5Method(),
            SmdMethod(),
            ShaMethod(),
            SshaMethod(),
            Ssha512Method(),
            Argon2Method(),
            SaslMethod(),
            ClearMethod(),
        ]
    )
