"""Endpoints for the official API backend, plus webhook and sync handling.

The data endpoints read from the local store (``store.py``), which Garmin fills
through your webhooks (push / ping), ``sync`` (pull of recent uploads) and
``backfill``. Same conventions as ``data.py``: the CLI, JSON API and MCP tools
are generated from ``ENDPOINTS``.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse
from typing import Any, Callable

from ..data import _day, _range
from . import oauth
from .api import API_BASE, BY_PUSH_KEY, DAY, SUMMARY_TYPES, OfficialClient, now
from .store import get_store

log = logging.getLogger("garmin_connector.official")

_client: OfficialClient | None = None


def get_client() -> OfficialClient:
    global _client
    if _client is None:
        _client = OfficialClient()
    return _client


def _daily(kind: str, date: str) -> dict[str, Any]:
    day = _day(date)
    found = get_store().query(kind, day, day, latest_per_day=True)
    if not found:
        return {"date": day, "data": None, "note": _empty_note(kind)}
    return found[-1]


def _ranged(kind: str, start: str, end: str) -> list[dict[str, Any]] | dict[str, Any]:
    s, e = _range(start, end)
    found = get_store().query(kind, s, e, latest_per_day=SUMMARY_TYPES[kind].daily)
    if not found:
        return {"start": s, "end": e, "data": [], "note": _empty_note(kind)}
    return found


def _empty_note(kind: str) -> str:
    return (
        f"No {kind} data stored for this period. Garmin delivers data after the "
        "watch syncs: run the `sync` tool for the last few days, or `garmin-connector "
        "backfill` for older history. It's also empty if your app doesn't have this "
        "data type enabled."
    )


# ---------------------------------------------------------------- endpoints


def profile() -> dict[str, Any]:
    """Your Garmin user ID, the permissions you granted, and what data is stored locally."""
    c = get_client()
    return {"user_id": c.user_id(), "permissions": c.permissions(), "stored": get_store().stats()}


def daily_summary(date: str = "today") -> dict[str, Any]:
    """Daily totals for one day: steps, distance, calories, floors, intensity minutes, resting/min/max HR, stress, Body Battery."""
    return _daily("dailies", date)


def sleep(date: str = "today") -> dict[str, Any]:
    """Sleep for the night ending on this date: stages, score, timing, SpO2, respiration."""
    return _daily("sleeps", date)


def stress(date: str = "today") -> dict[str, Any]:
    """Stress levels and Body Battery through the day."""
    return _daily("stress", date)


def hrv(date: str = "today") -> dict[str, Any]:
    """Overnight heart rate variability (HRV)."""
    return _daily("hrv", date)


def respiration(date: str = "today") -> dict[str, Any]:
    """Breathing rate through the day and night."""
    return _daily("respiration", date)


def spo2(date: str = "today") -> dict[str, Any]:
    """Blood oxygen (pulse ox) readings for the day."""
    return _daily("pulse_ox", date)


def user_metrics(start: str = "-30", end: str = "today") -> Any:
    """VO2 max and fitness age per day in a date range (default: last 30 days)."""
    return _ranged("user_metrics", start, end)


def body_composition(start: str = "-30", end: str = "today") -> Any:
    """Weight, BMI, body fat and other body composition in a date range (default: last 30 days)."""
    return _ranged("body_comps", start, end)


def daily_summaries(start: str = "-6", end: str = "today") -> Any:
    """Daily totals for each day in a date range (default: last 7 days)."""
    return _ranged("dailies", start, end)


def activities(start: str = "-6", end: str = "today", activity_type: str = "") -> Any:
    """Activities between two dates (default: last 7 days). activity_type filters, e.g. RUNNING, CYCLING."""
    found = _ranged("activities", start, end)
    if activity_type and isinstance(found, list):
        want = activity_type.upper()
        found = [a for a in found if str(a.get("activityType", "")).upper() == want]
    return found


def activity_details(activity_id: int) -> dict[str, Any]:
    """Full detail of one activity: summary plus samples (HR, pace, GPS, power) and laps."""
    found = get_store().find("activity_details", "activityId", str(activity_id))
    if not found:
        summary = get_store().find("activities", "activityId", str(activity_id))
        return {
            "activity_id": activity_id,
            "summary": summary[-1] if summary else None,
            "note": "No detail stored for this activity (Garmin sends it with the activity "
            "when the activity details data type is enabled for your app).",
        }
    return found[-1]


def summaries(kind: str, start: str = "-6", end: str = "today") -> Any:
    """Any stored summary type for a date range. kind: dailies, epochs, sleeps, body_comps, stress, user_metrics, pulse_ox, respiration, hrv, blood_pressure, skin_temp, health_snapshot, activities, activity_details, manual_activities, move_iq."""
    if kind not in SUMMARY_TYPES:
        raise ValueError(f"kind must be one of: {', '.join(SUMMARY_TYPES)}")
    return _ranged(kind, start, end)


def sync(days: int = 2) -> dict[str, Any]:
    """Pull everything your watch uploaded in the last N days (1-7) from Garmin into the local store."""
    if not 1 <= days <= 7:
        raise ValueError("days must be between 1 and 7 (use backfill for older history)")
    c = get_client()
    end = now()
    start = end - days * DAY
    counts: dict[str, Any] = {}
    for kind in SUMMARY_TYPES:
        try:
            counts[kind] = get_store().add(kind, c.pull(kind, start, end))
        except Exception as e:  # one disabled data type shouldn't stop the rest
            counts[kind] = f"skipped: {e}"
    return {"pulled_days": days, "stored": counts}


ENDPOINTS: dict[str, Callable[..., Any]] = {
    f.__name__: f
    for f in [
        profile,
        daily_summary,
        daily_summaries,
        sleep,
        stress,
        hrv,
        respiration,
        spo2,
        user_metrics,
        body_composition,
        activities,
        activity_details,
        summaries,
        sync,
    ]
}


# ---------------------------------------------------------------- history & webhooks


def backfill(days: int = 30, kinds: list[str] | None = None) -> dict[str, Any]:
    """Ask Garmin to send the last N days of history; it arrives via the webhooks."""
    if days < 1:
        raise ValueError("days must be at least 1")
    c = get_client()
    end = now()
    start = end - days * DAY
    result: dict[str, Any] = {}
    for kind in kinds or list(SUMMARY_TYPES):
        if kind not in SUMMARY_TYPES:
            raise ValueError(f"unknown summary type {kind!r}")
        try:
            result[kind] = f"requested ({c.backfill(kind, start, end)} request(s))"
        except Exception as e:
            result[kind] = f"skipped: {e}"
    return result


def handle_notification(payload: dict[str, Any]) -> dict[str, int]:
    """Store a push or ping notification from Garmin.

    Push items are the summaries themselves; ping items carry a ``callbackURL``
    to fetch them from. Items for other Garmin users are ignored.
    """
    store = get_store()
    me = (oauth.load_tokens() or {}).get("user_id")
    counts: dict[str, int] = {}
    for key, items in payload.items():
        if not isinstance(items, list):
            continue
        t = BY_PUSH_KEY.get(key.lower())
        if t is None:
            # deregistrations, userPermissionsChange and anything new
            store.add_event(key, items)
            if key == "deregistrations" and any(str(i.get("userId")) == me for i in items):
                log.warning("Garmin reports this app was disconnected from your account")
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if me and item.get("userId") is not None and str(item["userId"]) != me:
                log.warning("ignoring %s for another Garmin user", key)
                continue
            if "callbackURL" in item:
                url = str(item["callbackURL"])
                # Only ever send your access token to Garmin's API host.
                if urlparse(url).scheme != "https" or urlparse(url).netloc != urlparse(API_BASE).netloc:
                    log.warning("ignoring ping with callback outside %s", API_BASE)
                    continue
                summaries = get_client().get(url) or []
            else:
                summaries = [item]
            counts[t.name] = counts.get(t.name, 0) + store.add(t.name, summaries)
    return counts
