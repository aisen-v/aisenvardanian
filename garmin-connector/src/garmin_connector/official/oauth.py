"""OAuth 2.0 (PKCE) sign-in for the official Garmin Connect Developer Program API.

Your app's consumer key and secret come from the Garmin developer portal and are
read from the environment (never stored by this tool):

    GARMIN_CLIENT_ID       consumer key
    GARMIN_CLIENT_SECRET   consumer secret
    GARMIN_REDIRECT_URI    must match the redirect URL in your app's settings
                           (default http://localhost:8765/oauth/callback)

Signing in opens Garmin's consent page; after you approve, the user access and
refresh tokens are saved to <token dir>/official_tokens.json (owner-only) and
refreshed automatically.

URLs follow Garmin's OAuth2 PKCE specification and can be overridden with
GARMIN_AUTH_URL / GARMIN_TOKEN_URL if your portal docs say otherwise.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Callable

import requests

from ..auth import NotSignedIn, token_dir

AUTH_URL = os.getenv("GARMIN_AUTH_URL", "https://connect.garmin.com/oauth2Confirm")
TOKEN_URL = os.getenv(
    "GARMIN_TOKEN_URL", "https://diauth.garmin.com/di-oauth2-service/oauth/token"
)
DEFAULT_REDIRECT = "http://localhost:8765/oauth/callback"
TIMEOUT = 30


class OAuthError(RuntimeError):
    pass


def credentials() -> tuple[str, str]:
    cid, secret = os.getenv("GARMIN_CLIENT_ID"), os.getenv("GARMIN_CLIENT_SECRET")
    if not cid or not secret:
        raise NotSignedIn(
            "Set GARMIN_CLIENT_ID and GARMIN_CLIENT_SECRET (your Garmin developer "
            "app's consumer key and secret) in the environment."
        )
    return cid, secret


def redirect_uri() -> str:
    return os.getenv("GARMIN_REDIRECT_URI", DEFAULT_REDIRECT)


def tokens_path() -> Path:
    return Path(token_dir()) / "official_tokens.json"


# ---------------------------------------------------------------- PKCE


def make_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using the S256 method."""
    verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(client_id: str, challenge: str, state: str, redirect: str) -> str:
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "redirect_uri": redirect,
            "state": state,
        }
    )
    return f"{AUTH_URL}?{query}"


# ---------------------------------------------------------------- token storage


def _save(tokens: dict[str, Any]) -> None:
    path = tokens_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.parent.chmod(0o700)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(tokens, f)
    tmp.replace(path)


def load_tokens() -> dict[str, Any] | None:
    try:
        return json.loads(tokens_path().read_text())
    except FileNotFoundError:
        return None


def forget_tokens() -> None:
    with contextlib.suppress(FileNotFoundError):
        tokens_path().unlink()


def _token_request(data: dict[str, str]) -> dict[str, Any]:
    cid, secret = credentials()
    resp = requests.post(
        TOKEN_URL,
        data={**data, "client_id": cid, "client_secret": secret},
        headers={"Accept": "application/json"},
        timeout=TIMEOUT,
    )
    if resp.status_code != 200:
        raise OAuthError(f"Garmin token request failed ({resp.status_code}): {resp.text[:300]}")
    body = resp.json()
    now = int(time.time())
    body["expires_at"] = now + int(body.get("expires_in", 0))
    if "refresh_token_expires_in" in body:
        body["refresh_expires_at"] = now + int(body["refresh_token_expires_in"])
    return body


def exchange_code(code: str, verifier: str, redirect: str) -> dict[str, Any]:
    tokens = _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect,
        }
    )
    _save(tokens)
    return tokens


_refresh_lock = threading.Lock()


def access_token(force_refresh: bool = False) -> str:
    """A valid user access token, refreshing (and re-saving) it when needed."""
    with _refresh_lock:
        tokens = load_tokens()
        if not tokens:
            raise NotSignedIn("Not signed in to the Garmin API. Run `garmin-connector login`.")
        if force_refresh or tokens.get("expires_at", 0) - 120 < time.time():
            if tokens.get("refresh_expires_at", float("inf")) < time.time():
                raise NotSignedIn(
                    "The Garmin refresh token has expired. Run `garmin-connector login` again."
                )
            new = _token_request(
                {"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}
            )
            # Garmin issues a new refresh token with each refresh; keep the old
            # one only if it didn't.
            new.setdefault("refresh_token", tokens["refresh_token"])
            for k in ("user_id", "refresh_expires_at"):
                if k in tokens:
                    new.setdefault(k, tokens[k])
            _save(new)
            tokens = new
        return tokens["access_token"]


def remember_user_id(user_id: str) -> None:
    tokens = load_tokens() or {}
    tokens["user_id"] = user_id
    _save(tokens)


# ---------------------------------------------------------------- interactive sign-in


def _wait_for_redirect(redirect: str, timeout: float = 300) -> str:
    """Serve the redirect URL on localhost once and return the full URL hit."""
    parsed = urllib.parse.urlparse(redirect)
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if urllib.parse.urlparse(self.path).path != parsed.path:
                self.send_error(404)
                return
            result["url"] = f"{parsed.scheme}://{parsed.netloc}{self.path}"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h2>Garmin connected.</h2><p>You can close this tab and go back to the terminal.</p>"
            )

        def log_message(self, *args):
            pass

    host = parsed.hostname or "localhost"
    server = http.server.HTTPServer((host, parsed.port or 80), Handler)
    server.timeout = 1
    deadline = time.time() + timeout
    with server:
        while "url" not in result and time.time() < deadline:
            server.handle_request()
    if "url" not in result:
        raise OAuthError("Timed out waiting for Garmin to redirect back.")
    return result["url"]


def interactive_login(
    output: Callable[[str], None] = print,
    ask: Callable[[str], str] = input,
    open_browser: bool = True,
) -> dict[str, Any]:
    """Run the consent flow. Uses a local listener when the redirect URL is on
    localhost; otherwise asks you to paste the URL Garmin redirected to."""
    cid, _ = credentials()
    redirect = redirect_uri()
    verifier, challenge = make_pkce()
    state = secrets.token_urlsafe(24)
    url = authorization_url(cid, challenge, state, redirect)

    output(f"Open this page and approve access:\n\n  {url}\n")
    if open_browser:
        with contextlib.suppress(Exception):
            webbrowser.open(url)

    host = urllib.parse.urlparse(redirect).hostname
    if host in ("localhost", "127.0.0.1"):
        output(f"Waiting for Garmin to redirect to {redirect} ...")
        returned = _wait_for_redirect(redirect)
    else:
        returned = ask("After approving, paste the full URL you were redirected to: ").strip()

    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(returned).query))
    if "error" in params:
        raise OAuthError(f"Garmin refused access: {params.get('error_description') or params['error']}")
    if params.get("state") != state:
        raise OAuthError("The state in the redirect doesn't match; start the sign-in again.")
    if "code" not in params:
        raise OAuthError("No authorization code in the redirect URL.")
    return exchange_code(params["code"], verifier, redirect)
