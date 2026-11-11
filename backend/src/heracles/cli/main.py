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

    # --- P3 admin ---
    admin_commands.register(sub, directories or admin_commands.load_directories)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
