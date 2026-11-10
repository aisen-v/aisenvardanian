"""Command line: sign in, fetch data, and run the MCP server or JSON API.

    garmin-connector login
    garmin-connector sleep --date yesterday
    garmin-connector activities --limit 5
    garmin-connector download 12345678901 --format gpx
    garmin-connector mcp                      # MCP over stdio (Claude Desktop / Code)
    garmin-connector serve                    # JSON API + MCP over HTTP
"""

from __future__ import annotations

import argparse
import getpass
import inspect
import json
import logging
import os
import secrets
import sys
from pathlib import Path

from . import __version__, auth, data


def _cmd_login(args) -> int:
    email = args.email or os.getenv("GARMIN_EMAIL") or input("Garmin email: ").strip()
    password = os.getenv("GARMIN_PASSWORD") or getpass.getpass("Garmin password: ")
    client = auth.login(
        email,
        password,
        prompt_mfa=lambda: input("MFA code (from email or authenticator app): ").strip(),
        is_cn=args.cn,
    )
    print(f"Signed in as {client.get_full_name() or email}.")
    print(f"Session saved to {auth.token_dir()} (your password is not stored).")
    return 0


def _cmd_logout(args) -> int:
    auth.logout()
    print(f"Removed the saved session from {auth.token_dir()}.")
    return 0


def _cmd_status(args) -> int:
    try:
        g = auth.get_client()
    except auth.NotSignedIn as e:
        print(e, file=sys.stderr)
        return 1
    print(f"Signed in as {g.get_full_name()} (tokens in {auth.token_dir()}).")
    return 0


def _cmd_download(args) -> int:
    blob, filename = data.download_activity(args.activity_id, args.format)
    out = Path(args.output or filename)
    out.write_bytes(blob)
    print(f"Saved {out} ({len(blob):,} bytes).")
    return 0


def _cmd_mcp(args) -> int:
    from .server import build_mcp

    build_mcp().run("stdio")
    return 0


def _cmd_serve(args) -> int:
    import uvicorn

    from .server import LOCAL_HOSTS, build_http_app

    token = os.getenv("GARMIN_CONNECTOR_TOKEN")
    exposed = args.host not in LOCAL_HOSTS or bool(args.allowed_host)
    if not token and exposed:
        token = secrets.token_urlsafe(32)
        print(
            "No GARMIN_CONNECTOR_TOKEN set, so a one-time token was generated:\n"
            f"  {token}\n"
            "Set GARMIN_CONNECTOR_TOKEN to keep it the same across restarts.",
            file=sys.stderr,
        )
    if token:
        print("Requests need 'Authorization: Bearer <token>' or '?token=<token>'.", file=sys.stderr)
    print(
        f"JSON API: http://{args.host}:{args.port}/api   MCP: http://{args.host}:{args.port}/mcp",
        file=sys.stderr,
    )
    app = build_http_app(token, host=args.host, allowed_hosts=args.allowed_host)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _endpoint_runner(fn):
    def run(args) -> int:
        kwargs = {p: getattr(args, p) for p in inspect.signature(fn).parameters}
        result = fn(**kwargs)
        print(json.dumps(result, indent=None if args.compact else 2, default=str))
        return 0

    return run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="garmin-connector",
        description="Personal connector to your Garmin Connect data.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("-v", "--verbose", action="store_true", help="log HTTP details")
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("login", help="sign in and save a session")
    p.add_argument("--email")
    p.add_argument("--cn", action="store_true", help="account is on Garmin China (garmin.cn)")
    p.set_defaults(run=_cmd_login)

    sub.add_parser("logout", help="forget the saved session").set_defaults(run=_cmd_logout)
    sub.add_parser("status", help="check the saved session works").set_defaults(run=_cmd_status)

    p = sub.add_parser("mcp", help="run the MCP server over stdio (Claude Desktop / Claude Code)")
    p.set_defaults(run=_cmd_mcp)

    p = sub.add_parser("serve", help="run the JSON API and MCP server over HTTP")
    p.add_argument("--host", default="127.0.0.1", help="interface to listen on (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument(
        "--allowed-host",
        action="append",
        metavar="HOSTNAME",
        help="public hostname this is reached at through a tunnel/proxy (repeatable)",
    )
    p.set_defaults(run=_cmd_serve)

    p = sub.add_parser("download", help="download an activity file")
    p.add_argument("activity_id", type=int)
    p.add_argument("--format", default="fit", choices=data.DOWNLOAD_FORMATS,
                   help="fit = Garmin's original file, zipped (default)")
    p.add_argument("-o", "--output", help="file to write (default activity_<id>.<ext>)")
    p.set_defaults(run=_cmd_download)

    for name, fn in data.ENDPOINTS.items():
        doc = (fn.__doc__ or "").strip().splitlines()[0]
        p = sub.add_parser(name.replace("_", "-"), help=doc, description=doc)
        for pname, param in inspect.signature(fn).parameters.items():
            typ = int if param.annotation in (int, "int") else str
            if param.default is inspect.Parameter.empty:
                p.add_argument(pname, type=typ)
            else:
                p.add_argument(f"--{pname.replace('_', '-')}", dest=pname, type=typ,
                               default=param.default, help=f"default: {param.default!r}")
        p.add_argument("--compact", action="store_true", help="print JSON on one line")
        p.set_defaults(run=_endpoint_runner(fn))

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Never log to stdout: in `mcp` mode stdout carries the protocol.
    logging.basicConfig(
        stream=sys.stderr, level=logging.DEBUG if args.verbose else logging.WARNING
    )
    try:
        return args.run(args)
    except (auth.NotSignedIn, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
