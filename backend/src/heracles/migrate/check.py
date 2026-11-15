"""Post-migration checks: is the converted directory usable as it was before?

* the directory health checks (``heracles check``) pass;
* a sample of people can still sign in (``uid,password`` lines; against the real server,
  since only it verifies password hashes);
* ACL evaluation gives the expected rights for a sample of (subject, object, key) triples
  (``subject,object,key,expected``), e.g. rights exported before the cut-over with
  :func:`export_rights` and reviewed against the old system.

The checks run on a :class:`DirectoryClient`: the configured server, or an in-memory copy
of a converted LDIF (:func:`load_ldif`) before importing it.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from heracles.acl.directory import LdapAclDirectory
from heracles.acl.evaluator import AclEvaluator
from heracles.acl.resolver import AclResolver
from heracles.acl.rights import Rights, RightsParseError
from heracles.core import setup_checks
from heracles.ldap import dn as dnlib
from heracles.ldap.client import DirectoryClient, DirectoryError, Scope
from heracles.ldap.filter import escape_filter_value
from heracles.ldap.ldif import parse_ldif
from heracles.ldap.memory import MemoryDirectory


@dataclass(slots=True)
class CheckReport:
    health: list[dict[str, object]] = field(default_factory=lambda: [])
    logins: list[dict[str, object]] = field(default_factory=lambda: [])
    rights: list[dict[str, object]] = field(default_factory=lambda: [])

    @property
    def ok(self) -> bool:
        return (
            all(h["status"] != "error" for h in self.health)
            and all(x["ok"] for x in self.logins)
            and all(x["ok"] for x in self.rights)
        )

    def to_json(self) -> dict[str, object]:
        return {"ok": self.ok, "health": self.health, "logins": self.logins, "rights": self.rights}

    def summary(self) -> str:
        lines: list[str] = []
        for h in self.health:
            lines.append(f"[{str(h['status']).upper():7}] {h['id']}: {h['message']}")
        if self.logins:
            good = sum(1 for x in self.logins if x["ok"])
            lines.append(f"logins: {good}/{len(self.logins)} succeed")
            lines.extend(f"  FAIL {x['login']}: {x['detail']}" for x in self.logins if not x["ok"])
        if self.rights:
            good = sum(1 for x in self.rights if x["ok"])
            lines.append(f"rights: {good}/{len(self.rights)} as expected")
            lines.extend(
                f"  FAIL {x['subject']} on {x['object']} ({x['key']}): "
                f"expected {x['expected']!r}, got {x['actual']!r}"
                for x in self.rights
                if not x["ok"]
            )
        lines.append("result: OK" if self.ok else "result: FAILED")
        return "\n".join(lines) + "\n"


def load_ldif(text: str) -> MemoryDirectory:
    """An in-memory directory holding a converted export (base = its shallowest entry)."""
    entries = sorted(parse_ldif(text), key=lambda e: dnlib.depth(e.dn))
    if not entries:
        raise ValueError("the LDIF holds no entry")
    directory = MemoryDirectory(entries[0].dn)
    classes = {v.decode() for e in entries for v in e.get("objectClass")}
    directory.set_schema_object_classes([*directory.schema_object_classes(), *classes])
    for entry in entries:
        directory.add(entry.dn, {k: list(v) for k, v in entry.attrs.items()})
    return directory


def health(directory: DirectoryClient) -> list[dict[str, object]]:
    return [r.to_json() for r in setup_checks.run_checks(setup_checks.context_for(directory))]


def _person(directory: DirectoryClient, login: str) -> str | None:
    if "=" in login:
        return login
    flt = f"(uid={escape_filter_value(login)})"
    try:
        found = list(directory.search(directory.base_dn, flt, Scope.SUBTREE, ["1.1"], size_limit=2))
    except DirectoryError:
        return None
    return found[0].dn if len(found) == 1 else None


def logins(directory: DirectoryClient, rows: Iterable[Sequence[str]]) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for row in rows:
        if len(row) < 2 or not row[0].strip():
            continue
        login, password = row[0].strip(), row[1]
        dn = _person(directory, login)
        if dn is None:
            out.append({"login": login, "ok": False, "detail": "no single entry with this uid"})
            continue
        ok = directory.check_password(dn, password)
        out.append({"login": login, "ok": ok, "detail": "" if ok else "password refused"})
    return out


def rights_of(directory: DirectoryClient, subject: str, target: str, key: str) -> Rights:
    entry = directory.get(subject)
    attrs = (
        {k: [v.decode("utf-8", "replace") for v in vals] for k, vals in entry.attrs.items()}
        if entry is not None
        else {}
    )
    resolved = AclResolver(LdapAclDirectory(directory)).resolve(
        subject, uid=entry.text("uid") if entry is not None else None, user_attrs=attrs
    )
    return AclEvaluator(resolved).permissions(target, key)


def _letters(text: str) -> str:
    try:
        return Rights.parse(text).canonical()
    except RightsParseError:
        return "".join(sorted(text.strip()))


def compare_rights(
    directory: DirectoryClient, rows: Iterable[Sequence[str]]
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for row in rows:
        if len(row) < 4 or row[0].strip().lower() == "subject":
            continue
        subject, target, key, expected = (c.strip() for c in row[:4])
        actual = rights_of(directory, subject, target, key).canonical()
        out.append(
            {
                "subject": subject,
                "object": target,
                "key": key,
                "expected": expected,
                "actual": actual,
                "ok": actual == _letters(expected),
            }
        )
    return out


def export_rights(directory: DirectoryClient, rows: Iterable[Sequence[str]], path: Path) -> int:
    """Write ``subject,object,key,rights`` for each ``subject,object,key`` row."""
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["subject", "object", "key", "expected"])
        for row in rows:
            if len(row) < 3 or row[0].strip().lower() == "subject":
                continue
            subject, target, key = (c.strip() for c in row[:3])
            writer.writerow(
                [subject, target, key, rights_of(directory, subject, target, key).canonical()]
            )
            count += 1
    return count


def read_csv(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.reader(handle) if row and not row[0].startswith("#")]


__all__ = [
    "CheckReport",
    "compare_rights",
    "export_rights",
    "health",
    "load_ldif",
    "logins",
    "read_csv",
    "rights_of",
]
