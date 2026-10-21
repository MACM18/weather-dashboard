"""Small stdlib-only client for the existing weather-shutdown monitor.

The monitor remains responsible for all external weather requests. Call
submit_cycle() once after each monitoring cycle. The endpoint is internal and
authenticated with MONITOR_INGEST_TOKEN; it is not an end-user API token.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.request


INGEST_URL = os.environ.get(
    "WEATHER_DASHBOARD_INGEST_URL",
    "http://127.0.0.1:8788/weather-dashboard/internal/v1/monitoring/ingest",
)
INGEST_TOKEN = os.environ.get("WEATHER_DASHBOARD_INGEST_TOKEN", "")


def submit_cycle(payload: dict) -> None:
    """Submit one already-collected monitor cycle without contacting providers."""
    if not INGEST_TOKEN:
        raise RuntimeError("WEATHER_DASHBOARD_INGEST_TOKEN is not configured")
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        INGEST_URL,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Monitor-Token": INGEST_TOKEN,
            "User-Agent": "weather-shutdown-monitor/1.0",
        },
    )
    context = ssl.create_default_context()
    with urllib.request.urlopen(request, timeout=10, context=context) as response:
        if response.status not in (200, 202):
            raise RuntimeError(f"weather dashboard rejected ingest: HTTP {response.status}")

