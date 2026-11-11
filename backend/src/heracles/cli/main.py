"""``heracles`` command line."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from heracles.cli import admin as admin_commands


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from heracles.server import build_app, build_demo_app

    workers = int(args.workers)
    if workers < 1:
        print("heracles serve: --workers must be at least 1", file=sys.stderr)
        return 2
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
        uvicorn.run(
            "heracles.server:build_app",
            factory=True,
            workers=workers,
            host=args.host,
            port=args.port,
            proxy_headers=True,
        )
        return 0
    app = build_demo_app(args.static) if args.demo else build_app(args.config)
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True)
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
    serve.add_argument("--static", help="built frontend directory to serve (demo mode)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8420)
    serve.add_argument(
        "--workers",
        type=int,
        default=1,
        help="worker processes (state is shared through the application database)",
    )
    serve.set_defaults(func=_serve)

    dns = sub.add_parser("dns", help="serve the DNS zones stored in the directory")
    source = dns.add_mutually_exclusive_group()
    source.add_argument("--config", help="configuration file (default: $HERACLES_CONFIG)")
    source.add_argument("--demo", action="store_true", help="use the in-memory demo directory")
    dns.add_argument("--host", default="127.0.0.1")
    dns.add_argument("--port", type=int, default=5353)
    dns.add_argument("--no-tcp", action="store_true", help="answer over UDP only")
    dns.set_defaults(func=_dns)

    # --- P3 admin ---
    admin_commands.register(sub, directories or admin_commands.load_directories)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
