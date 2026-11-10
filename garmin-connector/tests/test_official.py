"""Official API backend, tested against fake Garmin responses (no network)."""

import base64
import datetime as dt
import hashlib
import json
import time
import urllib.parse

import pytest
from starlette.testclient import TestClient

from garmin_connector import backend, cli, server
from garmin_connector.official import api, endpoints, oauth, store

TOKEN = "connector-token"
DAY = 86400


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        return self._body


class FakeSession:
    """Answers Garmin API requests from a routing table."""

    def __init__(self, routes):
        self.routes = routes  # path suffix -> callable(params, headers) -> FakeResponse
        self.calls = []

    def request(self, method, url, params=None, headers=None, timeout=None):
        self.calls.append((method, url, dict(params or {}), dict(headers or {})))
        for suffix, handler in self.routes.items():
            if url.split("?")[0].endswith(suffix):
                return handler(params or {}, headers or {})
        return FakeResponse(404, {"error": "not found"})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GARMINTOKENS", str(tmp_path))
    monkeypatch.setenv("GARMIN_CLIENT_ID", "client-id")
    monkeypatch.setenv("GARMIN_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("GARMIN_BACKEND", raising=False)
    monkeypatch.setattr(store, "_store", store.Store(str(tmp_path / "data.sqlite3")))
    monkeypatch.setattr(endpoints, "_client", None)
    oauth._save({
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_at": int(time.time()) + 3600,
        "user_id": "user-1",
    })
    return tmp_path


def use_session(monkeypatch, routes):
    s = FakeSession(routes)
    monkeypatch.setattr(endpoints, "_client", api.OfficialClient(session=s))
    return s


# ---------------------------------------------------------------- backend choice


def test_backend_choice(monkeypatch):
    monkeypatch.delenv("GARMIN_BACKEND", raising=False)
    monkeypatch.delenv("GARMIN_CLIENT_ID", raising=False)
    assert backend.name() == "unofficial"
    monkeypatch.setenv("GARMIN_CLIENT_ID", "x")
    assert backend.name() == "official"
    monkeypatch.setenv("GARMIN_BACKEND", "unofficial")
    assert backend.name() == "unofficial"
    monkeypatch.setenv("GARMIN_BACKEND", "nonsense")
    with pytest.raises(ValueError):
        backend.name()


# ---------------------------------------------------------------- OAuth


def test_pkce_and_authorization_url():
    verifier, challenge = oauth.make_pkce()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expected.decode()
    url = oauth.authorization_url("cid", challenge, "st", "http://localhost:8765/oauth/callback")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert q == {
        "response_type": "code",
        "client_id": "cid",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "redirect_uri": "http://localhost:8765/oauth/callback",
        "state": "st",
    }


def test_paste_login_flow(env, monkeypatch):
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/garmin/callback")
    posted = {}

    def fake_post(url, data, headers, timeout):
        posted.update(data)
        return FakeResponse(200, {"access_token": "A", "refresh_token": "R", "expires_in": 86400,
                                  "refresh_token_expires_in": 7776000})

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    shown = []

    def ask(prompt):
        url = shown[0].split()[-1]
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["state"]
        return f"https://example.com/garmin/callback?code=THE-CODE&state={state}"

    tokens = oauth.interactive_login(output=shown.append, ask=ask, open_browser=False)
    assert tokens["access_token"] == "A"
    assert posted["grant_type"] == "authorization_code"
    assert posted["code"] == "THE-CODE"
    assert posted["client_id"] == "client-id" and posted["client_secret"] == "client-secret"
    assert len(posted["code_verifier"]) >= 43
    assert oauth.load_tokens()["refresh_token"] == "R"
    assert (oauth.tokens_path().stat().st_mode & 0o777) == 0o600


def test_login_rejects_wrong_state(env, monkeypatch):
    monkeypatch.setenv("GARMIN_REDIRECT_URI", "https://example.com/cb")
    with pytest.raises(oauth.OAuthError, match="state"):
        oauth.interactive_login(output=lambda s: None, open_browser=False,
                                ask=lambda p: "https://example.com/cb?code=x&state=forged")


def test_expired_token_is_refreshed(env, monkeypatch):
    oauth._save({"access_token": "old", "refresh_token": "R1", "expires_at": 0, "user_id": "user-1"})
    posted = {}

    def fake_post(url, data, headers, timeout):
        posted.update(data)
        return FakeResponse(200, {"access_token": "new", "refresh_token": "R2", "expires_in": 86400})

    monkeypatch.setattr(oauth.requests, "post", fake_post)
    assert oauth.access_token() == "new"
    assert posted["grant_type"] == "refresh_token" and posted["refresh_token"] == "R1"
    saved = oauth.load_tokens()
    assert saved["refresh_token"] == "R2" and saved["user_id"] == "user-1"


def test_not_signed_in(env):
    oauth.forget_tokens()
    with pytest.raises(oauth.NotSignedIn):
        oauth.access_token()


# ---------------------------------------------------------------- API client


def test_pull_splits_into_24h_windows(env, monkeypatch):
    s = use_session(monkeypatch, {"/dailies": lambda p, h: FakeResponse(200, [{"summaryId": str(p["uploadStartTimeInSeconds"])}])})
    out = endpoints.get_client().pull("dailies", 1000, 1000 + 2 * DAY + 5)
    assert len(out) == 3
    windows = [(c[2]["uploadStartTimeInSeconds"], c[2]["uploadEndTimeInSeconds"]) for c in s.calls]
    assert windows == [(1000, 1000 + DAY), (1000 + DAY, 1000 + 2 * DAY), (1000 + 2 * DAY, 1000 + 2 * DAY + 5)]
    assert s.calls[0][3]["Authorization"] == "Bearer access-1"
    assert s.calls[0][1] == "https://apis.garmin.com/wellness-api/rest/dailies"


def test_401_refreshes_once(env, monkeypatch):
    monkeypatch.setattr(oauth.requests, "post", lambda *a, **k: FakeResponse(
        200, {"access_token": "access-2", "refresh_token": "r2", "expires_in": 86400}))
    use_session(monkeypatch, {"/user/id": lambda p, h: FakeResponse(200, {"userId": "user-1"})
                              if h["Authorization"] == "Bearer access-2" else FakeResponse(401, {})})
    assert endpoints.get_client().user_id() == "user-1"


def test_backfill_chunks_and_tolerates_duplicates(env, monkeypatch):
    s = use_session(monkeypatch, {
        "/backfill/dailies": lambda p, h: FakeResponse(202),
        "/backfill/sleeps": lambda p, h: FakeResponse(409, {"error": "duplicate"}),
    })
    result = endpoints.backfill(120, ["dailies", "sleeps"])
    assert result["dailies"] == "requested (2 request(s))"
    assert result["sleeps"] == "requested (0 request(s))"
    spans = [c[2]["summaryEndTimeInSeconds"] - c[2]["summaryStartTimeInSeconds"]
             for c in s.calls if c[1].endswith("/backfill/dailies")]
    assert spans == [90 * DAY, 30 * DAY]


def test_api_error_explains_403(env, monkeypatch):
    use_session(monkeypatch, {"/hrv": lambda p, h: FakeResponse(403, {"error": "no"})})
    with pytest.raises(api.GarminAPIError, match="not be enabled"):
        endpoints.get_client().pull("hrv", 0, 10)


# ---------------------------------------------------------------- store & endpoints


def test_daily_keeps_latest_version(env):
    st = store.get_store()
    st.add("dailies", [{"summaryId": "a", "calendarDate": "2026-11-09", "steps": 100}])
    st.add("dailies", [{"summaryId": "b", "calendarDate": "2026-11-09", "steps": 9000}])
    st.add("dailies", [{"summaryId": "c", "calendarDate": "2026-11-08", "steps": 5}])
    assert endpoints.daily_summary("2026-11-09")["steps"] == 9000
    assert [d["steps"] for d in endpoints.daily_summaries("2026-11-08", "2026-11-09")] == [5, 9000]
    empty = endpoints.sleep("2026-11-09")
    assert empty["data"] is None and "sync" in empty["note"]


def test_activities_by_local_day_and_type(env):
    # 23:30 UTC on Nov 9 is Nov 10 at UTC+1
    ts = int(dt.datetime(2026, 11, 9, 23, 30, tzinfo=dt.timezone.utc).timestamp())
    store.get_store().add("activities", [
        {"summaryId": "1", "activityId": 11, "activityType": "RUNNING",
         "startTimeInSeconds": ts, "startTimeOffsetInSeconds": 3600},
        {"summaryId": "2", "activityId": 12, "activityType": "CYCLING",
         "startTimeInSeconds": ts, "startTimeOffsetInSeconds": 3600},
    ])
    assert len(endpoints.activities("2026-11-10", "2026-11-10")) == 2
    runs = endpoints.activities("2026-11-10", "2026-11-10", "running")
    assert [a["activityId"] for a in runs] == [11]
    assert endpoints.activities("2026-11-09", "2026-11-09")["data"] == []
    assert endpoints.activity_details(11)["summary"]["activityId"] == 11


def test_summaries_validates_kind(env):
    with pytest.raises(ValueError):
        endpoints.summaries("everything")


def test_sync_pulls_all_types_and_skips_failures(env, monkeypatch):
    def handler(p, h):
        return FakeResponse(200, [{"summaryId": f"s{p['uploadStartTimeInSeconds']}", "calendarDate": "2026-11-09"}])

    use_session(monkeypatch, {"/dailies": handler, "/sleeps": lambda p, h: FakeResponse(403, {})})
    result = endpoints.sync(days=1)["stored"]
    assert result["dailies"] == 1
    assert result["sleeps"].startswith("skipped")
    with pytest.raises(ValueError):
        endpoints.sync(days=30)


# ---------------------------------------------------------------- webhooks


def test_push_and_ping(env, monkeypatch):
    s = use_session(monkeypatch, {"/sleeps": lambda p, h: FakeResponse(200, [
        {"summaryId": "sl1", "userId": "user-1", "calendarDate": "2026-11-09", "durationInSeconds": 28000}])})
    counts = endpoints.handle_notification({
        "dailies": [
            {"summaryId": "d1", "userId": "user-1", "calendarDate": "2026-11-09", "steps": 1},
            {"summaryId": "x", "userId": "someone-else", "calendarDate": "2026-11-09", "steps": 2},
        ],
        "sleeps": [{"userId": "user-1",
                    "callbackURL": "https://apis.garmin.com/wellness-api/rest/sleeps?uploadStartTimeInSeconds=1&uploadEndTimeInSeconds=2"}],
        "deregistrations": [{"userId": "user-1"}],
    })
    assert counts == {"dailies": 1, "sleeps": 1}
    assert endpoints.daily_summary("2026-11-09")["steps"] == 1
    assert endpoints.sleep("2026-11-09")["durationInSeconds"] == 28000
    assert s.calls[0][3]["Authorization"] == "Bearer access-1"


def test_ping_never_sends_token_elsewhere(env, monkeypatch):
    s = use_session(monkeypatch, {})
    counts = endpoints.handle_notification({"dailies": [
        {"userId": "user-1", "callbackURL": "https://evil.example.com/steal"},
        {"userId": "user-1", "callbackURL": "http://apis.garmin.com/wellness-api/rest/dailies"},
    ]})
    assert counts == {} and s.calls == []


@pytest.fixture
def http(env):
    with TestClient(server.build_http_app(TOKEN), base_url="http://localhost:8765") as c:
        yield c


def test_webhook_route(http):
    body = {"dailies": [{"summaryId": "w1", "userId": "user-1", "calendarDate": "2026-11-07", "steps": 42}]}
    assert http.post("/garmin/webhook", json=body).status_code == 401  # token required
    r = http.post(f"/garmin/webhook?token={TOKEN}", json=body)
    assert r.status_code == 200
    r = http.get(f"/api/daily_summary?date=2026-11-07&token={TOKEN}")
    assert r.json()["steps"] == 42
    assert http.post(f"/garmin/webhook?token={TOKEN}", content=b"nope").status_code == 400


def test_api_and_mcp_use_official_endpoints(http):
    eps = http.get(f"/api?token={TOKEN}").json()
    assert eps["backend"] == "official"
    assert set(eps["endpoints"]) == {f"/api/{n}" for n in endpoints.ENDPOINTS}
    assert http.get(f"/api/activity/1/download?token={TOKEN}").status_code == 404

    hdrs = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}
    r = http.post("/mcp", headers=hdrs, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == set(endpoints.ENDPOINTS)


# ---------------------------------------------------------------- CLI


def test_cli_status_and_query(env, monkeypatch, capsys):
    use_session(monkeypatch, {
        "/user/id": lambda p, h: FakeResponse(200, {"userId": "user-1"}),
        "/user/permissions": lambda p, h: FakeResponse(200, ["ACTIVITY_EXPORT", "HEALTH_EXPORT"]),
    })
    store.get_store().add("hrv", [{"summaryId": "h", "calendarDate": "2026-11-09", "lastNightAvg": 48}])
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "official" in out and "HEALTH_EXPORT" in out and "hrv" in out
    assert cli.main(["hrv", "--date", "2026-11-09", "--compact"]) == 0
    assert json.loads(capsys.readouterr().out)["lastNightAvg"] == 48
    assert cli.main(["download", "1"]) == 1
