# Existing monitor integration

The dashboard does not call Open-Meteo, OpenWeather, or the Sri Lankan warning
feed. The existing `/opt/weather-shutdown` process remains the sole provider
client. Its monitor script imports the mapper and client from this directory.

The versioned monitor source is `weather_shutdown.py` in this directory. After
reviewing changes, install it on the host at `/opt/weather-shutdown/weather_shutdown.py`
with ownership and permissions appropriate for the existing systemd service.
The scheduled service launches a new Python process on each run, so the next
scheduled check reads the installed file. Keep its production credentials in
`/etc/weather-shutdown/weather-shutdown.env`, never in source control.

After the Telegram attempt in each monitoring cycle, call `submit_cycle(payload)`
from `monitor_ingest.py`. The deployed monitor records each provider's complete
JSON response and the full official warning-feed body in `response_data`, along
with normalized readings for the charts.
Failed or skipped calls are recorded with their error status and message; a
dashboard ingest failure is logged and does not change alert decisions.

```python
from weather_monitor_payload import build_payload
from monitor_ingest import submit_cycle

outcome = create_alert(reason, detail) if dangerous_result else None
payload = build_payload(
    open_meteo=w,
    openweather=ow,
    warnings=warnings,
    decision="alert" if dangerous_result else "no_alert",
    alert_reason=reason if dangerous_result else None,
    alert_detail=detail if dangerous_result else None,
    telegram_status=outcome["status"] if outcome else None,
    telegram_detail=outcome["detail"] if outcome else None,
    next_eligible_at=outcome["next_eligible_at"] if outcome else None,
    warning_response=warning_response,
)
submit_cycle(payload)
```

For a partial cycle, pass `None` for providers that were not called and pass
their error text in `endpoint_errors`, keyed as `open_meteo`, `openweather`, or
`official_warnings`. This keeps failed endpoints visible without inventing a
successful result.

The payload shape is:

```python
{
    "run_key": str(int(time.time())),
    "observed_at": datetime.now(timezone.utc).isoformat(),
    "decision": "no_alert",  # or "alert"
    "endpoint_calls": [
        {
            "category": "weather provider",
            "endpoint": "open-meteo forecast",
            "called_at": "2026-10-21T00:00:00+00:00",
            "status": "success",
            "duration_ms": None,
            "summary": "Open-Meteo response payload",
            "response_data": {"current": {"temperature_2m": 27.0}},
        },
        {
            "category": "official warnings",
            "endpoint": "Sri Lanka weather warnings",
            "called_at": "2026-10-21T00:00:00+00:00",
            "status": "success",
            "summary": "0 active warning(s) returned",
            "response_data": {"warnings": []},
        },
    ],
    "providers": [
        {
            "provider": "open_meteo",
            "observed_at": "2026-10-21T00:00:00+00:00",
            "temperature_c": 27.0,
            "precipitation_mm": 1.2,
            "precipitation_probability": 70,
            "wind_speed": 4.0,
            "weather_code": 51,
            "thunder": False,
            "error": None,
        }
    ],
    "official_warnings": [],
    "alert_reason": None,
    "alert_detail": None,
    "telegram_status": None,
    "telegram_detail": None,
    "next_eligible_at": None,
}
```

Configure these variables in the existing monitor service environment, without
putting the token in source code:

```text
WEATHER_DASHBOARD_INGEST_URL=http://127.0.0.1:8788/weather-dashboard/internal/v1/monitoring/ingest
WEATHER_DASHBOARD_INGEST_TOKEN=<same random value as the dashboard .env>
ALERT_COOLDOWN_SECONDS=1800
```

Delivery status is `accepted_by_telegram` only after Telegram's API accepts the
message. `suppressed_by_cooldown` includes the next eligible time. `failed`
includes a sanitized error category and is retried on the next check. Legacy
`not_sent` dashboard entries mean delivery is unverified. Each accepted reminder
gets a new approval link with the existing 10-minute lifetime.

The monitor supports `MODE=telegram_check` for a benign Telegram connectivity
message. It contains no shutdown approval link and does not save an alert or
request poweroff. The dashboard's authenticated event stream refreshes open
browsers after a cycle commits; a 30-second refresh remains as fallback.

Shutdown approval alerts are reserved for thunderstorm or lightning risk. The
monitor checks future six-hour WMO thunderstorm codes (95, 96, 97, 99) and
OpenWeather 2xx thunderstorm codes, matching the forecast hours within one hour.
A storm forecast from one service needs nearby thunderstorm or rain evidence
from the other service. Rain probability alone never creates a shutdown alert.
An official thunder or lightning warning for Kalutara, Western Province, or
the whole island remains an independent trigger; warnings for other districts
do not create a Horana shutdown request. Telegram messages show the local forecast time and
evidence, identify that no lightning strike was measured, and include a review
button; confirming the web page remains required before
any shutdown.

The monitor must still complete its provider calls and Telegram decision even
if ingestion fails. Log the ingestion failure, but do not turn a database/API
outage into a weather-provider outage.



The dashboard stores each item in `endpoint_calls` as a separate record, grouped by
category in the API Calls view. The mapper records the provider response body and
cycle timestamp. Pass `duration_ms` when the monitor measures individual HTTP
request durations; the dashboard displays it when present. The next-cycle time is
an estimate based on the median gap between recent monitoring runs.
