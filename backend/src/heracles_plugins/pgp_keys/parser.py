"""OpenPGP key parsing utilities (key IDs, fingerprints, armor decoding)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime

_ALGO_NAMES: dict[int, str] = {
    1: "RSA",
    2: "RSA Encrypt-Only",
    3: "RSA Sign-Only",
    16: "ElGamal",
    17: "DSA",
    18: "ECDH",
    19: "ECDSA",
    21: "Diffie-Hellman",
    22: "EdDSA",
}


@dataclass(frozen=True, slots=True)
class ParsedPgpKey:
    """Parsed metadata of an OpenPGP public key."""

    cert_id: str
    fingerprint: str
    user_id: str | None = None
    key_type: str | None = None
    created_at: datetime | None = None


def normalize_hex(text: str) -> str:
    """Remove whitespace and uppercase a hex string."""
    return re.sub(r"\s+", "", text).upper()


def parse_pgp_armor(text: str) -> bytes | None:
    """Extract raw OpenPGP binary packets from an ASCII armored block."""
    if "-----BEGIN PGP PUBLIC KEY BLOCK-----" not in text:
        return None
    start = text.index("-----BEGIN PGP PUBLIC KEY BLOCK-----")
    content = text[start:]
    lines = content.splitlines()
    body_lines: list[str] = []
    in_body = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped.startswith("-----END PGP PUBLIC KEY BLOCK-----"):
            break
        if not in_body:
            if not stripped:  # blank line separates headers from payload
                in_body = True
            elif ":" not in stripped:
                in_body = True
                body_lines.append(stripped)
        else:
            if stripped.startswith("="):
                break  # radix-64 checksum
            body_lines.append(stripped)
    payload = "".join(body_lines)
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None


def parse_packets(data: bytes) -> list[tuple[int, bytes]]:
    """Parse raw binary OpenPGP packets into (tag, body) pairs."""
    idx = 0
    packets: list[tuple[int, bytes]] = []
    while idx < len(data):
        header_byte = data[idx]
        if not (header_byte & 0x80):
            break
        idx += 1
        is_new = bool(header_byte & 0x40)
        if is_new:
            tag = header_byte & 0x3F
            if idx >= len(data):
                break
            first_len = data[idx]
            idx += 1
            if first_len < 192:
                length = first_len
            elif first_len < 224:
                if idx >= len(data):
                    break
                length = ((first_len - 192) << 8) + data[idx] + 192
                idx += 1
            elif first_len == 255:
                if idx + 4 > len(data):
                    break
                length = struct.unpack(">I", data[idx : idx + 4])[0]
                idx += 4
            else:
                break
        else:
            tag = (header_byte & 0x3C) >> 2
            len_type = header_byte & 0x03
            if len_type == 0:
                if idx >= len(data):
                    break
                length = data[idx]
                idx += 1
            elif len_type == 1:
                if idx + 2 > len(data):
                    break
                length = struct.unpack(">H", data[idx : idx + 2])[0]
                idx += 2
            elif len_type == 2:
                if idx + 4 > len(data):
                    break
                length = struct.unpack(">I", data[idx : idx + 4])[0]
                idx += 4
            else:
                length = len(data) - idx
        body = data[idx : idx + length]
        idx += length
        packets.append((tag, body))
    return packets


def parse_openpgp_key(text_or_bytes: str | bytes) -> ParsedPgpKey | None:
    """Extract key ID, fingerprint, user ID, key type, creation time."""
    if isinstance(text_or_bytes, str):
        cleaned = text_or_bytes.strip()
        # Direct hex fingerprint or key ID
        hex_val = normalize_hex(cleaned)
        if re.fullmatch(r"^[0-9A-F]{32,64}$", hex_val):
            return ParsedPgpKey(
                cert_id=hex_val[-16:],
                fingerprint=hex_val,
            )
        if re.fullmatch(r"^[0-9A-F]{8,16}$", hex_val):
            return ParsedPgpKey(
                cert_id=hex_val,
                fingerprint=hex_val,
            )
        raw = parse_pgp_armor(cleaned)
    else:
        raw = text_or_bytes

    if not raw:
        return None

    packets = parse_packets(raw)
    cert_id: str | None = None
    fingerprint: str | None = None
    user_id: str | None = None
    key_type: str | None = None
    created_at: datetime | None = None

    for tag, body in packets:
        # Tag 6: Public Key Packet
        if tag == 6 and fingerprint is None and len(body) >= 6:
            version = body[0]
            if version == 4:
                created_ts = struct.unpack(">I", body[1:5])[0]
                algo_id = body[5]
                header = b"\x99" + struct.pack(">H", len(body))
                fingerprint = hashlib.sha1(header + body, usedforsecurity=False).hexdigest().upper()
                cert_id = fingerprint[-16:]
                key_type = _ALGO_NAMES.get(algo_id, f"Algorithm-{algo_id}")
                created_at = datetime.fromtimestamp(created_ts, UTC)
        elif tag == 13 and user_id is None:
            user_id = body.decode("utf-8", errors="replace")

    if cert_id and fingerprint:
        return ParsedPgpKey(
            cert_id=cert_id,
            fingerprint=fingerprint,
            user_id=user_id,
            key_type=key_type,
            created_at=created_at,
        )
    return None
