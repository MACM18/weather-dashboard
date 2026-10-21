#!/usr/bin/env python3
import hashlib, html, json, os, secrets, sqlite3, ssl, time
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

sys.path.insert(0, "/opt/weather-dashboard/integration")
from weather_monitor_payload import build_payload
from monitor_ingest import submit_cycle

APP = "weather-shutdown"
DATA_DIR = os.environ.get("DATA_DIR", "/var/lib/weather-shutdown")
DB = os.path.join(DATA_DIR, "state.sqlite3")
HOST = os.environ.get("BIND_HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787"))
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"
LAT = os.environ.get("LATITUDE", "6.7167")
LON = os.environ.get("LONGITUDE", "80.0667")
AREA = os.environ.get("WARNING_AREA", "Kalutara").lower()
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
BASE_URL = os.environ.get("APPROVAL_BASE_URL", "")
COOLDOWN = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "1800"))
TOKEN_TTL = int(os.environ.get("TOKEN_TTL_SECONDS", "600"))
THUNDER_CODES = {95, 96, 97, 99}
THUNDER_WARNING = re.compile(r"\b(?:thunder\w*|lightning|electrical storm|hailstorm\w*)\b", re.IGNORECASE)
ISLAND_WIDE = ("island-wide", "island wide", "throughout the island", "whole island", "over the island", "most parts of the island", "across sri lanka")

def log(msg):
    print(f"{APP}: {msg}", flush=True)


def safe_error(error):
    message = str(error)
    for secret in (OPENWEATHER_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, BASE_URL):
        if secret:
            message = message.replace(secret, "[redacted]")
    return message[:500]


def record_dashboard_cycle(
    open_meteo=None,
    openweather_result=None,
    warnings=None,
    endpoint_errors=None,
    decision="no_alert",
    alert_reason=None,
    alert_detail=None,
    telegram_status=None,
    telegram_detail=None,
    next_eligible_at=None,
    warning_response=None,
):
    """Send collected monitor data to the dashboard without affecting alerts."""
    try:
        payload = build_payload(
            open_meteo=open_meteo,
            openweather=openweather_result,
            warnings=warnings,
            decision=decision,
            alert_reason=alert_reason,
            alert_detail=alert_detail,
            telegram_status=telegram_status,
            telegram_detail=telegram_detail,
            next_eligible_at=next_eligible_at,
            endpoint_errors=endpoint_errors,
            warning_response=warning_response,
        )
        submit_cycle(payload)
        log("weather dashboard cycle recorded")
    except Exception as e:
        log("weather dashboard ingest failed: " + str(e))

def db():
    os.makedirs(DATA_DIR, mode=0o750, exist_ok=True)
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, created INTEGER NOT NULL, expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS events (key TEXT PRIMARY KEY, sent INTEGER NOT NULL, reason TEXT NOT NULL)")
    c.commit()
    return c

def fetch_response(req):
    cafile = "/etc/ssl/certs/ca-certificates.crt"
    context = ssl.create_default_context(cafile=cafile) if os.path.exists(cafile) else ssl.create_default_context()
    with urlopen(req, timeout=20, context=context) as response:
        return response.read()

def fetch(url, headers=None):
    req = Request(url, headers=headers or {"User-Agent": APP})
    return fetch_response(req)

def weather():
    url = (
        "https://api.open-meteo.com/v1/forecast?latitude=" + LAT
        + "&longitude=" + LON
        + "&current=temperature_2m,apparent_temperature,relative_humidity_2m,is_day,precipitation,weather_code,wind_speed_10m"
        + "&hourly=temperature_2m,precipitation_probability,precipitation,weather_code"
        + "&forecast_days=2&timezone=Asia%2FColombo"
    )
    data = json.loads(fetch(url))
    current = data.get("current", {})
    hourly = data.get("hourly", {})
    indices = future_meteo_indices(hourly, 6)
    def selected(name):
        values = hourly.get(name) or []
        return [values[index] for index in indices if index < len(values) and values[index] is not None]
    rain = max(selected("precipitation") or [0])
    probability = max(selected("precipitation_probability") or [0])
    hours = []
    for index in indices:
        try:
            stamp = datetime.fromisoformat(hourly["time"][index])
            stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Colombo")) if stamp.tzinfo is None else stamp.astimezone(ZoneInfo("Asia/Colombo"))
            code = int(hourly["weather_code"][index])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        values = lambda name: (hourly.get(name) or [])
        chance = values("precipitation_probability")
        amount = values("precipitation")
        hours.append({"at": stamp, "code": code, "thunder": code in THUNDER_CODES,
                      "rain_chance": float(chance[index] or 0) if index < len(chance) else 0,
                      "rain_mm": float(amount[index] or 0) if index < len(amount) else 0})
    try:
        observed = datetime.fromisoformat(current["time"])
        observed = observed.replace(tzinfo=ZoneInfo("Asia/Colombo")) if observed.tzinfo is None else observed.astimezone(ZoneInfo("Asia/Colombo"))
        code = int(current["weather_code"])
        if 0 <= (datetime.now(ZoneInfo("Asia/Colombo")) - observed).total_seconds() <= 3600:
            hours.insert(0, {"at": observed, "code": code, "thunder": code in THUNDER_CODES,
                             "rain_chance": 0, "rain_mm": float(current.get("precipitation") or 0)})
    except (KeyError, TypeError, ValueError):
        pass
    thunder = any(hour["thunder"] for hour in hours)
    return {"current": current, "rain": rain, "probability": probability, "thunder": thunder, "hours": hours, "response": data}

def openweather():
    if not OPENWEATHER_API_KEY:
        raise RuntimeError("OpenWeather API key is not configured")

    url = (
        "https://api.openweathermap.org/data/4.0/onecall/timeline/1h"
        f"?lat={LAT}&lon={LON}"
        f"&units=metric&appid={OPENWEATHER_API_KEY}"
    )

    data = json.loads(fetch(url))
    now = datetime.now(timezone.utc).timestamp()
    all_hours = data.get("data", [])
    timeline = [item for item in all_hours if float(item.get("dt", 0)) > now][:6]
    recent = [item for item in all_hours if now - 3600 <= float(item.get("dt", 0)) <= now]

    rain_values = [
        float(item.get("rain", {}).get("1h", 0) or 0)
        for item in timeline
    ]

    probability_values = [
        float(item.get("pop", 0) or 0) * 100
        for item in timeline
    ]

    hours = []
    for item in recent[-1:] + timeline:
        conditions = item.get("weather") or []
        codes = [int(condition.get("id", 0)) for condition in conditions]
        hours.append({"at": datetime.fromtimestamp(int(item["dt"]), timezone.utc).astimezone(ZoneInfo("Asia/Colombo")),
                      "code": next((code for code in codes if 200 <= code <= 232), codes[0] if codes else None),
                      "thunder": any(200 <= code <= 232 for code in codes),
                      "rain_chance": float(item.get("pop", 0) or 0) * 100,
                      "rain_mm": float((item.get("rain") or {}).get("1h", 0) or 0)})
    thunder = any(hour["thunder"] for hour in hours)

    alerts = []
    for item in timeline:
        alerts.extend(str(alert) for alert in item.get("alerts", []))

    return {
        "current": timeline[0] if timeline else {},
        "rain": max(rain_values or [0]),
        "probability": max(probability_values or [0]),
        "thunder": thunder,
        "alerts": alerts,
        "hours": hours,
        "response": data,
    }

def official_warnings():
    raw = fetch("https://was.meteo.gov.lk/cap/en/rss.xml")
    root = ElementTree.fromstring(raw)
    found = []
    thunder_found = []
    items = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1].lower() == "item"]
    for item in items:
        content = " ".join((element.text or "") for element in item.iter())
        lowered = content.lower()
        if (AREA and AREA in lowered) or "western province" in lowered or any(term in lowered for term in ISLAND_WIDE):
            title = next(
                (element.text for element in item.iter()
                 if element.tag.rsplit("}", 1)[-1].lower() == "title"),
                None,
            )
            found.append(" ".join((title or "Official warning").split()))
            match = THUNDER_WARNING.search(content)
            if match:
                summary = found[-1]
                if not THUNDER_WARNING.search(summary):
                    excerpt = " ".join(content[max(0, match.start() - 45):match.end() + 95].split())
                    summary += ": " + excerpt
                thunder_found.append(summary[:240])
    return found, raw, thunder_found

def local_hour(stamp):
    return stamp.astimezone(ZoneInfo("Asia/Colombo")).strftime("%a %I:%M %p").replace(" 0", " ")

def thunderstorm_decision(meteo, open_weather):
    """Require a thunderstorm forecast plus a nearby corroborating signal."""
    meteo_hours = meteo.get("hours") or []
    openweather_hours = open_weather.get("hours") or []
    candidates = []
    for first in meteo_hours:
        for second in openweather_hours:
            if abs((first["at"] - second["at"]).total_seconds()) > 3600:
                continue
            if first["thunder"] and second["thunder"]:
                candidates.append((0, first["at"], first, second, "both"))
            elif first["thunder"] and (second["rain_chance"] >= 50 or second["rain_mm"] >= 0.5):
                candidates.append((1, first["at"], first, second, "meteo"))
            elif second["thunder"] and (first["rain_chance"] >= 50 or first["rain_mm"] >= 0.5):
                candidates.append((1, second["at"], first, second, "openweather"))
    if not candidates:
        return None
    _, forecast_time, first, second, support = min(candidates, key=lambda item: (item[0], item[1]))
    when = local_hour(forecast_time)
    if support == "both":
        evidence = f"Both forecast services show a thunderstorm near {when} (Open-Meteo WMO {first['code']}; OpenWeather {second['code']})."
    elif support == "meteo":
        evidence = f"Open-Meteo shows a thunderstorm near {when} (WMO {first['code']}); OpenWeather shows rain nearby ({second['rain_chance']:.0f}% chance)."
    else:
        evidence = f"OpenWeather shows a thunderstorm near {when} (code {second['code']}); Open-Meteo shows rain nearby ({first['rain_chance']:.0f}% chance)."
    return {"reason": "Thunderstorm or lightning risk", "detail": evidence}

def future_meteo_indices(hourly, count, now=None):
    """Take future local hourly timestamps, including hours across midnight."""
    now = now or datetime.now(ZoneInfo("Asia/Colombo"))
    result = []
    for index, stamp in enumerate(hourly.get("time") or []):
        try:
            hour = datetime.fromisoformat(stamp)
            hour = hour.replace(tzinfo=ZoneInfo("Asia/Colombo")) if hour.tzinfo is None else hour.astimezone(ZoneInfo("Asia/Colombo"))
        except (TypeError, ValueError):
            continue
        if hour > now:
            result.append(index)
        if len(result) == count:
            break
    return result

def token(reason):
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    now = int(time.time())
    connection = db()
    connection.execute(
        "INSERT INTO tokens(hash,created,expires,reason) VALUES(?,?,?,?)",
        (digest, now, now + TOKEN_TTL, reason),
    )
    connection.commit()
    connection.close()
    return raw

def telegram(text, approval_url=None):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram credentials are not configured")

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if approval_url:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": "Review shutdown request", "url": approval_url}]]}
    body = json.dumps(payload).encode()

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": APP},
    )
    result = json.loads(fetch_response(request))
    if not result.get("ok"):
        raise RuntimeError("Telegram rejected the message")

def telegram_connectivity_check():
    """Verify delivery without creating an approval token or shutdown link."""
    try:
        telegram("Weather monitor connectivity check. No shutdown approval is requested.")
    except Exception as error:
        log(f"Telegram connectivity check failed ({type(error).__name__})")
        return False
    log("Telegram accepted connectivity check")
    return True


def create_alert(reason, detail):
    key = hashlib.sha256(reason.encode()).hexdigest()
    now = int(time.time())
    c = db()
    row = c.execute("SELECT sent FROM events WHERE key=?", (key,)).fetchone()
    if row and now - row[0] < COOLDOWN:
        eligible = datetime.fromtimestamp(row[0] + COOLDOWN, timezone.utc).isoformat()
        c.close()
        return {"status": "suppressed_by_cooldown", "detail": "A previous alert was accepted by Telegram; waiting for the next eligible check.", "next_eligible_at": eligible}
    link = (BASE_URL.rstrip("/") + "/approve/" + token(reason)) if BASE_URL else None
    checked = datetime.fromtimestamp(now, ZoneInfo("Asia/Colombo")).strftime("%a %d %b, %I:%M %p")
    heading = "🧪 WEATHER MONITOR TEST" if reason == "test" else "⚡ THUNDER / LIGHTNING RISK"
    action = (f"Tap the button below to review a graceful shutdown. The link expires in {TOKEN_TTL // 60} minutes."
              if link else "Approval link is not configured; check the monitor service settings.")
    mode = "Dry run: approval will not power off the server." if DRY_RUN else "Live mode: shutdown occurs only after your confirmation."
    text = (f"<b>{heading}</b>\n"
            f"📍 <b>Horana, Sri Lanka</b>\n"
            f"🕒 Checked {checked} (Sri Lanka time)\n\n"
            f"<b>Why this alert</b>\n{html.escape(detail)}\n\n"
            "<i>This is a forecast or official warning, not a detected lightning strike.</i>\n\n"
            f"<b>Your choice</b>\n{action}\n"
            f"{mode}")
    try:
        telegram(text, approval_url=link)
    except Exception as error:
        c.close()
        # Never save the approval URL, API token, or Telegram response body.
        detail = f"Telegram delivery failed ({type(error).__name__}); retry on the next check."
        log(detail)
        return {"status": "failed", "detail": detail, "next_eligible_at": None}
    sent = int(time.time())
    c.execute("INSERT OR REPLACE INTO events(key,sent,reason) VALUES(?,?,?)", (key, sent, reason))
    c.commit(); c.close()
    eligible = datetime.fromtimestamp(sent + COOLDOWN, timezone.utc).isoformat()
    log("Telegram accepted weather alert; next eligible at " + eligible)
    return {"status": "accepted_by_telegram", "detail": "Telegram API accepted the alert message.", "next_eligible_at": eligible}

def record_alert_cycle(reason, detail, decision, **cycle):
    outcome = create_alert(reason, detail)
    if outcome["status"] == "suppressed_by_cooldown":
        log("Telegram alert suppressed until " + outcome["next_eligible_at"])
    record_dashboard_cycle(decision=decision, alert_reason=reason, alert_detail=detail,
                           telegram_status=outcome["status"], telegram_detail=outcome["detail"],
                           next_eligible_at=outcome["next_eligible_at"], **cycle)
    return outcome["status"] == "accepted_by_telegram"

def check_once(test_alert=False):
    errors = {}
    try:
        w = weather()
    except Exception as e:
        w = None
        errors["open_meteo"] = safe_error(e)
        log("Open-Meteo check failed: " + errors["open_meteo"])

    try:
        warnings, warning_response, thunder_warnings = official_warnings()
    except Exception as e:
        warnings, warning_response, thunder_warnings = [], None, []
        errors["official_warnings"] = safe_error(e)
        log("official warning feed check failed: " + errors["official_warnings"])

    if w:
        log(f"Open-Meteo current={w['current']} rain6h={w['rain']} "
            f"probability6h={w['probability']} thunder={w['thunder']} "
            f"official={len(warnings)} lightning_warnings={len(thunder_warnings)}")

    if test_alert:
        return record_alert_cycle("test", "operator-requested dry-run test", "test_alert",
                                  open_meteo=w, warnings=warnings, warning_response=warning_response,
                                  endpoint_errors=errors)

    # A relevant official warning can trigger even if a forecast provider fails.
    if thunder_warnings:
        detail = "Sri Lanka Department of Meteorology warns of thunder or lightning: " + "; ".join(thunder_warnings[:3])
        return record_alert_cycle("Official thunderstorm or lightning warning", detail, "alert",
                                  open_meteo=w, warnings=warnings, warning_response=warning_response,
                                  endpoint_errors=errors)

    try:
        ow = openweather()
    except Exception as e:
        ow = None
        errors["openweather"] = safe_error(e)
        log("OpenWeather check failed: " + errors["openweather"])

    if ow:
        log(f"OpenWeather current={ow['current']} rain6h={ow['rain']} "
            f"probability6h={ow['probability']} thunder={ow['thunder']} alerts={len(ow['alerts'])}")

    decision = thunderstorm_decision(w, ow) if w and ow else None
    if decision:
        return record_alert_cycle(decision["reason"], decision["detail"], "alert",
                                  open_meteo=w, openweather_result=ow, warnings=warnings,
                                  warning_response=warning_response, endpoint_errors=errors)

    record_dashboard_cycle(
        open_meteo=w,
        openweather_result=ow,
        warnings=warnings,
        warning_response=warning_response,
        endpoint_errors=errors,
    )
    return False

def approve(raw):
    digest = hashlib.sha256(raw.encode()).hexdigest(); now = int(time.time()); c = db()
    row = c.execute("SELECT reason,expires,used FROM tokens WHERE hash=?", (digest,)).fetchone()
    if not row or row[2] or row[1] < now: c.close(); return False, "This approval link is invalid, expired, or already used."
    c.execute("UPDATE tokens SET used=1 WHERE hash=? AND used=0", (digest,)); c.commit(); c.close()
    if DRY_RUN: return True, "Dry-run is enabled. No shutdown was performed."
    rc = os.system("/usr/bin/sudo /usr/bin/systemctl poweroff")
    return rc == 0, ("Shutdown command accepted." if rc == 0 else "Shutdown command failed; check the service log.")

class Handler(BaseHTTPRequestHandler):
    def send_page(self, code, body):
        raw = body.encode(); self.send_response(code); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/health": self.send_page(200, "ok"); return
        if p.startswith("/approve/"):
            self.send_page(200, "<h1>Shutdown approval</h1><p>Review the request, then explicitly confirm.</p><form method='post'><button>Confirm graceful shutdown</button></form>"); return
        self.send_page(404, "not found")
    def do_POST(self):
        p = urlparse(self.path).path
        if not p.startswith("/approve/"): self.send_page(404, "not found"); return
        ok, msg = approve(p.rsplit("/", 1)[-1]); self.send_page(200 if ok else 410, f"<h1>{html.escape(msg)}</h1>")
    def log_message(self, fmt, *args): log(fmt % args)

def serve():
    log(f"listening on {HOST}:{PORT}; dry_run={DRY_RUN}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    if os.environ.get("MODE") == "server": serve()
    elif os.environ.get("MODE") == "telegram_check": sys.exit(0 if telegram_connectivity_check() else 1)
    else: check_once(os.environ.get("TEST_ALERT", "false").lower() == "true")

