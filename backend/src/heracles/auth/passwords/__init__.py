"""Password hashing methods, registry, lock helpers and policy."""

from heracles.auth.passwords.base import PasswordError, PasswordMethod, UnsupportedOperationError
from heracles.auth.passwords.lock import EMPTY_LOCK, is_locked, lock, unlock
from heracles.auth.passwords.policy import PasswordPolicy, PasswordPolicyError
from heracles.auth.passwords.registry import (
    PasswordMethodRegistry,
    UnknownMethodError,
    default_registry,
)

__all__ = [
    "EMPTY_LOCK",
    "PasswordError",
    "PasswordMethod",
    "PasswordMethodRegistry",
    "PasswordPolicy",
    "PasswordPolicyError",
    "UnknownMethodError",
    "UnsupportedOperationError",
    "default_registry",
    "is_locked",
    "lock",
    "unlock",
]
