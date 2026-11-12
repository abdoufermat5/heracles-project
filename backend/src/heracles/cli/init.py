"""``heracles init``: the setup wizard of the web console, on the command line.

Same steps and same code as the console's setup mode (:mod:`heracles.setup.service`): the
directory, a connection test, a schema check, the administrator and the plugins, ending with a
configuration file. Without ``--yes`` missing answers are asked; with it the command never
prompts and fails when an answer is missing.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from heracles.setup import service

type Ask = Callable[[str, str], str]
type AskSecret = Callable[[str], str]


class InitError(Exception):
    """The setup cannot continue; the message is shown to the operator."""


def _read_secret_file(path: str, what: str) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise InitError(f"cannot read {what} file {path}: {exc.strerror or exc}") from exc
    return text.rstrip("\r\n")


def _default_ask(question: str, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{question}{suffix}: ").strip()
    return answer or default


class _Prompter:
    def __init__(self, interactive: bool, ask: Ask, secret: AskSecret) -> None:
        self.interactive = interactive
        self._ask = ask
        self._secret = secret

    def text(self, value: str | None, flag: str, question: str, default: str | None = None) -> str:
        """``value``, else the answer; ``default=None`` marks the answer as required."""
        if value is not None:
            return value
        if not self.interactive:
            if default is not None:
                return default
            raise InitError(f"{flag} is required with --yes")
        return self._ask(question, default or "")

    def password(self, value: str | None, flag: str, question: str, *, confirm: bool) -> str:
        if value is not None:
            return value
        if not self.interactive:
            raise InitError(f"{flag} is required with --yes")
        first = self._secret(f"{question}: ")
        if confirm and first != self._secret("Repeat: "):
            raise InitError("the passwords differ")
        return first

    def yes(self, question: str, default: bool = True) -> bool:
        if not self.interactive:
            return default
        hint = "Y/n" if default else "y/N"
        answer = self._ask(f"{question} ({hint})", "").lower()
        return default if not answer else answer.startswith("y")


def run_init(
    args: argparse.Namespace,
    *,
    ask: Ask = _default_ask,
    secret: AskSecret = getpass.getpass,
    factory: service.ClientFactory = service.default_client_factory,
    out: Callable[[str], None] = print,
) -> int:
    """Run the wizard; returns the process exit code."""
    try:
        return _run(args, _Prompter(not args.yes, ask, secret), factory, out)
    except InitError as exc:
        print(f"heracles init: {exc}", file=sys.stderr)
        return 2
    except service.SetupError as exc:
        print(f"heracles init: {exc.message}", file=sys.stderr)
        for name, message in exc.fields.items():
            print(f"  {name}: {message}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nheracles init: cancelled", file=sys.stderr)
        return 130


def _run(
    args: argparse.Namespace,
    ask: _Prompter,
    factory: service.ClientFactory,
    out: Callable[[str], None],
) -> int:
    output = service.config_path_for(args.output)
    existing = service.read_raw_config(output) if output.is_file() else {}
    if existing.get("directories") and not args.force:
        raise InitError(f"{output} already configures a directory (use --force to replace it)")

    # 1. the directory
    out("Directory")
    uri = ask.text(args.uri, "--uri", "LDAP address (ldap://host or ldaps://host)")
    bind_dn = ask.text(args.bind_dn, "--bind-dn", "Bind DN (service account)")
    password_file: str | None = args.bind_password_file
    bind_password = ask.password(
        _read_secret_file(password_file, "bind password") if password_file else None,
        "--bind-password-file",
        "Bind password",
        confirm=False,
    )
    base_dn = ask.text(args.base_dn, "--base-dn", "Base DN (for example dc=example,dc=org)")
    spec = service.DirectorySpec(
        uri=uri,
        base_dn=base_dn,
        bind_dn=bind_dn,
        bind_password=bind_password,
        starttls=bool(args.starttls),
        ca_file=args.ca_file,
        label=args.label or "",
    )

    # 2. test, 3. schema
    while True:
        result = service.test_directory(spec, factory)
        if not result.ok:
            message = result.error["message"] if result.error else "unknown error"
            out(f"  connection failed: {message}")
            raise InitError("the directory cannot be used")  # re-run with other answers
        out("  connected")
        if not result.base_dn_exists:
            raise InitError(
                f"{base_dn} does not exist in the directory"
                + (
                    f" (naming contexts: {', '.join(result.naming_contexts)})"
                    if result.naming_contexts
                    else ""
                )
            )
        out("  base DN found")
        out(
            "  the account can write" if result.can_write else "  WARNING: the account cannot write"
        )
        if result.schema_installed:
            out("  Heracles schema installed")
            break
        schema_file = output.parent / "heracles.ldif"
        try:
            schema_file.write_text(_schema_text(), encoding="utf-8")
            where = str(schema_file)
        except OSError:
            where = "(run: heracles schema export -o heracles.ldif)"
        out(
            f"  Heracles schema missing ({len(result.missing_classes)} classes): "
            f"exported to {where}\n"
            "  load it on the LDAP server (for OpenLDAP: ldapadd -Y EXTERNAL -H ldapi:/// -f "
            "heracles.ldif), then continue"
        )
        if not ask.interactive or not ask.yes("Schema loaded, test again?"):
            raise InitError("the Heracles schema is not installed on the directory")

    # 4. the administrator
    out("Administrator")
    uid = ask.text(args.admin_uid, "--admin-uid", "Login", "admin")
    admin_file: str | None = args.admin_password_file
    admin_password = ask.password(
        _read_secret_file(admin_file, "administrator password") if admin_file else None,
        "--admin-password-file",
        "Password",
        confirm=True,
    )
    mail = ask.text(args.admin_mail, "--admin-mail", "Mail address (optional)", "")
    admin = service.AdminSpec(uid=uid, password=admin_password, mail=mail)

    # 5. plugins
    out("Plugins")
    choice = args.plugins
    if choice is None and ask.interactive:
        choice = ask.text(
            None, "--plugins", "Profile: core, all, or a comma separated list", "core"
        )
    plugins = service.resolve_plugins(choice)
    out(f"  {', '.join(plugins)}")

    public_url: str | None = args.public_url
    applied = service.apply_setup(spec, admin, plugins, public_url, output, factory)
    out(f"Administrator {applied.admin_dn} " + ("created" if applied.admin_created else "exists"))
    out(f"Configuration written to {applied.config_path}")
    out(f"Next: heracles serve --config {applied.config_path}")
    return 0


def _schema_text() -> str:
    from heracles.schema.export import render_ldif

    return render_ldif()


def register(sub: Any) -> None:
    init = sub.add_parser("init", help="set up a directory and write the configuration")
    init.add_argument("--uri", help="LDAP address")
    init.add_argument(
        "--starttls", action="store_true", help="upgrade the connection with STARTTLS"
    )
    init.add_argument("--ca-file", help="CA certificate file to trust")
    init.add_argument("--bind-dn", help="service account DN")
    init.add_argument("--bind-password-file", help="file holding the service account password")
    init.add_argument("--base-dn", help="base DN of the directory")
    init.add_argument("--label", help="name shown in the console (default: the id)")
    init.add_argument("--admin-uid", help="login of the administrator to create")
    init.add_argument("--admin-password-file", help="file holding the administrator password")
    init.add_argument("--admin-mail", help="mail address of the administrator")
    init.add_argument("--plugins", help="core, all, or a comma separated list of plugins")
    init.add_argument("--public-url", help="address users reach the console at")
    init.add_argument("--output", help="configuration file to write (default: $HERACLES_CONFIG)")
    init.add_argument("--force", action="store_true", help="replace an existing configuration")
    init.add_argument("--yes", action="store_true", help="never prompt; fail on a missing answer")
    init.set_defaults(func=run_init)
