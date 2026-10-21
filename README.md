# Weather Dashboard

A private weather and server safety dashboard for Horana, Sri Lanka. It combines a React weather app, a FastAPI service, PostgreSQL history, and a host weather monitor. The monitor fetches Open-Meteo, OpenWeather, and Sri Lanka Department of Meteorology warnings, then records each cycle in the dashboard.

The MACM light interface shows current conditions, a 12-hour forecast, animated weather scenes, provider comparisons, charts, endpoint responses, Telegram delivery status, and the estimated next check. Open browser sessions refresh after new data arrives.

## Architecture

    Host monitor ── weather APIs and official warning feed
        ├── Telegram alert → approval page → optional graceful shutdown
        └── authenticated ingest → FastAPI → PostgreSQL
                                      │
    Browser ← local Nginx + React ←───┘

The dashboard itself makes no weather-provider calls. The deployable host monitor source is in [integration/weather_shutdown.py](integration/weather_shutdown.py); its installation notes are in [integration/README.md](integration/README.md).

## Requirements

- Docker Engine and the Compose plugin
- Python 3.11+ for the host monitor
- OpenWeather and Telegram credentials for forecast alerts
- A private HTTPS reverse proxy, such as Tailscale Serve, for remote access

## Configure and start

    cp .env.example .env
    # Set unique, long values for every password, secret, and token.
    chmod 600 .env
    docker compose up -d --build

Open http://127.0.0.1:8788/weather-dashboard/ on the server and log in with ADMIN_USERNAME and ADMIN_PASSWORD from .env. This production host manages Compose as root, so use sudo for its Compose commands.

The web service binds to 127.0.0.1 by default. PostgreSQL has no published host port. Keep .env private; the example files contain placeholders only. The administrator is created on first startup, so changing ADMIN_PASSWORD in .env later does not reset the stored password.

| Variable | Purpose |
| --- | --- |
| POSTGRES_PASSWORD | Database credential |
| SESSION_SECRET | Dashboard session signing |
| MONITOR_INGEST_TOKEN | Host monitor to dashboard ingestion |
| CONTROL_TOKEN | Optional host control helper |
| ADMIN_USERNAME / ADMIN_PASSWORD | Initial administrator |
| COOKIE_SECURE | Secure login cookie for HTTPS deployments |
| RETENTION_DAYS | Monitoring history retention, default 90 days |
| SHUTDOWN_ENABLED | Manual shutdown control, disabled by default |
| WEB_PORT | Local web port, default 8788 |

## Connect the host monitor

Configure these values in the monitor's root-owned environment file. Use the same ingest token as the dashboard .env.

    WEATHER_DASHBOARD_INGEST_URL=http://127.0.0.1:8788/weather-dashboard/internal/v1/monitoring/ingest
    WEATHER_DASHBOARD_INGEST_TOKEN=<MONITOR_INGEST_TOKEN from .env>
    ALERT_COOLDOWN_SECONDS=1800

The monitor sends one cycle after its weather and Telegram decisions. The API saves normalized readings and the full response from each successful provider call, including the official warning feed. Failed endpoints are stored separately. Old records are removed after RETENTION_DAYS.

Shutdown approval alerts require a relevant official thunder or lightning warning, or a thunderstorm signal from one forecast provider with nearby support from the other. Rain probability alone does not trigger a shutdown alert. Telegram acceptance, cooldown suppression, and delivery failure have separate statuses. An approval link expires after 10 minutes by default and still requires an explicit confirmation. A forecast does not mean a lightning strike was detected.

## Verify operation

    docker compose ps
    curl -fsS http://127.0.0.1:8788/weather-dashboard/
    systemctl status weather-shutdown-check.timer
    journalctl -u weather-shutdown-check.service -n 40 --no-pager

After a scheduled check, the monitor log should say "weather dashboard cycle recorded". The dashboard should show a recent observation, provider readings, and endpoint calls. "Telegram accepted weather alert" means Telegram's API accepted the message; it does not prove a phone displayed it. The monitor's MODE=telegram_check sends a benign connectivity message with no shutdown link.

To inspect ingestion counts on the Compose host:

    docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT count(*) FROM monitoring_runs; SELECT count(*) FROM provider_readings; SELECT count(*) FROM endpoint_calls;"'

## Access and shutdown safety

The browser requires login. You can create separately scoped, read-only API tokens for trusted devices; plaintext is shown once and only its hash is stored. The monitor ingest and host control tokens are separate. The containers receive neither the Docker socket nor weather-provider credentials.

Manual shutdown stays disabled unless SHUTDOWN_ENABLED=true. The optional host helper in [control-helper.py](control-helper.py) and [weather-dashboard-control.service](weather-dashboard-control.service) additionally requires EXECUTE_SHUTDOWN=true in a root-owned /etc/weather-dashboard/control.env. Review and dry-run that path before enabling it. See [control.env.example](control.env.example) for its settings.

If using Tailscale Serve, publish /weather-dashboard/ without replacing the monitor's /approve/ route. Keep the local web listener bound to loopback.

## Project layout

| Path | Contents |
| --- | --- |
| frontend/ | React app, MACM styles, weather artwork, Nginx proxy |
| backend/ | FastAPI, PostgreSQL models, weather overview, event stream |
| integration/ | Host monitor, payload mapper, ingestion client, setup notes |
| compose.yaml | Database, API, and web containers |
| control-helper.py | Optional host-side manual shutdown worker |
| *.service | Example systemd units |

## Local development

The frontend uses Vite: run npm install and npm run dev in frontend/. The API dependencies are in backend/requirements.txt. Focused Python checks are in backend/app/test_weather_view.py and can be run with python3 -m unittest backend/app/test_weather_view.py on a host with the API dependencies installed.

This repository holds application source and example configuration. Runtime database files, installed dependencies, generated builds, and live secrets stay on the host and are ignored by Git.
