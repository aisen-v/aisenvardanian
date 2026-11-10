# garmin-connector

A personal connector to your own Garmin data. It gives you:

- **a CLI**: `garmin-connector sleep --date yesterday`
- **a JSON API**: `GET /api/sleep?date=yesterday`
- **an MCP server**, so Claude (Desktop, Claude Code, or claude.ai as a custom connector) can read your data

Everything is read-only. There are two backends:

| | **official** (Garmin Connect Developer Program) | **unofficial** (Garmin Connect app sign-in) |
|---|---|---|
| you need | your app's consumer key + secret | your Garmin email + password |
| sign-in | OAuth 2.0 consent page | email/password (+ MFA) |
| how data arrives | Garmin pushes it to your webhook when the watch syncs; recent uploads can also be pulled | fetched live on request |
| data | dailies, sleep, stress/Body Battery, HRV, SpO2, respiration, VO2 max, body comp, activities (+ details) | all of that plus training readiness/status, race predictions, PRs, devices, file downloads |
| stability | supported by Garmin | can break when Garmin changes things |

The backend is **official** when `GARMIN_CLIENT_ID` is set, otherwise **unofficial**. Force one with `GARMIN_BACKEND=official|unofficial`.

## Install

Needs Python 3.10+.

```bash
cd garmin-connector
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Official API (Developer Program key)

### 1. Configure your app

Put the consumer key and secret in the environment, not in a file in this repo (for example in your shell profile, or a `.env` you `source` that is gitignored):

```bash
export GARMIN_CLIENT_ID="<consumer key>"
export GARMIN_CLIENT_SECRET="<consumer secret>"
```

In the developer portal, set your app's **redirect URL** to `http://localhost:8765/oauth/callback`, or set `GARMIN_REDIRECT_URI` to whatever URL you registered there. When it isn't on localhost, sign-in asks you to paste the URL you land on after approving.

### 2. Sign in

```bash
garmin-connector login
```

Your browser opens Garmin's consent page; approve the data you want to share. The access and refresh tokens are saved to `~/.garminconnect/official_tokens.json` (owner-only) and refreshed automatically. `garmin-connector status` shows your Garmin user ID, the permissions you granted and what's stored.

### 3. Get data in

Garmin doesn't answer "give me Tuesday's sleep". It delivers each summary when your watch syncs, so the connector keeps a local store (`~/.garminconnect/official_data.sqlite3`, or `GARMIN_DATA_DB`) and answers queries from it. Three ways to fill it:

- **Webhooks (best, automatic).** Run the server somewhere Garmin can reach over HTTPS (see [claude.ai custom connector](#claudeai-custom-connector-remote) for a tunnel), then in the developer portal's endpoint configuration set every data type you use to push or ping to:

  `https://<your host>/garmin/webhook?token=<GARMIN_CONNECTOR_TOKEN>`

  Push and ping both work; for ping, the connector fetches the data from Garmin itself (and only ever sends your token to `apis.garmin.com`). Notifications for other Garmin users are ignored.
- **`garmin-connector sync --days 2`** pulls whatever your watch uploaded in the last 1–7 days. Claude can call `sync` itself when a day comes back empty. (Garmin pulls work by *upload* time, 24 hours per request; the connector splits that for you.)
- **`garmin-connector backfill --days 365`** asks Garmin to resend older history (in 90-day requests). It arrives through the webhooks, so the server must be running and reachable.

### What you can get (official)

| command / endpoint / tool | what | parameters |
|---|---|---|
| `profile` | Garmin user ID, granted permissions, what's stored | |
| `daily-summary` | steps, distance, calories, floors, intensity minutes, HR, stress, Body Battery | `date` |
| `daily-summaries` | the same for each day in a range | `start`, `end` |
| `sleep` | stages, score, timing | `date` |
| `stress` | stress and Body Battery through the day | `date` |
| `hrv` | overnight HRV | `date` |
| `respiration` | breathing rate | `date` |
| `spo2` | pulse ox | `date` |
| `user-metrics` | VO2 max, fitness age | `start`, `end` |
| `body-composition` | weight, BMI, body fat | `start`, `end` |
| `activities` | activities in a date range | `start`, `end`, `activity_type` (e.g. `RUNNING`) |
| `activity-details` | samples (HR, pace, GPS, power) and laps of one activity | `activity_id` |
| `summaries` | any stored type: `epochs`, `blood_pressure`, `skin_temp`, `health_snapshot`, `move_iq`, ... | `kind`, `start`, `end` |
| `sync` | pull the last N days of uploads into the store | `days` (1–7) |

Which data types you actually receive depends on what's enabled for your app in the portal and what you approved at sign-in. A 403 on `sync` for a type means it isn't enabled.

`garmin-connector logout` forgets the tokens; `logout --deregister` also revokes the app's access at Garmin.

> The Garmin endpoints used (consent page `connect.garmin.com/oauth2Confirm`, token endpoint `diauth.garmin.com/di-oauth2-service/oauth/token`, data under `apis.garmin.com/wellness-api/rest/`) follow Garmin's published OAuth2 PKCE and Health/Activity API specs. If your portal documentation shows different URLs, override them with `GARMIN_AUTH_URL`, `GARMIN_TOKEN_URL` and `GARMIN_API_BASE`.

## Unofficial backend (email + password)

Without a Developer Program key, this uses the same sign-in as the Garmin Connect app, through the open-source [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library. It's unofficial: Garmin can change things and break it, and it's meant for your own account only. Don't poll it aggressively — Garmin rate-limits (HTTP 429).

Sign in once:

```bash
garmin-connector login
```

It asks for your email, password and (if enabled) the MFA code. Only the session tokens are saved, to `~/.garminconnect/garmin_tokens.json` (owner-only permissions); your password is not stored. The session refreshes itself; if it ever stops working, run `login` again. `garmin-connector logout` deletes it. Set `GARMINTOKENS=/some/dir` to keep the tokens elsewhere.

### What you can get (unofficial)

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
claude mcp add garmin -e GARMIN_CLIENT_ID="$GARMIN_CLIENT_ID" -e GARMIN_CLIENT_SECRET="$GARMIN_CLIENT_SECRET" -- /full/path/to/garmin-connector/.venv/bin/garmin-connector mcp
```

Claude Desktop — add to `claude_desktop_config.json` (Settings → Developer → Edit Config), then restart:

```json
{
  "mcpServers": {
    "garmin": {
      "command": "/full/path/to/garmin-connector/.venv/bin/garmin-connector",
      "args": ["mcp"],
      "env": {
        "GARMIN_CLIENT_ID": "<consumer key>",
        "GARMIN_CLIENT_SECRET": "<consumer secret>"
      }
    }
  }
}
```

Leave out the `-e` flags / `env` block for the unofficial backend. Claude Desktop doesn't see your shell's environment, which is why the key goes in its config (that file stays on your computer). The local MCP server can't receive webhooks, so with the official backend either also run `garmin-connector serve` behind a tunnel, or let Claude call `sync` to pull recent days.

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
- `POST /garmin/webhook` — push/ping notifications from Garmin (official backend)

On `127.0.0.1` the token is optional; set `GARMIN_CONNECTOR_TOKEN` to require it. When listening on another interface (`--host 0.0.0.0`) or with `--allowed-host`, a token is always required (one is generated and printed if you didn't set one). Send it as `Authorization: Bearer <token>` or `?token=<token>`.

```bash
curl -H "Authorization: Bearer $GARMIN_CONNECTOR_TOKEN" "http://127.0.0.1:8765/api/daily_summary?date=yesterday"
```

Errors come back as `{"error": "..."}` with 400 (bad parameter), 401 (no/wrong token, or not signed in to Garmin), 429 (Garmin rate limit) or 502 (Garmin failed).

## Adding an endpoint

Add a function to `src/garmin_connector/data.py` (unofficial) or `src/garmin_connector/official/endpoints.py` (official) and list it in that file's `ENDPOINTS`. It shows up in the CLI, the JSON API and as an MCP tool automatically. The [`garminconnect` `Garmin` class](https://github.com/cyberjunky/python-garminconnect) has ~300 methods to choose from (training plans, gear, hydration, women's health, golf, ...).

## Tests

```bash
pip install -e '.[test]'
pytest
```

The tests use fake Garmin responses; no account, key or network needed.
