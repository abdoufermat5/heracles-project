"""``heracles`` command line."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from heracles.server import build_app, build_demo_app

    app = build_demo_app(args.static) if args.demo else build_app(args.config)
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Heracles CLI."""
    parser = argparse.ArgumentParser(prog="heracles", description="Heracles directory console")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the web server")
    serve.add_argument("--config", help="configuration file (default: $HERACLES_CONFIG)")
    serve.add_argument("--demo", action="store_true", help="use the in-memory demo directory")
    serve.add_argument("--static", help="built frontend directory to serve (demo mode)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=_serve)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
