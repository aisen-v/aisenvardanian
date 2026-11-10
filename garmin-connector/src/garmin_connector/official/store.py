"""Local SQLite store for summaries Garmin has delivered.

Everything the official API sends (push, ping, pull, backfill) lands here, and
the connector's endpoints read from it. Default location:
<token dir>/official_data.sqlite3, or GARMIN_DATA_DB.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from ..auth import token_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS summaries (
    kind        TEXT NOT NULL,
    id          TEXT NOT NULL,
    day         TEXT,             -- local calendar date, YYYY-MM-DD
    start_ts    INTEGER,          -- start / measurement time, Unix seconds
    user_id     TEXT,
    body        TEXT NOT NULL,    -- the summary as Garmin sent it
    received_at INTEGER NOT NULL,
    PRIMARY KEY (kind, id)
);
CREATE INDEX IF NOT EXISTS summaries_day ON summaries (kind, day);
CREATE TABLE IF NOT EXISTS events (
    received_at INTEGER NOT NULL,
    kind        TEXT NOT NULL,    -- deregistrations, userPermissionsChange, ...
    body        TEXT NOT NULL
);
"""


def db_path() -> str:
    return os.getenv("GARMIN_DATA_DB") or str(Path(token_dir()) / "official_data.sqlite3")


def _start_ts(s: dict[str, Any]) -> int | None:
    for key in ("startTimeInSeconds", "measurementTimeInSeconds", "summaryStartTimeInSeconds"):
        if isinstance(s.get(key), (int, float)):
            return int(s[key])
    return None


def summary_day(s: dict[str, Any]) -> str | None:
    """The local calendar day a summary is about."""
    if isinstance(s.get("calendarDate"), str):
        return s["calendarDate"][:10]
    ts = _start_ts(s)
    if ts is None:
        return None
    offset = 0
    for key in ("startTimeOffsetInSeconds", "measurementTimeOffsetInSeconds"):
        if isinstance(s.get(key), (int, float)):
            offset = int(s[key])
            break
    return dt.datetime.fromtimestamp(ts + offset, dt.timezone.utc).date().isoformat()


def summary_id(s: dict[str, Any]) -> str:
    for key in ("summaryId", "activityId"):
        if s.get(key) not in (None, ""):
            return str(s[key])
    return hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()[:32]


class Store:
    def __init__(self, path: str | None = None):
        self.path = path or db_path()
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
        if self.path != ":memory:":
            os.chmod(self.path, 0o600)

    def add(self, kind: str, summaries: Iterable[dict[str, Any]]) -> int:
        rows = [
            (
                kind,
                summary_id(s),
                summary_day(s),
                _start_ts(s),
                str(s["userId"]) if s.get("userId") is not None else None,
                json.dumps(s),
                time.time_ns(),
            )
            for s in summaries
            if isinstance(s, dict)
        ]
        with self._lock, self._db:
            self._db.executemany(
                "INSERT INTO summaries VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(kind, id) DO UPDATE SET day=excluded.day, start_ts=excluded.start_ts, "
                "user_id=excluded.user_id, body=excluded.body, received_at=excluded.received_at",
                rows,
            )
        return len(rows)

    def add_event(self, kind: str, body: Any) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO events VALUES (?,?,?)", (int(time.time()), kind, json.dumps(body))
            )

    def query(
        self, kind: str, start_day: str, end_day: str, latest_per_day: bool = False
    ) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT day, body FROM summaries WHERE kind=? AND day BETWEEN ? AND ? "
                "ORDER BY day, start_ts, received_at",
                (kind, start_day, end_day),
            ).fetchall()
        items = [(r["day"], json.loads(r["body"])) for r in rows]
        if latest_per_day:
            # Garmin resends a day's summary as more data syncs; the last one
            # received covers the most of the day.
            by_day: dict[str, dict] = {}
            for day, body in items:
                by_day[day] = body
            return list(by_day.values())
        return [body for _, body in items]

    def find(self, kind: str, field: str, value: str) -> list[dict[str, Any]]:
        if not field.isidentifier():
            raise ValueError(f"bad field name {field!r}")
        with self._lock:
            rows = self._db.execute(
                f"SELECT body FROM summaries WHERE kind=? AND CAST(json_extract(body, '$.{field}') AS TEXT)=?",
                (kind, str(value)),
            ).fetchall()
        return [json.loads(r["body"]) for r in rows]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self._db.execute(
                "SELECT kind, COUNT(*) n, MIN(day) first, MAX(day) last, MAX(received_at) latest "
                "FROM summaries GROUP BY kind ORDER BY kind"
            ).fetchall()
        return {
            r["kind"]: {
                "count": r["n"],
                "first_day": r["first"],
                "last_day": r["last"],
                "last_received": dt.datetime.fromtimestamp(r["latest"] / 1e9).isoformat(timespec="seconds"),
            }
            for r in rows
        }


_store: Store | None = None
_store_lock = threading.Lock()


def get_store() -> Store:
    global _store
    with _store_lock:
        if _store is None:
            _store = Store()
        return _store
