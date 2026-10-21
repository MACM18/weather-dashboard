from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def build_payload(
    open_meteo: dict[str, Any] | None,
    openweather: dict[str, Any] | None,
    warnings: list[str] | None,
    decision: str = "no_alert",
    alert_reason: str | None = None,
    alert_detail: str | None = None,
    telegram_status: str | None = None,
    telegram_detail: str | None = None,
    next_eligible_at: str | None = None,
    endpoint_errors: dict[str, str] | None = None,
    warning_response: str | bytes | None = None,
) -> dict[str, Any]:
    """Map one monitor cycle, including partial failures, to dashboard input.

    Provider dictionaries may include the full upstream response under
    ``response``. Error entries are recorded as endpoint calls even when no
    provider reading could be produced.
    """
    now = datetime.now(timezone.utc)
    observed_at = now.isoformat()
    errors = endpoint_errors or {}
    endpoint_calls: list[dict[str, Any]] = []
    providers: list[dict[str, Any]] = []

    def add_provider(
        provider: str,
        endpoint: str,
        category: str,
        result: dict[str, Any] | None,
        error_key: str,
    ) -> None:
        error = errors.get(error_key) or (result or {}).get("error")
        if result is None and error is None:
            return
        response_data = (result or {}).get("response", result or {})
        endpoint_calls.append({
            "category": category,
            "endpoint": endpoint,
            "called_at": observed_at,
            "status": "error" if error else "success",
            "summary": f"{endpoint} request failed: {error}" if error else f"{endpoint} response payload",
            "response_data": {"error": error} if error and result is None else response_data,
        })
        if result is None:
            return

        current = result.get("current", {})
        if provider == "open_meteo":
            providers.append({
                "provider": provider,
                "observed_at": observed_at,
                "temperature_c": current.get("temperature_2m"),
                "precipitation_mm": result.get("rain"),
                "precipitation_probability": result.get("probability"),
                "wind_speed": current.get("wind_speed_10m"),
                "weather_code": current.get("weather_code"),
                "thunder": result.get("thunder", False),
                "error": error,
            })
        else:
            weather = (current.get("weather") or [{}])[0]
            providers.append({
                "provider": provider,
                "observed_at": observed_at,
                "temperature_c": current.get("temp"),
                "precipitation_mm": result.get("rain"),
                "precipitation_probability": result.get("probability"),
                "wind_speed": current.get("wind_speed"),
                "weather_code": weather.get("id"),
                "thunder": result.get("thunder", False),
                "error": error,
            })

    add_provider("open_meteo", "Open-Meteo forecast", "weather provider", open_meteo, "open_meteo")
    add_provider("openweather", "OpenWeather One Call timeline", "weather provider", openweather, "openweather")

    warnings_error = errors.get("official_warnings")
    if warnings is not None or warnings_error or warning_response is not None:
        warning_items = warnings or []
        warning_body: dict[str, Any] = {"warnings": warning_items}
        if warning_response is not None:
            warning_body["raw_response"] = warning_response.decode("utf-8", errors="replace") if isinstance(warning_response, bytes) else warning_response
        endpoint_calls.append({
            "category": "official warnings",
            "endpoint": "Sri Lanka weather warnings",
            "called_at": observed_at,
            "status": "error" if warnings_error else "success",
            "summary": f"Warning feed request failed: {warnings_error}" if warnings_error else f"{len(warning_items)} active warning(s) returned",
            "response_data": {"error": warnings_error} if warnings_error else warning_body,
        })

    return {
        "run_key": f"weather-{int(now.timestamp() * 1000000)}",
        "observed_at": observed_at,
        "decision": decision,
        "endpoint_calls": endpoint_calls,
        "providers": providers,
        "official_warnings": warnings or [],
        "alert_reason": alert_reason,
        "alert_detail": alert_detail,
        "telegram_status": telegram_status,
        "telegram_detail": telegram_detail,
        "next_eligible_at": next_eligible_at,
    }
