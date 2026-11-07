"""SSH plugin: OpenSSH public keys of users (``ldapPublicKey``)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass

from heracles.attributes import ListAttr, TextAttr
from heracles.i18n import _
from heracles.ldap.client import Entry, Modification
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext

DISABLED_PREFIX = "disabled-"

_KEY_RE = re.compile(
    r"^(?P<options>[-\w=\",.]+\s+)?"
    r"(?P<disabled>disabled-)?"
    r"(?P<type>ssh-(?:dss|rsa|ed25519)|ecdsa-sha2-nistp\d{3}|ecdsa-sk|ed25519-sk|"
    r"sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)"
    r"\s+(?P<blob>[A-Za-z0-9+/.=]+)"
    r"(?:\s+(?P<comment>\S.*?))?\s*$"
)

_TYPE_LABELS = {
    "ssh-dss": "DSA",
    "ssh-rsa": "RSA",
    "ssh-ed25519": "Ed25519",
    "ed25519-sk": "Ed25519-SK",
    "ecdsa-sk": "ECDSA-SK",
}


@dataclass(frozen=True, slots=True)
class PublicKey:
    """A parsed OpenSSH public key line."""

    line: str
    key_type: str
    fingerprint: str
    comment: str
    disabled: bool

    @property
    def label(self) -> str:
        return _TYPE_LABELS.get(self.key_type, self.key_type)


def md5_fingerprint(blob: bytes) -> str:
    """MD5 fingerprint of a key blob as ``aa:bb:...``."""
    digest = hashlib.md5(blob, usedforsecurity=False).hexdigest()
    return ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))


def parse_key(line: str) -> PublicKey | None:
    """Parse one ``authorized_keys`` style line, or ``None`` if invalid."""
    match = _KEY_RE.match(line.strip())
    if match is None:
        return None
    try:
        blob = base64.b64decode(match["blob"], validate=True)
    except (binascii.Error, ValueError):
        return None
    if not blob:
        return None
    return PublicKey(
        line=line.strip(),
        key_type=match["type"],
        fingerprint=md5_fingerprint(blob),
        comment=match["comment"] or "",
        disabled=match["disabled"] is not None,
    )


def disable_key(line: str) -> str:
    """Insert the ``disabled-`` marker before the key type (idempotent)."""
    match = _KEY_RE.match(line.strip())
    if match is None or match["disabled"]:
        return line
    start = match.start("type")
    return line[:start] + DISABLED_PREFIX + line[start:]


def enable_key(line: str) -> str:
    """Remove the ``disabled-`` marker (idempotent)."""
    match = _KEY_RE.match(line.strip())
    if match is None or not match["disabled"]:
        return line
    start = match.start("disabled")
    return line[:start] + line[start + len(DISABLED_PREFIX) :]


class SshPublicKeyAttr(TextAttr):
    """One OpenSSH public key line."""

    def _validate(self, value: str) -> list[str]:
        if parse_key(value) is None:
            return [_("Unknown public key format.")]
        return []


class SshTab(Tab):
    """OpenSSH public keys of a user."""

    name = "ssh"
    acl_key = "sshAccount"
    label = _("SSH keys")
    optional = True
    object_classes = ("ldapPublicKey",)
    requires = ("posix",)

    keys = Section(
        _("OpenSSH public keys"),
        ListAttr(
            "sshPublicKey",
            _("Public keys"),
            SshPublicKeyAttr("key", _("Public key")),
        ),
    )

    @classmethod
    def prepare(cls, ctx: TabContext) -> None:
        raw = ctx.values.get("sshPublicKey")
        if not isinstance(raw, list):
            return
        seen: dict[str, int] = {}
        for index, value in enumerate(raw):  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            key = parse_key(value) if isinstance(value, str) else None
            if key is None:
                continue
            if key.fingerprint in seen:
                ctx.error(
                    f"sshPublicKey.{index}",
                    _("Several keys have the fingerprint {fp}.").format(fp=key.fingerprint),
                )
            seen[key.fingerprint] = index


def lock_keys(entry: Entry, locked: bool) -> list[Modification]:
    """Account lock hook: disable (or re-enable) every public key."""
    keys = entry.texts("sshPublicKey")
    if not keys:
        return []
    changed = [disable_key(k) if locked else enable_key(k) for k in keys]
    if changed == keys:
        return []
    return [Modification("replace", "sshPublicKey", [k.encode() for k in changed])]


def plugin() -> Plugin:
    """Entry point of the SSH plugin."""
    return Plugin(
        name="ssh",
        version="0.1.0",
        tabs=(TabAttachment("user", SshTab),),
        required_object_classes=("ldapPublicKey",),
        account_lock_hooks=(lock_keys,),
    )


__all__ = [
    "PublicKey",
    "SshPublicKeyAttr",
    "SshTab",
    "disable_key",
    "enable_key",
    "lock_keys",
    "md5_fingerprint",
    "parse_key",
    "plugin",
]
