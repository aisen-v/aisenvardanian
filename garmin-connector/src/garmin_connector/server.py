"""MCP server and JSON API over the endpoints in ``data.py``.

* ``build_mcp()`` registers every endpoint as a read-only MCP tool.
* ``build_http_app()`` serves, on one port:
    - ``/mcp``                    the MCP endpoint (streamable HTTP)
    - ``/api``                    lists the JSON endpoints
    - ``/api/<name>?param=value`` one endpoint as JSON
    - ``/api/activity/<id>/download?format=fit|tcx|gpx|kml|csv``
    - ``/health``                 liveness check (no token needed)
  Everything except ``/health`` requires the access token when one is set.
"""

from __future__ import annotations

import hmac
import inspect
import json
import logging
from typing import Any

import functools

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import data
from .auth import NotSignedIn

log = logging.getLogger("garmin_connector")

INSTRUCTIONS = """\
Read-only access to the user's own Garmin Connect data (sleep, heart rate, HRV,
stress, Body Battery, steps, training readiness/status, VO2 max, activities).
Dates accept YYYY-MM-DD, 'today', 'yesterday' or a number of days ago ('7').
Start with daily_summary or activities; use activity(activity_id) for detail.
Some responses are large time series; prefer summaries when they answer the question.
"""

LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def build_mcp() -> MCPServer:
    mcp = MCPServer(name="garmin", title="Garmin Connect", instructions=INSTRUCTIONS)
    readonly = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
    for name, fn in data.ENDPOINTS.items():
        mcp.tool(name=name, annotations=readonly, structured_output=False)(_explain_errors(fn))
    return mcp


def _explain_errors(fn):
    """Pass error messages through to the model (the SDK hides unexpected ones).

    Without this, "not signed in" or "bad date" would reach Claude only as
    "Error executing tool".
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as e:
            log.warning("%s failed: %s: %s", fn.__name__, type(e).__name__, e)
            raise ToolError(str(e) if isinstance(e, (ValueError, NotSignedIn))
                            else f"{type(e).__name__}: {e}") from e

    return wrapper


# ---------------------------------------------------------------- JSON API


def _coerce(fn, params: dict[str, str]) -> dict[str, Any]:
    """Turn query-string values into the endpoint's parameters."""
    sig = inspect.signature(fn)
    unknown = set(params) - set(sig.parameters) - {"token"}
    if unknown:
        raise ValueError(f"unknown parameter(s): {', '.join(sorted(unknown))}")
    kwargs: dict[str, Any] = {}
    for pname, p in sig.parameters.items():
        if pname not in params:
            if p.default is inspect.Parameter.empty:
                raise ValueError(f"missing parameter: {pname}")
            continue
        raw = params[pname]
        if p.annotation in (int, "int"):
            try:
                kwargs[pname] = int(raw)
            except ValueError:
                raise ValueError(f"{pname} must be a whole number") from None
        else:
            kwargs[pname] = raw
    return kwargs


def _describe(fn) -> dict[str, Any]:
    params = {}
    for pname, p in inspect.signature(fn).parameters.items():
        params[pname] = {
            "type": str(p.annotation).replace("<class '", "").replace("'>", ""),
            "required": p.default is inspect.Parameter.empty,
            **({} if p.default is inspect.Parameter.empty else {"default": p.default}),
        }
    return {"description": (fn.__doc__ or "").strip().splitlines()[0], "params": params}


async def _call(fn, kwargs) -> Response:
    try:
        result = await anyio.to_thread.run_sync(lambda: fn(**kwargs))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except NotSignedIn as e:
        return JSONResponse({"error": str(e)}, status_code=401)
    except Exception as e:  # Garmin errors: rate limits, outages, missing data
        log.exception("Garmin request failed")
        status = 429 if "TooManyRequests" in type(e).__name__ else 502
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=status)
    return Response(json.dumps(result, default=str), media_type="application/json")


def _add_api_routes(mcp: MCPServer) -> None:
    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> Response:
        return JSONResponse({"ok": True})

    @mcp.custom_route("/api", methods=["GET"])
    async def index(request: Request) -> Response:
        eps = {f"/api/{n}": _describe(f) for n, f in data.ENDPOINTS.items()}
        eps["/api/activity/{activity_id}/download"] = {
            "description": "Download an activity file (fit = original .zip)",
            "params": {"format": {"type": "str", "required": False, "default": "fit",
                                  "choices": list(data.DOWNLOAD_FORMATS)}},
        }
        return JSONResponse({"endpoints": eps})

    @mcp.custom_route("/api/activity/{activity_id:int}/download", methods=["GET"])
    async def download(request: Request) -> Response:
        aid = request.path_params["activity_id"]
        fmt = request.query_params.get("format", "fit")
        try:
            blob, filename = await anyio.to_thread.run_sync(
                lambda: data.download_activity(aid, fmt)
            )
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except NotSignedIn as e:
            return JSONResponse({"error": str(e)}, status_code=401)
        except Exception as e:
            log.exception("Garmin download failed")
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=502)
        return Response(
            blob,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @mcp.custom_route("/api/{name}", methods=["GET"])
    async def endpoint(request: Request) -> Response:
        fn = data.ENDPOINTS.get(request.path_params["name"])
        if fn is None:
            return JSONResponse({"error": "no such endpoint; see /api"}, status_code=404)
        try:
            kwargs = _coerce(fn, dict(request.query_params))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return await _call(fn, kwargs)


# ---------------------------------------------------------------- auth


class TokenAuth:
    """ASGI middleware: require the access token on every path but /health.

    The token can be sent as ``Authorization: Bearer <token>`` or as
    ``?token=<token>`` (for clients, like Claude's custom connectors, that only
    take a URL).
    """

    def __init__(self, app, token: str):
        self.app = app
        self.token = token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/health":
            return await self.app(scope, receive, send)
        request = Request(scope)
        given = ""
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            given = auth[7:].strip()
        given = given or request.query_params.get("token", "")
        if not hmac.compare_digest(given.encode(), self.token):
            resp = JSONResponse(
                {"error": "missing or wrong access token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            return await resp(scope, receive, send)
        return await self.app(scope, receive, send)


def build_http_app(
    token: str | None,
    host: str = "127.0.0.1",
    allowed_hosts: list[str] | None = None,
):
    """The combined MCP + JSON API app, wrapped in token auth when a token is set."""
    mcp = build_mcp()
    _add_api_routes(mcp)

    security = None
    if allowed_hosts:
        # Behind a tunnel or reverse proxy the Host header is the public name.
        local = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
        hosts = local + [h for a in allowed_hosts for h in (a, f"{a}:*")]
        security = TransportSecuritySettings(
            allowed_hosts=hosts,
            allowed_origins=[f"{s}://{h}" for h in hosts for s in ("http", "https")],
        )

    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=security,
        host=host,
    )
    return TokenAuth(app, token) if token else app
