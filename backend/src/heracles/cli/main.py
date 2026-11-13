"""``heracles`` command line."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from urllib.parse import urlsplit

from heracles.cli import admin as admin_commands
from heracles.cli import init as init_command
from heracles.cli.secrets import SecretError, read_secret_file
from heracles.setup import service as setup_service


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from heracles.server import build_app, build_demo_app

    workers = int(args.workers)
    if workers < 1:
        print("heracles serve: --workers must be at least 1", file=sys.stderr)
        return 2
    if not args.demo and setup_service.setup_required(args.config):
        if workers != 1:
            print(
                "heracles serve: no configuration found, so the server starts in setup mode, "
                "which needs --workers 1; finish the setup, then restart with more workers",
                file=sys.stderr,
            )
            return 2
        from pathlib import Path

        from heracles.setup.mode import make_setup_server

        static = Path(args.static) if args.static else setup_service.default_static_dir()
        dispatcher = make_setup_server(
            args.config,
            static_dir=static,
            with_worker=args.with_worker,
            worker_interval=args.worker_interval,
        )
        uvicorn.run(dispatcher, host=args.host, port=args.port, proxy_headers=True)
        return 0
    if workers > 1:
        if args.demo:
            print(
                "heracles serve: --workers > 1 cannot be used with --demo: the demo directory "
                "lives in the memory of one process",
                file=sys.stderr,
            )
            return 2
        # Every worker builds its own application from the same configuration; they share
        # sessions, the login limiter and recovery tokens through the application database.
        if args.config:
            os.environ["HERACLES_CONFIG"] = args.config
        if args.with_worker:
            os.environ["HERACLES_WITH_WORKER"] = "1"
            os.environ["HERACLES_WORKER_INTERVAL"] = str(args.worker_interval)
        uvicorn.run(
            "heracles.server:build_app",
            factory=True,
            workers=workers,
            host=args.host,
            port=args.port,
            proxy_headers=True,
        )
        return 0
    if args.demo:
        app = build_demo_app(args.static)
        if args.with_worker:
            from heracles.tasks.wiring import attach_scheduler

            attach_scheduler(app, interval=args.worker_interval)
    else:
        os.environ["HERACLES_WORKER_INTERVAL"] = str(args.worker_interval)
        app = build_app(args.config, with_worker=args.with_worker)
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True)
    return 0


def _worker(args: argparse.Namespace) -> int:
    import signal
    import threading

    from heracles.ldap.config import ConfigError
    from heracles.tasks import wiring

    if args.interval <= 0:
        print("heracles worker: --interval must be positive", file=sys.stderr)
        return 2
    try:
        scheduler = wiring.build_worker(args.config)
    except ConfigError as exc:
        print(f"heracles worker: {exc}", file=sys.stderr)
        return 2
    stop = threading.Event()
    if not args.once:

        def request_stop(_signum: int, _frame: object) -> None:
            stop.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, request_stop)
    while True:
        runs = scheduler.run_pass()
        if runs is None:
            print("heracles worker: another worker holds the lease", file=sys.stderr)
        else:
            for run in runs:
                print(
                    f"{run.directory} {run.runner}: {run.status} ({run.summary})", file=sys.stderr
                )
        if args.once or stop.wait(args.interval):
            return 0


def _dns(args: argparse.Namespace) -> int:
    try:
        from heracles_plugins.dns.server import serve
    except ImportError:
        print(
            "heracles dns: dnspython is not installed; install Heracles with the 'dns' extra",
            file=sys.stderr,
        )
        return 2
    except RuntimeError as exc:  # dnspython missing
        print(f"heracles dns: {exc}", file=sys.stderr)
        return 2

    if args.demo:
        from heracles import demo

        directory = demo.build_demo_directory()
    else:
        from heracles.ldap.config import ConfigError, load_settings
        from heracles.ldap.pyldap import LdapUnavailableError, PyLdapDirectory

        try:
            settings = load_settings(args.config)
        except ConfigError as exc:
            print(f"heracles dns: {exc}", file=sys.stderr)
            return 2
        # The server answers for one directory; like the console, the first configured one.
        if not settings.directories:
            print("heracles dns: no directory is configured", file=sys.stderr)
            return 2
        try:
            directory = PyLdapDirectory(settings.directories[0])
        except LdapUnavailableError as exc:
            print(f"heracles dns: {exc}", file=sys.stderr)
            return 2

    transport = "udp" if args.no_tcp else "udp and tcp"
    print(f"heracles dns: listening on {args.host}:{args.port} ({transport})", file=sys.stderr)
    try:
        serve(directory, args.host, args.port, tcp=not args.no_tcp)
    except RuntimeError as exc:  # dnspython missing
        print(f"heracles dns: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        pass
    return 0


def _schema_export(args: argparse.Namespace) -> int:
    from heracles.schema.export import render_ldif, render_schema

    text = render_ldif() if args.format == "ldif" else render_schema()
    if args.output in (None, "-"):
        sys.stdout.write(text)
    else:
        with open(args.output, "w", encoding="utf-8") as out:
            out.write(text)
    return 0


def _migrate_directory(args: argparse.Namespace) -> int:
    import csv

    from heracles.migrate.directory import migrate_ldif

    if os.path.exists(args.target) and os.path.samefile(args.source, args.target):
        print(
            "heracles migrate-directory: the target must not be the source export", file=sys.stderr
        )
        return 2
    with open(args.source, encoding="utf-8") as src:
        converted, report = migrate_ldif(src.read())
    err = sys.stderr
    print(f"renamed names: {len(report.renamed)} ({sum(report.renamed.values())} uses)", file=err)
    for cls, count in sorted(report.added_classes.items()):
        print(f"added objectClass {cls} to {count} entries", file=err)
    for dn in report.dropped_entries:
        print(f"dropped transient entry {dn}", file=err)
    for line in report.dropped_values:
        print(f"dropped value {line}", file=err)
    for line in report.errors:
        print(f"error: {line}", file=err)
    if args.report:
        with open(args.report, "w", encoding="utf-8", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(["old", "new"])
            writer.writerows(report.rename_table())
    if report.errors and not args.force:
        print(f"{len(report.errors)} error(s): nothing written (use --force)", file=err)
        return 1
    # the export holds password hashes: readable by the owner only
    fd = os.open(args.target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        os.fchmod(out.fileno(), 0o600)
        out.write(converted)
    return 0


#: Where ``db migrate-to-postgres`` reads the destination when ``--to`` is omitted.
DATABASE_URL_ENV = "HERACLES_DATABASE_URL"


def _carries_password(url: str) -> bool:
    try:
        return urlsplit(url).password is not None
    except ValueError:
        return False


def _destination(args: argparse.Namespace) -> str | None:
    """The PostgreSQL URL: ``--to``, ``--to-file``, or ``$HERACLES_DATABASE_URL``."""
    if args.to is not None:
        if _carries_password(args.to):
            print(
                "warning: --to puts the database password in the process list and the shell"
                f" history; use --to-file or ${DATABASE_URL_ENV}",
                file=sys.stderr,
            )
        return args.to
    if args.to_file is not None:
        try:
            return read_secret_file(args.to_file, "database URL")
        except SecretError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return None
    from_env = os.environ.get(DATABASE_URL_ENV) or None
    if from_env is not None:
        return from_env
    print(
        f"error: no destination: use --to, --to-file or ${DATABASE_URL_ENV}",
        file=sys.stderr,
    )
    return None


def _db_migrate_to_postgres(args: argparse.Namespace) -> int:
    from pathlib import Path

    from heracles.storage import DatabaseError
    from heracles.storage.copy import copy_sqlite_to_postgres

    url = _destination(args)
    if url is None:
        return 2
    try:
        copied = copy_sqlite_to_postgres(Path(args.source), url)
    except DatabaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for table, count in copied.items():
        print(f"{table}: {count} row(s)")
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    directories: admin_commands.DirectoryFactory | None = None,
) -> int:
    """Run the Heracles CLI."""
    parser = argparse.ArgumentParser(prog="heracles", description="Heracles directory console")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the web server")
    serve.add_argument("--config", help="configuration file (default: $HERACLES_CONFIG)")
    serve.add_argument("--demo", action="store_true", help="use the in-memory demo directory")
    serve.add_argument("--static", help="built frontend directory to serve (demo and setup mode)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8420)
    serve.add_argument(
        "--workers",
        type=int,
        default=1,
        help="worker processes (state is shared through the application database)",
    )
    serve.add_argument(
        "--with-worker",
        action="store_true",
        help="also run the task scheduler in a background thread",
    )
    serve.add_argument(
        "--worker-interval", type=float, default=60.0, help="seconds between scheduler passes"
    )
    serve.set_defaults(func=_serve)

    worker = sub.add_parser("worker", help="run the scheduled tasks (reminders, audit purge, ...)")
    worker.add_argument("--config", help="configuration file (default: $HERACLES_CONFIG)")
    worker.add_argument("--interval", type=float, default=60.0, help="seconds between passes")
    worker.add_argument("--once", action="store_true", help="run one pass and exit")
    worker.set_defaults(func=_worker)

    dns = sub.add_parser("dns", help="serve the DNS zones stored in the directory")
    source = dns.add_mutually_exclusive_group()
    source.add_argument("--config", help="configuration file (default: $HERACLES_CONFIG)")
    source.add_argument("--demo", action="store_true", help="use the in-memory demo directory")
    dns.add_argument("--host", default="127.0.0.1")
    dns.add_argument("--port", type=int, default=5353)
    dns.add_argument("--no-tcp", action="store_true", help="answer over UDP only")
    dns.set_defaults(func=_dns)

    schema = sub.add_parser("schema", help="the Heracles LDAP schema")
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)
    export = schema_sub.add_parser("export", help="print the schema for the LDAP server")
    export.add_argument(
        "--format",
        choices=("ldif", "schema"),
        default="ldif",
        help="cn=config LDIF (default) or OpenLDAP .schema file",
    )
    export.add_argument("-o", "--output", help="output file (default: standard output)")
    export.set_defaults(func=_schema_export)

    migrate = sub.add_parser(
        "migrate-directory",
        help="convert an LDIF export from the legacy layout to the Heracles schema",
    )
    migrate.add_argument("source", help="LDIF export of the existing directory")
    migrate.add_argument("target", help="converted LDIF to import into the new server")
    migrate.add_argument("--report", help="CSV file listing every renamed name (old,new)")
    migrate.add_argument(
        "--force", action="store_true", help="write the result even when errors were found"
    )
    migrate.set_defaults(func=_migrate_directory)

    db = sub.add_parser("db", help="the application database")
    db_sub = db.add_subparsers(dest="db_command", required=True)
    to_pg = db_sub.add_parser(
        "migrate-to-postgres",
        help="copy the SQLite application database into PostgreSQL (to run several replicas)",
    )
    to_pg.add_argument("--from", dest="source", required=True, help="the SQLite file")
    destination = to_pg.add_mutually_exclusive_group()
    destination.add_argument(
        "--to",
        help=f"postgresql://user:password@host/db (empty); ${DATABASE_URL_ENV} also works",
    )
    destination.add_argument(
        "--to-file", help="read the URL from this file ('-' for standard input)"
    )
    to_pg.set_defaults(func=_db_migrate_to_postgres)

    init_command.register(sub)

    # --- P3 admin ---
    admin_commands.register(sub, directories or admin_commands.load_directories)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
