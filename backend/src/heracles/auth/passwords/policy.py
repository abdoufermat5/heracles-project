"""Password policy: strength rules and method selection."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from heracles.auth.passwords.registry import PasswordMethodRegistry, default_registry


class PasswordPolicyError(ValueError):
    """The proposed password violates the policy."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(slots=True)
class PasswordPolicy:
    """Configurable rules for new passwords."""

    min_length: int = 8
    min_differing: int = 0
    default_method: str = "ssha"
    allowed_methods: tuple[str, ...] = (
        "ssha",
        "ssha512",
        "argon2",
        "crypt/sha-512",
        "crypt/sha-256",
        "crypt/blowfish",
    )
    force_default: bool = False
    registry: PasswordMethodRegistry = field(default_factory=default_registry)

    def problems(self, new: str, previous: str | None = None) -> list[str]:
        out: list[str] = []
        if len(new) < self.min_length:
            out.append(f"Password must be at least {self.min_length} characters long")
        if previous is not None and self.min_differing > 0:
            differing = sum((Counter(new) - Counter(previous)).values())
            if differing < self.min_differing:
                out.append(
                    "Password must differ from the previous one by at least "
                    f"{self.min_differing} characters"
                )
        return out

    def validate(self, new: str, previous: str | None = None) -> None:
        problems = self.problems(new, previous)
        if problems:
            raise PasswordPolicyError(problems)

    def method_for(self, current_stored: str | None = None) -> str:
        """Method id to use for a new password given the currently stored value."""
        if not self.force_default and current_stored:
            current = self.registry.detect(current_stored)
            if current is not None and current.can_hash and current.id in self.allowed_methods:
                return current.id
        return self.default_method

    def hash_new(
        self, new: str, *, previous: str | None = None, current_stored: str | None = None
    ) -> str:
        """Validate ``new`` and return the value to store."""
        self.validate(new, previous)
        return self.registry.hash(new, self.method_for(current_stored))
