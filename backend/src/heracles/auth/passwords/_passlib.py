"""Typed facade over the (dynamically populated) crypt-family handlers of passlib."""

from __future__ import annotations

import importlib
from typing import Any, cast

_hash_module: Any = importlib.import_module("passlib.hash")


def _handler(name: str) -> Any:
    return getattr(_hash_module, name)


def des_verify(password: str, hashed: str) -> bool:
    return bool(_handler("des_crypt").verify(password, hashed))


def md5_hash(password: str) -> str:
    return cast(str, _handler("md5_crypt").hash(password))


def md5_verify(password: str, hashed: str) -> bool:
    return bool(_handler("md5_crypt").verify(password, hashed))


def sha256_hash(password: str) -> str:
    return cast(str, _handler("sha256_crypt").hash(password))


def sha256_verify(password: str, hashed: str) -> bool:
    return bool(_handler("sha256_crypt").verify(password, hashed))


def sha512_hash(password: str) -> str:
    return cast(str, _handler("sha512_crypt").hash(password))


def sha512_verify(password: str, hashed: str) -> bool:
    return bool(_handler("sha512_crypt").verify(password, hashed))
