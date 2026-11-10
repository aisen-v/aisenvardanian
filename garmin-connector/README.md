# garmin-connector

A personal connector to your own Garmin Connect data. One sign-in gives you:

- **a CLI**: `garmin-connector sleep --date yesterday`
- **a JSON API**: `GET /api/sleep?date=yesterday`
- **an MCP server**, so Claude (Desktop, Claude Code, or claude.ai as a custom connector) can read your data

Everything is read-only.

> **Why not Garmin's official API?** Garmin's Health/Activity APIs are only for approved business partners. This uses the same sign-in as the Garmin Connect app, through the open-source [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library. It's unofficial: Garmin can change things and break it, and it's meant for your own account only. Don't poll it aggressively — Garmin rate-limits (HTTP 429).

## Setup

Needs Python 3.10+.

```bash
cd garmin-connector
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Sign in once:

```bash
garmin-connector login
```

It asks for your email, password and (if enabled) the MFA code. Only the session tokens are saved, to `~/.garminconnect/garmin_tokens.json` (owner-only permissions); your password is not stored. The session refreshes itself; if it ever stops working, run `login` again. `garmin-connector logout` deletes it. Set `GARMINTOKENS=/some/dir` to keep the tokens elsewhere.

## What you can get

| command / endpoint / tool | what | parameters |
|---|---|---|
| `profile` | name, units, profile settings | |
| `devices` | your Garmin devices | |
| `daily-summary` | steps, calories, distance, floors, intensity minutes, resting HR, stress, Body Battery | `date` |
| `sleep` | stages, score, timing, SpO2, respiration | `date` |
| `heart-rate` | resting/min/max + timeline | `date` |
| `hrv` | overnight HRV and status | `date` |
| `stress` | stress through the day | `date` |
| `body-battery` | charged/drained + timeline | `start`, `end` |
| `respiration` | breathing rate | `date` |
| `spo2` | pulse ox | `date` |
| `steps` | steps and goal per day | `start`, `end` (default last 7 days) |
| `body-composition` | weight, BMI, body fat | `start`, `end` (default last 30 days) |
| `training-readiness` | readiness score and factors | `date` |
| `training-status` | status, load, load focus | `date` |
| `max-metrics` | VO2 max, fitness age | `date` |
| `race-predictions` | 5K / 10K / half / marathon | |
| `personal-records` | PRs | |
| `activities` | recent activities, newest first | `limit` (1–100), `start`, `activity_type` |
| `activities-by-date` | activities in a date range | `start`, `end`, `activity_type` |
| `activity` | one activity in detail | `activity_id` |
| `activity-splits` | laps / splits | `activity_id` |
| `download` (CLI) / `/api/activity/<id>/download` | activity file | `format`: fit (original, zipped), tcx, gpx, kml, csv |

Dates accept `YYYY-MM-DD`, `today`, `yesterday`, or a number of days ago (`7`). `activity_type` is Garmin's key, e.g. `running`, `cycling`, `swimming`, `strength_training`.

In the CLI, underscores become dashes and parameters become flags (`--date`, `--activity-type`); `activity_id` is positional. In the JSON API and MCP the names keep underscores (`/api/daily_summary`, tool `daily_summary`).

```bash
garmin-connector daily-summary --date yesterday
garmin-connector activities --limit 5 --activity-type running
garmin-connector activity 12345678901
garmin-connector download 12345678901 --format gpx
```

## Use it from Claude

### Claude Desktop or Claude Code (local, simplest)

The MCP server runs on your computer over stdio; nothing is exposed to the network.

Claude Code:

```bash
claude mcp add garmin -- /full/path/to/garmin-connector/.venv/bin/garmin-connector mcp
```

Claude Desktop — add to `claude_desktop_config.json` (Settings → Developer → Edit Config), then restart:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "/full/path/to/garmin-connector/.venv/bin/garmin-connector",
      "args": ["mcp"]
    }
  }
}
```

Then ask things like "how did I sleep this week?" or "compare my last three runs".

### claude.ai custom connector (remote)

claude.ai connects from Anthropic's servers, so the server must be reachable over HTTPS from the internet, for example through a tunnel on your own machine or a small server you run.

1. Pick a long random access token and start the server:

   ```bash
   export GARMIN_CONNECTOR_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
   garmin-connector serve --port 8765 --allowed-host garmin.your-domain.com
   ```

2. Expose it over HTTPS, e.g. with Cloudflare Tunnel: `cloudflared tunnel --url http://localhost:8765` (a named tunnel gives you a stable hostname; pass that hostname to `--allowed-host`).
3. In claude.ai: Settings → Connectors → Add custom connector, URL:
   `https://garmin.your-domain.com/mcp?token=<your token>`

Treat that URL like a password: anyone with it can read your Garmin data. To revoke it, change `GARMIN_CONNECTOR_TOKEN` and restart. On a server without a terminal, run `login` once locally and copy `~/.garminconnect/garmin_tokens.json` over (or point `GARMINTOKENS` at it).

## JSON API

```bash
garmin-connector serve            # http://127.0.0.1:8765
```

- `GET /api` — lists every endpoint and its parameters
- `GET /api/<name>?param=value` — e.g. `/api/sleep?date=2026-11-09`, `/api/activities?limit=5`
- `GET /api/activity/<id>/download?format=gpx`
- `GET /health` — liveness, no token needed
- `POST /mcp` — the MCP endpoint (streamable HTTP)

On `127.0.0.1` the token is optional; set `GARMIN_CONNECTOR_TOKEN` to require it. When listening on another interface (`--host 0.0.0.0`) or with `--allowed-host`, a token is always required (one is generated and printed if you didn't set one). Send it as `Authorization: Bearer <token>` or `?token=<token>`.

```bash
curl -H "Authorization: Bearer $GARMIN_CONNECTOR_TOKEN" "http://127.0.0.1:8765/api/daily_summary?date=yesterday"
```

Errors come back as `{"error": "..."}` with 400 (bad parameter), 401 (no/wrong token, or not signed in to Garmin), 429 (Garmin rate limit) or 502 (Garmin failed).

## Adding an endpoint

Add a function to `src/garmin_connector/data.py` and list it in `ENDPOINTS`. It shows up in the CLI, the JSON API and as an MCP tool automatically. The [`garminconnect` `Garmin` class](https://github.com/cyberjunky/python-garminconnect) has ~300 methods to choose from (training plans, gear, hydration, women's health, golf, ...).

## Tests

```bash
pip install -e '.[test]'
pytest
```

The tests use a fake Garmin client; no account or network needed.
