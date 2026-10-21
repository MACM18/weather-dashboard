from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

LOCAL_ZONE = ZoneInfo("Asia/Colombo")


def condition_for(code: int | None, provider: str = "open_meteo") -> tuple[str, str]:
    """Return a compact condition key and human-readable label."""
    if code is None:
        return "unknown", "Weather unavailable"
    try:
        value = int(code)
    except (TypeError, ValueError):
        return "unknown", "Weather unavailable"
    if provider == "openweather":
        if 200 <= value <= 232:
            return "thunder", "Thunderstorms"
        if 300 <= value <= 321:
            return "rain", "Drizzle"
        if 500 <= value <= 531:
            return "rain", "Rain"
        if 600 <= value <= 622:
            return "snow", "Snow"
        if 701 <= value <= 781:
            return "fog", "Hazy conditions"
        if value == 800:
            return "clear", "Clear sky"
        if 801 <= value <= 804:
            return "clouds", "Cloudy"
    else:
        if value == 0:
            return "clear", "Clear sky"
        if value in (1, 2, 3):
            return "clouds", {1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast"}[value]
        if value in (45, 48):
            return "fog", "Foggy"
        if value in (51, 53, 55, 56, 57):
            return "rain", "Drizzle"
        if value in (61, 63, 65, 66, 67, 80, 81, 82):
            return "rain", "Rain"
        if value in (71, 73, 75, 77, 85, 86):
            return "snow", "Snow"
        if value in (95, 96, 97, 99):
            return "thunder", "Thunderstorms"
    return "unknown", "Weather unavailable"


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _hourly_forecast(response: dict[str, Any], source: str, now: datetime) -> list[dict[str, Any]]:
    hourly = response.get("hourly") or {}
    times = hourly.get("time") or []
    if source == "openweather":
        rows = response.get("data") or []
        result = []
        for row in rows:
            try:
                stamp = datetime.fromtimestamp(int(row["dt"]), timezone.utc)
            except (KeyError, TypeError, ValueError):
                continue
            if stamp <= now:
                continue
            weather = (row.get("weather") or [{}])[0]
            key, label = condition_for(weather.get("id"), source)
            result.append({
                "time": stamp.isoformat(),
                "temperature_c": _number(row.get("temp")),
                "precipitation_probability": round((_number(row.get("pop")) or 0) * 100),
                "weather_code": weather.get("id"), "condition": label, "condition_key": key,
            })
            if len(result) == 12:
                break
        return result
    result = []
    for index, stamp in enumerate(times):
        try:
            local_stamp = datetime.fromisoformat(stamp)
            if local_stamp.tzinfo is None:
                local_stamp = local_stamp.replace(tzinfo=LOCAL_ZONE)
        except (TypeError, ValueError):
            continue
        if local_stamp <= now:
            continue
        def item(name):
            values = hourly.get(name) or []
            return values[index] if index < len(values) else None
        code = item("weather_code")
        key, label = condition_for(code)
        result.append({
            "time": local_stamp.isoformat(),
            "temperature_c": _number(item("temperature_2m")),
            "precipitation_probability": _number(item("precipitation_probability")),
            "precipitation_mm": _number(item("precipitation")),
            "weather_code": code, "condition": label, "condition_key": key,
        })
        if len(result) == 12:
            break
    return result


def build_overview(readings: list[dict[str, Any]], calls: list[dict[str, Any]], warnings: list[str], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    readings_by_provider = {row["provider"]: row for row in readings}
    meteo_call = next((row for row in calls if "open-meteo" in row["endpoint"].lower()), None)
    ow_call = next((row for row in calls if "openweather" in row["endpoint"].lower()), None)
    source_call = meteo_call if meteo_call and meteo_call["status"] == "success" else ow_call
    provider = "open_meteo" if source_call is meteo_call and source_call else "openweather"
    reading = readings_by_provider.get(provider)
    if reading is None or source_call is None:
        return {"available": False, "freshness": "unavailable", "message": "Waiting for the first successful weather check.", "forecast": [], "warnings": warnings, "source": None}
    raw = source_call.get("response_data") or {}
    current = raw.get("current") or ((raw.get("data") or [{}])[0] if provider == "openweather" else {})
    code = reading.get("weather_code")
    key, label = condition_for(code, provider)
    observed = reading.get("observed_at")
    if isinstance(observed, str):
        observed = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    age = max(0, int((now - observed).total_seconds())) if observed else None
    freshness = "fresh" if age is not None and age <= 20 * 60 else "stale"
    if provider == "open_meteo":
        feels_like = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        is_day = current.get("is_day")
        hourly = _hourly_forecast(raw, provider, now)
    else:
        feels_like = current.get("feels_like")
        humidity = current.get("humidity")
        icon = (current.get("weather") or [{}])[0].get("icon", "")
        is_day = icon.endswith("d") if icon else None
        hourly = _hourly_forecast(raw, provider, now)
    local_now = now.astimezone(LOCAL_ZONE)
    if is_day is None:
        is_day = 6 <= local_now.hour < 18
    return {
        "available": True,
        "freshness": freshness,
        "age_seconds": age,
        "observed_at": observed,
        "location": "Horana, Sri Lanka",
        "timezone": "Asia/Colombo",
        "source": provider,
        "condition": label,
        "condition_key": key,
        "is_day": bool(is_day),
        "temperature_c": reading.get("temperature_c"),
        "feels_like_c": _number(feels_like),
        "humidity_percent": _number(humidity),
        "wind_speed": reading.get("wind_speed"),
        "precipitation_probability": reading.get("precipitation_probability"),
        "precipitation_mm": reading.get("precipitation_mm"),
        "forecast": hourly,
        "warnings": warnings,
    }
