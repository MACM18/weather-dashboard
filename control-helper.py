#!/usr/bin/env python3
"""Host-side bridge for the dashboard's delayed shutdown requests.

This process has no Docker access. It only sees requests through the private
dashboard API and can run the single sudoers-approved poweroff command after
the cancellation deadline. Keep EXECUTE_SHUTDOWN=false until the complete
workflow has been tested in dry-run mode.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.request


API = os.environ.get("WEATHER_DASHBOARD_INTERNAL_URL", "http://127.0.0.1:8788/weather-dashboard/internal/v1")
TOKEN = os.environ.get("WEATHER_DASHBOARD_CONTROL_TOKEN", "")
EXECUTE = os.environ.get("EXECUTE_SHUTDOWN", "false").lower() == "true"


def request(method: str, path: str, body: dict | None = None) -> dict:
    payload = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=payload, method=method, headers={"X-Control-Token": TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10, context=ssl.create_default_context()) as response:
        return json.loads(response.read())


def run() -> None:
    if not TOKEN:
        raise SystemExit("WEATHER_DASHBOARD_CONTROL_TOKEN is required")
    while True:
        try:
            pending = request("GET", "/shutdown/pending")
            now = time.time()
            for item in pending:
                deadline = item["cancel_deadline"].replace("Z", "+00:00")
                from datetime import datetime
                seconds = datetime.fromisoformat(deadline).timestamp() - now
                if seconds > 0:
                    continue
                claim = request("POST", f"/shutdown/requests/{item['id']}/claim")
                if not claim.get("execute") or not EXECUTE:
                    request("POST", f"/shutdown/requests/{item['id']}/complete?result=dry_run")
                    continue
                try:
                    subprocess.run(["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "poweroff"], check=True)
                    request("POST", f"/shutdown/requests/{item['id']}/complete?result=powered_off")
                except (subprocess.CalledProcessError, OSError):
                    request("POST", f"/shutdown/requests/{item['id']}/complete?result=failed")
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as exc:
            print(f"weather-dashboard-control: {exc}", flush=True)
        time.sleep(2)


if __name__ == "__main__":
    run()

