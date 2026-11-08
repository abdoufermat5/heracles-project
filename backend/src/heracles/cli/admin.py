"""``heracles check``, ``heracles fix`` and ``heracles create-admin``."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Callable, Mapping
from typing import Any

from heracles.auth.passwords import PasswordPolicy
from heracles.core import setup_checks
from heracles.ldap.client import DirectoryClient, DirectoryError

type DirectoryFactory = Callable[[argparse.Namespace], Mapping[str, DirectoryClient]]


def load_directories(args: argparse.Namespace) -> Mapping[str, DirectoryClient]:
    """Directories declared in the configuration file (python-ldap needed)."""
    from heracles.ldap.config import load_settings
    from heracles.ldap.pyldap import PyLdapDirectory

    settings = load_settings(args.config)
    return {cfg.id: PyLdapDirectory(cfg) for cfg in settings.directories}


def _directory(args: argparse.Namespace, factory: DirectoryFactory) -> DirectoryClient | None:
    directories = factory(args)
    if not directories:
        print("error: no directory is configured", file=sys.stderr)
        return None
    wanted = getattr(args, "directory", None)
    if wanted is None:
        return next(iter(directories.values()))
    if wanted not in directories:
        print(f"error: unknown directory {wanted!r}", file=sys.stderr)
        return None
    return directories[wanted]


_ICON = {"ok": "OK  ", "warning": "WARN", "error": "FAIL"}


def run_check(args: argparse.Namespace, factory: DirectoryFactory) -> int:
    directory = _directory(args, factory)
    if directory is None:
        return 2
    results = setup_checks.run_checks(setup_checks.context_for(directory))
    if args.json:
        print(json.dumps([r.to_json() for r in results], indent=2))
    else:
        for r in results:
            print(f"[{_ICON[r.status]}] {r.id}: {r.message}")
            for dn in r.dns[:20]:
                print(f"         {dn}")
            if len(r.dns) > 20:
                print(f"         ... and {len(r.dns) - 20} more")
            if r.fixable:
                print(f"         fix: heracles fix {r.id}")
    return 1 if any(r.status == "error" for r in results) else 0


def run_fix(args: argparse.Namespace, factory: DirectoryFactory) -> int:
    directory = _directory(args, factory)
    if directory is None:
        return 2
    options: dict[str, str] = {}
    if args.user:
        options["dn"] = args.user
    try:
        outcome = setup_checks.run_fix(
            setup_checks.context_for(directory), args.check_id, args.dn or [], options
        )
    except setup_checks.UnknownCheckError:
        print(f"error: {args.check_id!r} is not a fixable check", file=sys.stderr)
        return 2
    except DirectoryError as exc:
        print(f"error: {type(exc).__name__}", file=sys.stderr)
        return 1
    for dn in outcome.fixed:
        print(f"fixed  {dn}")
    for dn, reason in outcome.failed.items():
        print(f"failed {dn}: {reason}", file=sys.stderr)
    return 1 if outcome.failed else 0


def run_create_admin(args: argparse.Namespace, factory: DirectoryFactory) -> int:
    directory = _directory(args, factory)
    if directory is None:
        return 2
    password = args.password
    if password is None:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            print("error: the passwords differ", file=sys.stderr)
            return 2
    policy = PasswordPolicy()
    problems = policy.problems(password)
    if problems:
        print("error: " + "; ".join(problems), file=sys.stderr)
        return 2
    ctx = setup_checks.context_for(directory)
    try:
        dn = setup_checks.create_admin_user(ctx, args.uid, password_hash=policy.hash_new(password))
    except DirectoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"created {dn}")
    return 0


def register(sub: Any, factory: DirectoryFactory) -> None:
    """Add the commands to the sub-parsers object of the main parser."""

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", help="configuration file (default: $HERACLES_CONFIG)")
        p.add_argument("--directory", help="directory id (default: the first one)")

    check = sub.add_parser("check", help="run the directory health checks")
    common(check)
    check.add_argument("--json", action="store_true", help="machine readable output")

    def do_check(a: argparse.Namespace) -> int:
        return run_check(a, factory)

    check.set_defaults(func=do_check)

    fix = sub.add_parser("fix", help="apply the fix of one health check")
    common(fix)
    fix.add_argument("check_id", choices=[c for c, _a, f in setup_checks.CHECKS if f is not None])
    fix.add_argument("--dn", action="append", help="limit the fix to this entry (repeatable)")
    fix.add_argument("--user", help="user DN (super_admin fix)")

    def do_fix(a: argparse.Namespace) -> int:
        return run_fix(a, factory)

    fix.set_defaults(func=do_fix)

    create = sub.add_parser("create-admin", help="create a user with full rights")
    common(create)
    create.add_argument("--uid", required=True)
    create.add_argument("--password", help="password (prompted when omitted)")

    def do_create(a: argparse.Namespace) -> int:
        return run_create_admin(a, factory)

    create.set_defaults(func=do_create)
