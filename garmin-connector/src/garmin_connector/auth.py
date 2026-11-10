"""Signing in to Garmin Connect and keeping a reusable session.

Garmin has no public API for personal accounts, so this uses the same sign-in
as the Garmin Connect app (through the ``garminconnect`` library). You sign in
once with your email and password (plus an MFA code if your account has one);
the resulting tokens are saved to disk and refreshed automatically after that,
so your password is never stored.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

from garminconnect import Garmin, GarminConnectAuthenticationError

DEFAULT_TOKEN_DIR = "~/.garminconnect"


def token_dir() -> str:
    """Where the session tokens live: $GARMINTOKENS or ~/.garminconnect."""
    return str(Path(os.getenv("GARMINTOKENS") or DEFAULT_TOKEN_DIR).expanduser())


def login(
    email: str,
    password: str,
    prompt_mfa: Callable[[], str] | None = None,
    is_cn: bool = False,
) -> Garmin:
    """Sign in with credentials and save the session tokens to ``token_dir()``."""
    path = token_dir()
    Path(path).mkdir(mode=0o700, parents=True, exist_ok=True)
    client = Garmin(email=email, password=password, is_cn=is_cn, prompt_mfa=prompt_mfa)
    client.login(tokenstore=path)
    # login() writes the tokens when the store is a path; dump again so a fresh
    # sign-in always leaves a token file behind.
    client.client.dump(path)
    return client


def logout() -> None:
    """Forget the saved session (does not revoke it at Garmin)."""
    Garmin().logout(tokenstore=token_dir())


_client: Garmin | None = None
_lock = threading.Lock()


def get_client() -> Garmin:
    """Return a signed-in client, resuming the saved session on first use.

    Falls back to GARMIN_EMAIL / GARMIN_PASSWORD from the environment when no
    session has been saved yet (useful on a server without a terminal).
    """
    global _client
    with _lock:
        if _client is None:
            client = Garmin(
                email=os.getenv("GARMIN_EMAIL"),
                password=os.getenv("GARMIN_PASSWORD"),
                is_cn=os.getenv("GARMIN_IS_CN", "").lower() in ("1", "true", "yes"),
            )
            try:
                client.login(tokenstore=token_dir())
            except GarminConnectAuthenticationError as e:
                raise NotSignedIn(
                    f"Not signed in to Garmin Connect ({e}). "
                    "Run `garmin-connector login` first."
                ) from e
            _client = client
        return _client


def reset_client() -> None:
    global _client
    with _lock:
        _client = None


class NotSignedIn(RuntimeError):
    pass
