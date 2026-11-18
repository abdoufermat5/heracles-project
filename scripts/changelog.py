#!/usr/bin/env python3
"""Generate the changelog from Conventional Commits (no third-party tool).

    scripts/changelog.py                      # whole CHANGELOG.md on standard output
    scripts/changelog.py --release v0.2.0     # notes of one tag (from the previous tag)
    scripts/changelog.py --unreleased         # commits since the last tag
    scripts/changelog.py -o CHANGELOG.md      # write the file

Sections per version: breaking changes first (``type!:`` or a ``BREAKING CHANGE:`` footer),
then features, fixes, performance, security, documentation and the rest. Merge commits and
commits without a conventional type are left out.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

HEADER = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<bang>!)?: (?P<subject>.+)$")
TAG = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
SECTIONS: tuple[tuple[str, str], ...] = (
    ("feat", "Features"),
    ("fix", "Fixes"),
    ("perf", "Performance"),
    ("security", "Security"),
    ("docs", "Documentation"),
    ("refactor", "Refactoring"),
    ("test", "Tests"),
    ("build", "Build"),
    ("ci", "Continuous integration"),
)
SKIPPED = {"merge", "chore", "style", "revert-revert"}
#: The changelog starts after this commit (``.changelog-base``): the initial development before
#: it is summarised by :data:`BASELINE_NOTE` in the first section instead of commit by commit.
BASE_FILE = Path(__file__).resolve().parents[1] / ".changelog-base"
BASELINE_NOTE = (
    "First public release. It brings the web console and the self-service portal for LDAP "
    "directories (users, groups, roles, departments, delegated administration with roles and "
    "ACLs), the Heracles LDAP schema, the plugins listed in manual/plugins.md, API v2 and API "
    "v1 compatibility, SCIM 2.0 provisioning, scoped API tokens, the tamper-evident audit log, "
    "access requests, time-bound grants and access reviews, backup and restore, and the "
    "Kubernetes chart. Changes are listed commit by commit from the next release on."
)
SEP = "\x1e"
FIELD = "\x1f"


@dataclass(frozen=True, slots=True)
class Commit:
    sha: str
    type: str
    scope: str
    subject: str
    breaking: str  # the breaking-change note ("" when not breaking)


@dataclass(slots=True)
class Release:
    name: str  # tag, or "Unreleased"
    date: str
    commits: list[Commit] = field(default_factory=lambda: [])


def git(*args: str) -> str:
    # fixed program, arguments built here: no untrusted input
    run = subprocess.run(["git", *args], check=True, capture_output=True, text=True)  # noqa: S603, S607
    return run.stdout


def parse(sha: str, message: str) -> Commit | None:
    subject, _, body = message.partition("\n")
    match = HEADER.match(subject.strip())
    if match is None or match["type"] in SKIPPED:
        return None
    breaking = ""
    footer = re.search(r"^BREAKING[ -]CHANGE: (.+?)(?:\n\n|\Z)", body, re.M | re.S)
    if footer:
        breaking = " ".join(footer.group(1).split())
    elif match["bang"]:
        breaking = match["subject"]
    return Commit(sha[:8], match["type"], match["scope"] or "", match["subject"], breaking)


def commits(rev_range: str) -> list[Commit]:
    raw = git("log", "--no-merges", f"--format=%H{FIELD}%B{SEP}", rev_range)
    out: list[Commit] = []
    for chunk in raw.split(SEP):
        if not chunk.strip():
            continue
        sha, _, message = chunk.strip().partition(FIELD)
        commit = parse(sha, message)
        if commit is not None:
            out.append(commit)
    return out


def tags() -> list[tuple[str, str]]:
    """Release tags, oldest first, with their dates."""
    raw = git("tag", "--sort=creatordate", "--format=%(refname:short) %(creatordate:short)")
    pairs = [line.split(" ", 1) for line in raw.splitlines() if line.strip()]
    return [(name, date) for name, date in pairs if TAG.match(name)]


def base() -> str:
    """The baseline commit, or ``""`` (whole history)."""
    try:
        return BASE_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def releases(*, unreleased: bool = True) -> list[Release]:
    out: list[Release] = []
    start = base()
    seen: list[str] = []
    for name, date in tags():
        if start and _is_ancestor(name, start):
            continue  # a tag at or before the baseline
        previous = previous_tag(name, seen) or start
        span = f"{previous}..{name}" if previous else name
        out.append(Release(name, date, commits(span)))
        seen.append(name)
    if unreleased:
        previous = seen[-1] if seen else start
        span = f"{previous}..HEAD" if previous else "HEAD"
        pending = commits(span)
        if pending:
            out.append(Release("Unreleased", "", pending))
    return list(reversed(out))


def previous_tag(name: str, earlier: Sequence[str]) -> str:
    """The tag a release is compared with, or ``""`` when it is the first.

    A final release (``v1.2.0``) is compared with the previous final release, so that it lists
    everything since then, pre-releases included; a pre-release is compared with the tag just
    before it.
    """
    if "-" in name:
        return earlier[-1] if earlier else ""
    finals = [t for t in earlier if "-" not in t]
    return finals[-1] if finals else ""


def _is_ancestor(rev: str, of: str) -> bool:
    run = subprocess.run(["git", "merge-base", "--is-ancestor", rev, of], check=False)  # noqa: S603, S607
    return run.returncode == 0


def _line(c: Commit) -> str:
    scope = f"**{c.scope}:** " if c.scope else ""
    return f"- {scope}{c.subject} ({c.sha})"


def render(release: Release, *, heading: bool = True, first: bool = False) -> str:
    lines: list[str] = []
    if heading:
        title = release.name if not release.date else f"{release.name} — {release.date}"
        lines += [f"## {title}", ""]
    if first and base():
        lines += [BASELINE_NOTE, ""]
    breaking = [c for c in release.commits if c.breaking]
    if breaking:
        lines += ["### Breaking changes", ""]
        for c in breaking:
            scope = f"**{c.scope}:** " if c.scope else ""
            lines.append(f"- {scope}{c.breaking} ({c.sha})")
        lines.append("")
    known = {t for t, _ in SECTIONS}
    for kind, title in SECTIONS:
        items = [c for c in release.commits if c.type == kind]
        if items:
            lines += [f"### {title}", "", *(_line(c) for c in items), ""]
    others = [c for c in release.commits if c.type not in known]
    if others:
        lines += ["### Other changes", "", *(_line(c) for c in others), ""]
    if len(lines) <= 2:
        lines += ["No user-visible changes.", ""]
    return "\n".join(lines)


def document(items: Iterable[Release]) -> str:
    head = (
        "# Changelog\n\n"
        "Generated from the commit history by `scripts/changelog.py` "
        "([Conventional Commits](https://www.conventionalcommits.org/)); versions follow the "
        "[versioning policy](manual/versioning.md).\n\n"
    )
    ordered = list(items)
    return head + "\n".join(render(r, first=(i == len(ordered) - 1)) for i, r in enumerate(ordered))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--release", help="notes of one tag, e.g. v0.2.0")
    group.add_argument("--unreleased", action="store_true", help="commits since the last tag")
    parser.add_argument("-o", "--output", help="file to write (default: standard output)")
    args = parser.parse_args(argv)
    if args.release:
        found = [r for r in releases(unreleased=False) if r.name == args.release]
        if not found:
            print(f"changelog: no tag {args.release}", file=sys.stderr)
            return 2
        oldest = releases(unreleased=False)[-1].name
        text = render(found[0], heading=False, first=found[0].name == oldest)
    elif args.unreleased:
        pending = [r for r in releases() if r.name == "Unreleased"]
        first = not tags()
        text = (
            render(pending[0], heading=False, first=first)
            if pending
            else "No unreleased changes.\n"
        )
    else:
        text = document(releases())
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
