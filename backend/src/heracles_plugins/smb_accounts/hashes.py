"""Windows password hashes: NT (MD4 of UTF-16LE) and LM (DES based).

``hashlib`` often lacks MD4 (and never offers DES), so both are implemented here
in pure Python from RFC 1320 and FIPS 46-3. They are only used to derive the
legacy hashes stored next to the directory password.
"""

from __future__ import annotations

import struct

_MASK = 0xFFFFFFFF


def _rol(value: int, bits: int) -> int:
    value &= _MASK
    return ((value << bits) | (value >> (32 - bits))) & _MASK


def md4(data: bytes) -> bytes:
    """MD4 digest (RFC 1320)."""
    length = len(data)
    padded = data + b"\x80" + b"\x00" * ((55 - length) % 64) + struct.pack("<Q", length * 8)
    a, b, c, d = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476
    for offset in range(0, len(padded), 64):
        x = struct.unpack("<16I", padded[offset : offset + 64])
        aa, bb, cc, dd = a, b, c, d
        for i in range(16):  # round 1
            k, s = i, (3, 7, 11, 19)[i % 4]
            f = (b & c) | (~b & d)
            a, b, c, d = d, _rol(a + f + x[k], s), b, c
        for i in range(16):  # round 2
            k, s = (i % 4) * 4 + i // 4, (3, 5, 9, 13)[i % 4]
            g = (b & c) | (b & d) | (c & d)
            a, b, c, d = d, _rol(a + g + x[k] + 0x5A827999, s), b, c
        for i in range(16):  # round 3
            k = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)[i]
            s = (3, 9, 11, 15)[i % 4]
            h = b ^ c ^ d
            a, b, c, d = d, _rol(a + h + x[k] + 0x6ED9EBA1, s), b, c
        a, b, c, d = (a + aa) & _MASK, (b + bb) & _MASK, (c + cc) & _MASK, (d + dd) & _MASK
    return struct.pack("<4I", a, b, c, d)


def nt_hash(password: str) -> str:
    """Upper-case hex NT hash (``hrcSmbNTPassword``)."""
    return md4(password.encode("utf-16-le")).hex().upper()


# ---------------------------------------------------------------------- DES

_IP = (
    58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4,
    62, 54, 46, 38, 30, 22, 14, 6, 64, 56, 48, 40, 32, 24, 16, 8,
    57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3,
    61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7,
)  # fmt: skip
_FP = (
    40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31,
    38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29,
    36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27,
    34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25,
)  # fmt: skip
_E = (
    32, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9, 8, 9, 10, 11,
    12, 13, 12, 13, 14, 15, 16, 17, 16, 17, 18, 19, 20, 21, 20, 21,
    22, 23, 24, 25, 24, 25, 26, 27, 28, 29, 28, 29, 30, 31, 32, 1,
)  # fmt: skip
_P = (
    16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10,
    2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25,
)  # fmt: skip
_PC1 = (
    57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18,
    10, 2, 59, 51, 43, 35, 27, 19, 11, 3, 60, 52, 44, 36,
    63, 55, 47, 39, 31, 23, 15, 7, 62, 54, 46, 38, 30, 22,
    14, 6, 61, 53, 45, 37, 29, 21, 13, 5, 28, 20, 12, 4,
)  # fmt: skip
_PC2 = (
    14, 17, 11, 24, 1, 5, 3, 28, 15, 6, 21, 10,
    23, 19, 12, 4, 26, 8, 16, 7, 27, 20, 13, 2,
    41, 52, 31, 37, 47, 55, 30, 40, 51, 45, 33, 48,
    44, 49, 39, 56, 34, 53, 46, 42, 50, 36, 29, 32,
)  # fmt: skip
_SHIFTS = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)
_SBOXES = (
    (
        14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7,
        0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8,
        4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0,
        15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13,
    ),
    (
        15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10,
        3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5,
        0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15,
        13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9,
    ),
    (
        10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8,
        13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1,
        13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7,
        1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12,
    ),
    (
        7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15,
        13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9,
        10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4,
        3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14,
    ),
    (
        2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9,
        14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6,
        4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14,
        11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3,
    ),
    (
        12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11,
        10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8,
        9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6,
        4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13,
    ),
    (
        4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1,
        13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6,
        1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2,
        6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12,
    ),
    (
        13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7,
        1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2,
        7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8,
        2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11,
    ),
)  # fmt: skip


def _permute(value: int, table: tuple[int, ...], width: int) -> int:
    out = 0
    for pos in table:
        out = (out << 1) | ((value >> (width - pos)) & 1)
    return out


def _subkeys(key: bytes) -> list[int]:
    k = _permute(int.from_bytes(key, "big"), _PC1, 64)
    c, d = k >> 28, k & 0xFFFFFFF
    keys: list[int] = []
    for shift in _SHIFTS:
        c = ((c << shift) | (c >> (28 - shift))) & 0xFFFFFFF
        d = ((d << shift) | (d >> (28 - shift))) & 0xFFFFFFF
        keys.append(_permute((c << 28) | d, _PC2, 56))
    return keys


def des_encrypt_block(key: bytes, block: bytes) -> bytes:
    """Encrypt one 8-byte block with single DES (8-byte key, parity bits ignored)."""
    if len(key) != 8 or len(block) != 8:
        raise ValueError("DES works on 8-byte keys and blocks")
    data = _permute(int.from_bytes(block, "big"), _IP, 64)
    left, right = data >> 32, data & _MASK
    for subkey in _subkeys(key):
        mixed = _permute(right, _E, 32) ^ subkey
        out = 0
        for i in range(8):
            chunk = (mixed >> (42 - 6 * i)) & 0x3F
            row = ((chunk & 0x20) >> 4) | (chunk & 1)
            out = (out << 4) | _SBOXES[i][row * 16 + ((chunk >> 1) & 0xF)]
        left, right = right, left ^ _permute(out, _P, 32)
    return _permute((right << 32) | left, _FP, 64).to_bytes(8, "big")


def _des_key_from_7(raw: bytes) -> bytes:
    """Spread 7 key bytes over 8 (the parity bit position is left at zero)."""
    bits = int.from_bytes(raw, "big")
    return bytes(((bits >> (49 - 7 * i)) & 0x7F) << 1 for i in range(8))


LM_MAGIC = b"KGS!@#$%"
LM_MAX_LENGTH = 14


def lm_hash(password: str) -> str | None:
    """Upper-case hex LM hash, or ``None`` when the password cannot have one.

    The LM scheme upper-cases the password, uses the OEM (here Latin-1) bytes and
    only supports 14 characters.
    """
    try:
        raw = password.upper().encode("latin-1")
    except UnicodeEncodeError:
        return None
    if len(raw) > LM_MAX_LENGTH:
        return None
    padded = raw.ljust(LM_MAX_LENGTH, b"\x00")
    return (
        (
            des_encrypt_block(_des_key_from_7(padded[:7]), LM_MAGIC)
            + des_encrypt_block(_des_key_from_7(padded[7:]), LM_MAGIC)
        )
        .hex()
        .upper()
    )


__all__ = ["des_encrypt_block", "lm_hash", "md4", "nt_hash"]
