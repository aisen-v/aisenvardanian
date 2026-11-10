"""Client for the official Garmin Health and Activity APIs.

How Garmin delivers data: when your watch syncs, Garmin sends each new summary
to the webhook URLs configured for your app (push), or sends a notification
with a callback URL to fetch it from (ping). Summaries can also be pulled by
*upload* time (when the watch synced, not the day the data is about), at most
24 hours per request, and older history can be requested with a backfill,
which Garmin then delivers through the webhooks.

The base URL can be overridden with GARMIN_API_BASE.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from . import oauth

log = logging.getLogger("garmin_connector.official")

API_BASE = os.getenv("GARMIN_API_BASE", "https://apis.garmin.com").rstrip("/")
REST = "/wellness-api/rest"
TIMEOUT = 60
DAY = 86400
MAX_PULL_WINDOW = DAY  # per request, by upload time
MAX_BACKFILL_WINDOW = 90 * DAY  # per request, by summary time


@dataclass(frozen=True)
class SummaryType:
    name: str  # name used in this connector
    path: str  # REST path segment for pull / backfill
    push_key: str  # key in push / ping payloads
    daily: bool  # one record per calendar day (keep the latest)


SUMMARY_TYPES: dict[str, SummaryType] = {
    t.name: t
    for t in [
        # Health API
        SummaryType("dailies", "dailies", "dailies", True),
        SummaryType("epochs", "epochs", "epochs", False),
        SummaryType("sleeps", "sleeps", "sleeps", True),
        SummaryType("body_comps", "bodyComps", "bodyComps", False),
        SummaryType("stress", "stressDetails", "stressDetails", True),
        SummaryType("user_metrics", "userMetrics", "userMetrics", True),
        SummaryType("pulse_ox", "pulseOx", "pulseox", True),
        SummaryType("respiration", "respiration", "allDayRespiration", True),
        SummaryType("hrv", "hrv", "hrv", True),
        SummaryType("blood_pressure", "bloodPressures", "bloodPressures", False),
        SummaryType("skin_temp", "skinTemp", "skinTemp", True),
        SummaryType("health_snapshot", "healthSnapshot", "healthSnapshot", False),
        # Activity API
        SummaryType("activities", "activities", "activities", False),
        SummaryType("activity_details", "activityDetails", "activityDetails", False),
        SummaryType("manual_activities", "manuallyUpdatedActivities", "manuallyUpdatedActivities", False),
        SummaryType("move_iq", "moveiq", "moveIQActivities", False),
    ]
}
BY_PUSH_KEY = {t.push_key.lower(): t for t in SUMMARY_TYPES.values()}


class GarminAPIError(RuntimeError):
    def __init__(self, status: int, body: str, url: str):
        self.status = status
        hint = {
            401: " (the sign-in is no longer valid: run `garmin-connector login`)",
            403: " (this data type may not be enabled for your app, or you didn't grant it)",
            429: " (rate limited by Garmin: try again later)",
        }.get(status, "")
        super().__init__(f"Garmin API {status} for {url}{hint}: {body[:300]}")


class OfficialClient:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()

    def _request(self, method: str, url: str, params: dict | None = None) -> requests.Response:
        if not url.startswith("http"):
            url = f"{API_BASE}{REST}{url}"
        for attempt in (1, 2):
            token = oauth.access_token(force_refresh=attempt == 2)
            resp = self.session.request(
                method,
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=TIMEOUT,
            )
            if resp.status_code != 401:
                break
        if resp.status_code >= 400:
            raise GarminAPIError(resp.status_code, resp.text, url.split("?")[0])
        return resp

    def get(self, url: str, params: dict | None = None) -> Any:
        resp = self._request("GET", url, params)
        return resp.json() if resp.content else None

    # ------------------------------------------------------------ user

    def user_id(self) -> str:
        return str(self.get("/user/id")["userId"])

    def permissions(self) -> list[str]:
        return self.get("/user/permissions") or []

    def deregister(self) -> None:
        """Revoke this app's access to your account at Garmin."""
        self._request("DELETE", "/user/registration")

    # ------------------------------------------------------------ data

    def pull(self, kind: str, upload_start: int, upload_end: int) -> list[dict]:
        """Summaries of one type uploaded between two Unix times."""
        t = SUMMARY_TYPES[kind]
        out: list[dict] = []
        start = upload_start
        while start < upload_end:
            end = min(start + MAX_PULL_WINDOW, upload_end)
            out.extend(
                self.get(
                    f"/{t.path}",
                    {"uploadStartTimeInSeconds": start, "uploadEndTimeInSeconds": end},
                )
                or []
            )
            start = end
        return out

    def backfill(self, kind: str, start: int, end: int) -> int:
        """Ask Garmin to (re)send history for a period; it arrives via the
        webhooks. Returns the number of requests accepted."""
        t = SUMMARY_TYPES[kind]
        accepted = 0
        while start < end:
            chunk_end = min(start + MAX_BACKFILL_WINDOW, end)
            try:
                self._request(
                    "GET",
                    f"/backfill/{t.path}",
                    {"summaryStartTimeInSeconds": start, "summaryEndTimeInSeconds": chunk_end},
                )
                accepted += 1
            except GarminAPIError as e:
                if e.status != 409:  # 409: this period was already requested
                    raise
                log.info("backfill %s %s-%s already requested", kind, start, chunk_end)
            start = chunk_end
        return accepted


def now() -> int:
    return int(time.time())
