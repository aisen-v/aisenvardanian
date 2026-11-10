"""The Garmin data this connector exposes.

Each public function here is one read-only endpoint. The CLI, the JSON API and
the MCP server are all generated from this list (``ENDPOINTS``), so adding a
function here makes it available everywhere. Parameters must be ``str`` or
``int`` with defaults where optional; the docstring's first line is used as
the description.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Callable

from .auth import get_client


def _day(value: str) -> str:
    """Accept 'today', 'yesterday', 'N' / '-N' (days ago) or YYYY-MM-DD."""
    v = (value or "today").strip().lower()
    today = dt.date.today()
    if v == "today":
        return today.isoformat()
    if v == "yesterday":
        return (today - dt.timedelta(days=1)).isoformat()
    if v.lstrip("-").isdigit():
        return (today - dt.timedelta(days=abs(int(v)))).isoformat()
    try:
        return dt.date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError(
            f"Invalid date {value!r}: use YYYY-MM-DD, 'today', 'yesterday' or a number of days ago"
        ) from None


def _range(start: str, end: str) -> tuple[str, str]:
    s, e = _day(start), _day(end)
    if s > e:
        raise ValueError(f"start ({s}) is after end ({e})")
    return s, e


# ---------------------------------------------------------------- account


def profile() -> dict[str, Any]:
    """Your name, unit system and profile settings."""
    g = get_client()
    return {
        "full_name": g.get_full_name(),
        "unit_system": g.get_unit_system(),
        "settings": g.get_userprofile_settings(),
    }


def devices() -> list[Any]:
    """Your registered Garmin devices."""
    return get_client().get_devices()


# ---------------------------------------------------------------- daily health


def daily_summary(date: str = "today") -> dict[str, Any]:
    """Daily totals for one day: steps, calories, distance, floors, intensity minutes, resting HR, stress, body battery."""
    return get_client().get_user_summary(_day(date))


def sleep(date: str = "today") -> dict[str, Any]:
    """Sleep for the night ending on this date: stages, score, timing, SpO2, respiration."""
    return get_client().get_sleep_data(_day(date))


def heart_rate(date: str = "today") -> dict[str, Any]:
    """Heart rate through the day (resting, min, max and timeline)."""
    return get_client().get_heart_rates(_day(date))


def hrv(date: str = "today") -> dict[str, Any]:
    """Overnight heart rate variability (HRV) summary and status."""
    return get_client().get_hrv_data(_day(date)) or {}


def stress(date: str = "today") -> dict[str, Any]:
    """Stress levels through the day."""
    return get_client().get_stress_data(_day(date))


def body_battery(start: str = "today", end: str = "today") -> list[Any]:
    """Body Battery charged/drained and timeline, per day in a date range."""
    s, e = _range(start, end)
    return get_client().get_body_battery(s, e)


def respiration(date: str = "today") -> dict[str, Any]:
    """Breathing rate through the day and night."""
    return get_client().get_respiration_data(_day(date))


def spo2(date: str = "today") -> dict[str, Any]:
    """Blood oxygen (pulse ox) readings for the day."""
    return get_client().get_spo2_data(_day(date))


def steps(start: str = "-6", end: str = "today") -> list[Any]:
    """Total steps and step goal per day in a date range (default: last 7 days)."""
    s, e = _range(start, end)
    return get_client().get_daily_steps(s, e)


def body_composition(start: str = "-30", end: str = "today") -> dict[str, Any]:
    """Weight, BMI, body fat and other body composition in a date range (default: last 30 days)."""
    s, e = _range(start, end)
    return get_client().get_body_composition(s, e)


# ---------------------------------------------------------------- training


def training_readiness(date: str = "today") -> Any:
    """Training readiness score and its contributing factors."""
    return get_client().get_training_readiness(_day(date))


def training_status(date: str = "today") -> dict[str, Any]:
    """Training status, load and load focus."""
    return get_client().get_training_status(_day(date))


def max_metrics(date: str = "today") -> Any:
    """VO2 max and fitness age estimates."""
    return get_client().get_max_metrics(_day(date))


def race_predictions() -> dict[str, Any]:
    """Predicted 5K, 10K, half marathon and marathon times."""
    return get_client().get_race_predictions()


def personal_records() -> Any:
    """Your personal records (fastest times, longest distances, ...)."""
    return get_client().get_personal_record()


# ---------------------------------------------------------------- activities


def activities(limit: int = 20, start: int = 0, activity_type: str = "") -> Any:
    """Recent activities, newest first. activity_type filters, e.g. running, cycling, swimming."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if start < 0:
        raise ValueError("start must be 0 or more")
    return get_client().get_activities(start, limit, activity_type or None)


def activities_by_date(start: str = "-6", end: str = "today", activity_type: str = "") -> list[Any]:
    """Activities between two dates (default: last 7 days), optionally filtered by type."""
    s, e = _range(start, end)
    return get_client().get_activities_by_date(s, e, activity_type or None)


def activity(activity_id: int) -> dict[str, Any]:
    """Full summary of one activity: distance, duration, pace, HR, power, training effect."""
    return get_client().get_activity(str(activity_id))


def activity_splits(activity_id: int) -> dict[str, Any]:
    """Laps / splits of one activity."""
    return get_client().get_activity_splits(str(activity_id))


ENDPOINTS: dict[str, Callable[..., Any]] = {
    f.__name__: f
    for f in [
        profile,
        devices,
        daily_summary,
        sleep,
        heart_rate,
        hrv,
        stress,
        body_battery,
        respiration,
        spo2,
        steps,
        body_composition,
        training_readiness,
        training_status,
        max_metrics,
        race_predictions,
        personal_records,
        activities,
        activities_by_date,
        activity,
        activity_splits,
    ]
}

DOWNLOAD_FORMATS = ("fit", "tcx", "gpx", "kml", "csv")


def download_activity(activity_id: int, fmt: str = "fit") -> tuple[bytes, str]:
    """Download an activity file. Returns (bytes, filename).

    'fit' returns Garmin's original upload as a .zip containing the .fit file.
    """
    from garminconnect import Garmin

    fmt = fmt.lower()
    if fmt not in DOWNLOAD_FORMATS:
        raise ValueError(f"format must be one of {', '.join(DOWNLOAD_FORMATS)}")
    kind = Garmin.ActivityDownloadFormat["ORIGINAL" if fmt == "fit" else fmt.upper()]
    data = get_client().download_activity(str(activity_id), dl_fmt=kind)
    ext = "zip" if fmt == "fit" else fmt
    return data, f"activity_{activity_id}.{ext}"
