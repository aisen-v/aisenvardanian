"""Tests run against a fake Garmin client, so no account or network is needed."""

import datetime as dt
import json

import pytest
from starlette.testclient import TestClient

from garmin_connector import cli, data, server

TOKEN = "s3cret-token"


class FakeGarmin:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return {"method": name, "args": list(args)}

        return method

    def download_activity(self, activity_id, dl_fmt):
        self.calls.append(("download_activity", (activity_id,), {"dl_fmt": dl_fmt}))
        return b"FILE"


@pytest.fixture
def fake(monkeypatch):
    g = FakeGarmin()
    monkeypatch.setattr(data, "get_client", lambda: g)
    return g


# ---------------------------------------------------------------- dates


def test_day_parsing():
    today = dt.date.today()
    assert data._day("today") == today.isoformat()
    assert data._day("yesterday") == (today - dt.timedelta(days=1)).isoformat()
    assert data._day("7") == (today - dt.timedelta(days=7)).isoformat()
    assert data._day("-7") == (today - dt.timedelta(days=7)).isoformat()
    assert data._day("2026-03-04") == "2026-03-04"
    with pytest.raises(ValueError):
        data._day("March 4")
    with pytest.raises(ValueError):
        data._range("2026-03-05", "2026-03-04")


def test_endpoints_call_garmin(fake):
    assert data.sleep("2026-01-02") == {"method": "get_sleep_data", "args": ["2026-01-02"]}
    data.activities(limit=5, activity_type="running")
    assert fake.calls[-1] == ("get_activities", (0, 5, "running"), {})
    data.activities_by_date("2026-01-01", "2026-01-07")
    assert fake.calls[-1] == ("get_activities_by_date", ("2026-01-01", "2026-01-07", None), {})
    with pytest.raises(ValueError):
        data.activities(limit=1000)


def test_download_formats(fake):
    blob, name = data.download_activity(42, "fit")
    assert blob == b"FILE" and name == "activity_42.zip"
    assert fake.calls[-1][2]["dl_fmt"].name == "ORIGINAL"
    _, name = data.download_activity(42, "GPX")
    assert name == "activity_42.gpx"
    with pytest.raises(ValueError):
        data.download_activity(42, "exe")


# ---------------------------------------------------------------- HTTP


@pytest.fixture
def http(fake):
    with TestClient(server.build_http_app(TOKEN), base_url="http://localhost:8765") as c:
        yield c


def auth(**extra):
    return {"Authorization": f"Bearer {TOKEN}", **extra}


def test_token_required(http):
    assert http.get("/health").status_code == 200
    assert http.get("/api").status_code == 401
    assert http.get("/api", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert http.get("/api", headers=auth()).status_code == 200
    assert http.get(f"/api?token={TOKEN}").status_code == 200


def test_api_index_lists_all_endpoints(http):
    eps = http.get("/api", headers=auth()).json()["endpoints"]
    for name in data.ENDPOINTS:
        assert f"/api/{name}" in eps
    assert eps["/api/sleep"]["params"]["date"]["default"] == "today"


def test_api_endpoint(http, fake):
    r = http.get("/api/sleep?date=2026-01-02", headers=auth())
    assert r.status_code == 200
    assert r.json() == {"method": "get_sleep_data", "args": ["2026-01-02"]}

    r = http.get("/api/activities?limit=3", headers=auth())
    assert r.status_code == 200 and fake.calls[-1][1] == (0, 3, None)

    assert http.get("/api/activities?limit=x", headers=auth()).status_code == 400
    assert http.get("/api/sleep?date=bad", headers=auth()).status_code == 400
    assert http.get("/api/sleep?colour=red", headers=auth()).status_code == 400
    assert http.get("/api/activity", headers=auth()).status_code == 400  # missing id
    assert http.get("/api/nope", headers=auth()).status_code == 404


def test_api_download(http):
    r = http.get("/api/activity/42/download?format=gpx", headers=auth())
    assert r.status_code == 200 and r.content == b"FILE"
    assert "activity_42.gpx" in r.headers["content-disposition"]


def test_garmin_errors_become_502(http, fake, monkeypatch):
    def boom(*a):
        raise RuntimeError("Garmin is down")

    monkeypatch.setattr(fake, "get_sleep_data", boom, raising=False)
    r = http.get("/api/sleep", headers=auth())
    assert r.status_code == 502 and "Garmin is down" in r.json()["error"]


# ---------------------------------------------------------------- MCP


def rpc(http, method, params=None, id=1):
    r = http.post(
        "/mcp",
        headers=auth(Accept="application/json, text/event-stream"),
        json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_mcp_lists_and_calls_tools(http):
    rpc(http, "initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    })
    tools = {t["name"]: t for t in rpc(http, "tools/list")["result"]["tools"]}
    assert set(tools) == set(data.ENDPOINTS)
    assert tools["sleep"]["annotations"]["readOnlyHint"] is True
    assert "date" in tools["sleep"]["inputSchema"]["properties"]
    assert tools["activity"]["inputSchema"]["required"] == ["activity_id"]

    res = rpc(http, "tools/call", {"name": "hrv", "arguments": {"date": "2026-02-03"}})["result"]
    assert not res.get("isError")
    assert json.loads(res["content"][0]["text"]) == {"method": "get_hrv_data", "args": ["2026-02-03"]}


def test_mcp_requires_token(fake):
    with TestClient(server.build_http_app(TOKEN), base_url="http://localhost:8765") as c:
        assert c.post("/mcp", json={}).status_code == 401


# ---------------------------------------------------------------- CLI


def test_cli_endpoint(fake, capsys):
    assert cli.main(["daily-summary", "--date", "2026-05-06", "--compact"]) == 0
    assert json.loads(capsys.readouterr().out) == {"method": "get_user_summary", "args": ["2026-05-06"]}
    assert cli.main(["activity", "123"]) == 0
    assert fake.calls[-1] == ("get_activity", ("123",), {})


def test_cli_bad_input(fake, capsys):
    assert cli.main(["sleep", "--date", "nonsense"]) == 1
    assert "Invalid date" in capsys.readouterr().err


def test_cli_download(fake, tmp_path, capsys):
    out = tmp_path / "a.gpx"
    assert cli.main(["download", "7", "--format", "gpx", "-o", str(out)]) == 0
    assert out.read_bytes() == b"FILE"


def test_allowed_host_for_tunnels(fake):
    app = lambda: server.build_http_app(TOKEN, allowed_hosts=["garmin.example.com"])
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "t", "version": "0"}}}
    hdrs = auth(Accept="application/json, text/event-stream")
    with TestClient(app(), base_url="https://garmin.example.com") as c:
        assert c.post("/mcp", headers=hdrs, json=init).status_code == 200
    with TestClient(app(), base_url="https://evil.example.net") as c:
        assert c.post("/mcp", headers=hdrs, json=init).status_code == 421


def test_mcp_errors_reach_the_model(http):
    res = rpc(http, "tools/call", {"name": "sleep", "arguments": {"date": "someday"}})["result"]
    assert res["isError"] and "Invalid date" in res["content"][0]["text"]
