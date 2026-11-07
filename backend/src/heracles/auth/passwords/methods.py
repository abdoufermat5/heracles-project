"""Concrete password methods."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Final

import bcrypt
from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exc

from heracles.auth.passwords import _passlib
from heracles.auth.passwords.base import (
    UnsupportedOperationError,
    b64decode,
    b64encode,
    scheme_of,
    strip_scheme,
)

_BCRYPT_PREFIXES: Final = ("$2a$", "$2b$", "$2x$", "$2y$")
_BCRYPT_MAX = 72
_DES_RE = re.compile(r"^[./0-9A-Za-z]{13}$")


def _eq(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)


class ClearMethod:
    """Plain text, stored without any prefix (``{CLEAR}`` is accepted on read)."""

    id = "clear"
    can_hash = True

    def hash(self, password: str) -> str:
        return password

    def verify(self, password: str, stored: str) -> bool:
        if scheme_of(stored) == "CLEAR":
            stored = strip_scheme(stored)
        return _eq(password.encode(), stored.encode())

    def matches(self, stored: str) -> bool:
        scheme = scheme_of(stored)
        return stored != "" and (scheme is None or scheme == "CLEAR")


class _DigestMethod:
    """Unsalted ``{SCHEME}base64(digest(pwd))``."""

    id: str
    can_hash = True
    _scheme: str

    def _digest(self, data: bytes) -> bytes:
        raise NotImplementedError

    def hash(self, password: str) -> str:
        return f"{{{self._scheme}}}{b64encode(self._digest(password.encode()))}"

    def verify(self, password: str, stored: str) -> bool:
        if scheme_of(stored) != self._scheme:
            return False
        raw = b64decode(strip_scheme(stored))
        if raw is None:
            return False
        return _eq(self._digest(password.encode()), raw)

    def matches(self, stored: str) -> bool:
        return scheme_of(stored) == self._scheme


class Md5Method(_DigestMethod):
    id = "md5"
    _scheme = "MD5"

    def _digest(self, data: bytes) -> bytes:
        return hashlib.md5(data, usedforsecurity=False).digest()


class ShaMethod(_DigestMethod):
    id = "sha"
    _scheme = "SHA"

    def _digest(self, data: bytes) -> bytes:
        return hashlib.sha1(data, usedforsecurity=False).digest()


class _SaltedDigestMethod:
    """``{SCHEME}base64(digest(pwd + salt) + salt)`` with a 4-16 byte salt."""

    id: str
    can_hash = True
    _scheme: str
    _digest_size: int
    salt_length = 8

    def _digest(self, data: bytes) -> bytes:
        raise NotImplementedError

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(self.salt_length)
        digest = self._digest(password.encode() + salt)
        return f"{{{self._scheme}}}{b64encode(digest + salt)}"

    def verify(self, password: str, stored: str) -> bool:
        if scheme_of(stored) != self._scheme:
            return False
        raw = b64decode(strip_scheme(stored))
        if raw is None:
            return False
        digest, salt = raw[: self._digest_size], raw[self._digest_size :]
        if len(digest) != self._digest_size or not 4 <= len(salt) <= 16:
            return False
        return _eq(self._digest(password.encode() + salt), digest)

    def matches(self, stored: str) -> bool:
        return scheme_of(stored) == self._scheme


class SmdMethod(_SaltedDigestMethod):
    id = "smd5"
    _scheme = "SMD5"
    _digest_size = 16

    def _digest(self, data: bytes) -> bytes:
        return hashlib.md5(data, usedforsecurity=False).digest()


class SshaMethod(_SaltedDigestMethod):
    id = "ssha"
    _scheme = "SSHA"
    _digest_size = 20

    def _digest(self, data: bytes) -> bytes:
        return hashlib.sha1(data, usedforsecurity=False).digest()


class Ssha512Method(_SaltedDigestMethod):
    id = "ssha512"
    _scheme = "SSHA512"
    _digest_size = 64

    def _digest(self, data: bytes) -> bytes:
        return hashlib.sha512(data).digest()


class _CryptMethod:
    """Base for ``{CRYPT}`` values."""

    id: str
    can_hash = True

    def _body_matches(self, body: str) -> bool:
        raise NotImplementedError

    def _hash_body(self, password: str) -> str:
        raise NotImplementedError

    def _verify_body(self, password: str, body: str) -> bool:
        raise NotImplementedError

    def hash(self, password: str) -> str:
        return "{CRYPT}" + self._hash_body(password)

    def verify(self, password: str, stored: str) -> bool:
        if not self.matches(stored):
            return False
        try:
            return self._verify_body(password, strip_scheme(stored))
        except (ValueError, TypeError):
            return False

    def matches(self, stored: str) -> bool:
        return scheme_of(stored) == "CRYPT" and self._body_matches(strip_scheme(stored))


class CryptDesMethod(_CryptMethod):
    """Traditional DES crypt: verification only (legacy)."""

    id = "crypt/standard-des"
    can_hash = False

    def _body_matches(self, body: str) -> bool:
        return _DES_RE.match(body) is not None

    def _hash_body(self, password: str) -> str:
        raise UnsupportedOperationError("standard DES crypt is verify-only")

    def _verify_body(self, password: str, body: str) -> bool:
        return _passlib.des_verify(password, body)


class CryptMd5Method(_CryptMethod):
    id = "crypt/md5"

    def _body_matches(self, body: str) -> bool:
        return body.startswith("$1$")

    def _hash_body(self, password: str) -> str:
        return _passlib.md5_hash(password)

    def _verify_body(self, password: str, body: str) -> bool:
        return _passlib.md5_verify(password, body)


class CryptSha256Method(_CryptMethod):
    id = "crypt/sha-256"

    def _body_matches(self, body: str) -> bool:
        return body.startswith("$5$")

    def _hash_body(self, password: str) -> str:
        return _passlib.sha256_hash(password)

    def _verify_body(self, password: str, body: str) -> bool:
        return _passlib.sha256_verify(password, body)


class CryptSha512Method(_CryptMethod):
    id = "crypt/sha-512"

    def _body_matches(self, body: str) -> bool:
        return body.startswith("$6$")

    def _hash_body(self, password: str) -> str:
        return _passlib.sha512_hash(password)

    def _verify_body(self, password: str, body: str) -> bool:
        return _passlib.sha512_verify(password, body)


class CryptBlowfishMethod(_CryptMethod):
    """bcrypt (``$2y$`` / ``$2b$``); inputs are truncated to 72 bytes."""

    id = "crypt/blowfish"
    rounds = 12

    def _body_matches(self, body: str) -> bool:
        return body.startswith(_BCRYPT_PREFIXES)

    def _hash_body(self, password: str) -> str:
        pw = password.encode()[:_BCRYPT_MAX]
        return bcrypt.hashpw(pw, bcrypt.gensalt(self.rounds, prefix=b"2b")).decode("ascii")

    def _verify_body(self, password: str, body: str) -> bool:
        # The bcrypt package understands $2a$/$2b$/$2y$; normalise $2x$ is not supported.
        if body.startswith("$2x$"):
            return False
        return bcrypt.checkpw(password.encode()[:_BCRYPT_MAX], body.encode("ascii"))


class Argon2Method:
    id = "argon2"
    can_hash = True

    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash(self, password: str) -> str:
        return "{ARGON2}" + self._hasher.hash(password)

    def verify(self, password: str, stored: str) -> bool:
        if not self.matches(stored):
            return False
        try:
            return self._hasher.verify(strip_scheme(stored), password)
        except (
            argon2_exc.VerifyMismatchError,
            argon2_exc.VerificationError,
            argon2_exc.InvalidHashError,
        ):
            return False

    def matches(self, stored: str) -> bool:
        return scheme_of(stored) == "ARGON2"

    def needs_rehash(self, stored: str) -> bool:
        return self._hasher.check_needs_rehash(strip_scheme(stored))


class SaslMethod:
    """``{SASL}user@realm`` — pass-through authentication, verified by LDAP bind only."""

    id = "sasl"
    can_hash = False

    def hash(self, password: str) -> str:
        raise UnsupportedOperationError("SASL passwords are managed by the realm")

    def verify(self, password: str, stored: str) -> bool:
        return False

    def matches(self, stored: str) -> bool:
        return scheme_of(stored) == "SASL"


class EmptyMethod:
    """No ``userPassword`` at all."""

    id = "empty"
    can_hash = False

    def hash(self, password: str) -> str:
        raise UnsupportedOperationError("the empty method stores no password")

    def verify(self, password: str, stored: str) -> bool:
        return False

    def matches(self, stored: str) -> bool:
        return stored == ""
