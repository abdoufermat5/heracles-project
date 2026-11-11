"""SSH plugin: OpenSSH public keys of users (``ldapPublicKey``)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from typing import Any, cast

from heracles.attributes import DisplayAttr, ListAttr, StringAttr
from heracles.i18n import _
from heracles.ldap.client import Entry, Modification
from heracles.objects import Plugin, Section, Tab, TabAttachment
from heracles.objects.hooks import TabContext

DISABLED_PREFIX = "disabled-"

# Options may contain quoted strings (with spaces, escaped quotes) and commas.
_OPTIONS = r'(?:[^\s"]|"(?:[^"\\]|\\.)*")+'
_KEY_RE = re.compile(
    rf"(?P<options>{_OPTIONS}\s+)?"
    r"(?P<disabled>disabled-)?"
    r"(?P<type>ssh-(?:dss|rsa|ed25519)|ecdsa-sha2-nistp\d{3}|ecdsa-sk|ed25519-sk|"
    r"sk-ssh-ed25519@openssh\.com|sk-ecdsa-sha2-nistp256@openssh\.com)"
    r"\s+(?P<blob>[A-Za-z0-9+/]+=*)"
    r"(?:\s+(?P<comment>\S.*?))?"
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
    match = _KEY_RE.fullmatch(line.strip())
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
    text = line.strip()
    match = _KEY_RE.fullmatch(text)
    if match is None or match["disabled"]:
        return line
    start = match.start("type")
    return text[:start] + DISABLED_PREFIX + text[start:]


def enable_key(line: str) -> str:
    """Remove the ``disabled-`` marker (idempotent)."""
    text = line.strip()
    match = _KEY_RE.fullmatch(text)
    if match is None or not match["disabled"]:
        return line
    start = match.start("disabled")
    return text[:start] + text[start + len(DISABLED_PREFIX) :]


class SshPublicKeyAttr(StringAttr):
    """One OpenSSH public key line."""

    def _validate(self, value: str) -> list[str]:
        if parse_key(value) is None:
            return [_("Unknown public key format.")]
        return []


class SshPublicKeyListAttr(ListAttr[str]):
    """List of public keys; errors name the offending (1-based) position.

    Like every ``ListAttr`` the error is reported on the field itself
    (``ssh.sshPublicKey``), not on an item key.
    """

    def _validate(self, value: list[str]) -> list[str]:
        errors: list[str] = []
        if self.min_length is not None and len(value) < self.min_length:
            errors.append(_("At least {n} values are required.").format(n=self.min_length))
        if self.max_length is not None and len(value) > self.max_length:
            errors.append(_("At most {n} values are allowed.").format(n=self.max_length))
        seen: dict[str, int] = {}
        for index, line in enumerate(value, start=1):
            key = parse_key(line)
            if key is None:
                errors.append(_("Key {n}: unknown public key format.").format(n=index))
                continue
            if key.fingerprint in seen:
                errors.append(
                    _("Key {n}: same fingerprint as key {m} ({fp}).").format(
                        n=index, m=seen[key.fingerprint], fp=key.fingerprint
                    )
                )
                continue
            seen[key.fingerprint] = index
        return errors


def summarize(values: dict[str, Any]) -> str | None:
    """Read-only summary: type, fingerprint and comment of every key."""
    raw = values.get("sshPublicKey")
    if not isinstance(raw, list):
        return None
    lines: list[str] = []
    for line in cast("list[object]", raw):
        key = parse_key(line) if isinstance(line, str) else None
        if key is None:
            continue
        parts = [key.label, key.fingerprint]
        if key.comment:
            parts.append(key.comment)
        if key.disabled:
            parts.append(_("(disabled)"))
        lines.append(" ".join(parts))
    return "\n".join(lines) or None


class SshTab(Tab):
    """OpenSSH public keys of a user."""

    name = "ssh"
    acl_key = "sshAccount"
    label = _("SSH keys")
    description = _("Public keys for SSH login")
    optional = True
    object_classes = ("ldapPublicKey",)
    requires = ("posix",)

    keys = Section(
        _("OpenSSH public keys"),
        SshPublicKeyListAttr(
            "sshPublicKey",
            _("Public keys"),
            SshPublicKeyAttr("key", _("Public key")),
        ),
        DisplayAttr("keySummary", _("Keys"), compute=summarize),
    )

    @classmethod
    def on_load(cls, ctx: TabContext) -> None:
        ctx.values["keySummary"] = summarize(ctx.values)


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
    "SshPublicKeyListAttr",
    "SshTab",
    "disable_key",
    "enable_key",
    "lock_keys",
    "md5_fingerprint",
    "parse_key",
    "plugin",
    "summarize",
]
