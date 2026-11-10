"""Pick which Garmin backend the CLI, JSON API and MCP server use.

* ``official``: the Garmin Connect Developer Program API, with your app's
  consumer key and secret (GARMIN_CLIENT_ID / GARMIN_CLIENT_SECRET).
* ``unofficial``: the Garmin Connect app's own sign-in with your email and
  password, through the garminconnect library.

Set GARMIN_BACKEND to choose; otherwise it's ``official`` when
GARMIN_CLIENT_ID is set.
"""

from __future__ import annotations

import os
from typing import Any, Callable


def name() -> str:
    chosen = os.getenv("GARMIN_BACKEND", "").strip().lower()
    if chosen in ("official", "unofficial"):
        return chosen
    if chosen:
        raise ValueError("GARMIN_BACKEND must be 'official' or 'unofficial'")
    return "official" if os.getenv("GARMIN_CLIENT_ID") else "unofficial"


def is_official() -> bool:
    return name() == "official"


def endpoints() -> dict[str, Callable[..., Any]]:
    if is_official():
        from .official.endpoints import ENDPOINTS
    else:
        from .data import ENDPOINTS
    return ENDPOINTS
