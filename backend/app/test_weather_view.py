import sys
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "app"))
sys.path.insert(0, str(ROOT / "integration"))

from weather_view import build_overview, condition_for
from weather_monitor_payload import build_payload

spec = importlib.util.spec_from_file_location("weather_shutdown_under_test", ROOT / "integration" / "weather_shutdown.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


class WeatherOverviewTests(unittest.TestCase):
    def test_condition_mapping_handles_wmo_and_openweather(self):
        self.assertEqual(condition_for(95), ("thunder", "Thunderstorms"))
        self.assertEqual(condition_for(3), ("clouds", "Overcast"))
        self.assertEqual(condition_for(800, "openweather"), ("clear", "Clear sky"))
        self.assertEqual(condition_for(721, "openweather")[0], "fog")
        self.assertEqual(condition_for(97)[0], "thunder")

    def test_overview_exposes_current_details_forecast_and_daylight(self):
        now = datetime(2026, 10, 21, 8, tzinfo=timezone.utc)
        observed = now.isoformat()
        response = {
            "current": {"temperature_2m": 29.4, "apparent_temperature": 34, "relative_humidity_2m": 75, "is_day": 1},
            "hourly": {"time": ["2026-10-21T14:00", "2026-10-21T15:00"], "temperature_2m": [29, 28], "precipitation_probability": [35, 70], "precipitation": [0.2, 1.1], "weather_code": [2, 61]},
        }
        reading = {"provider": "open_meteo", "observed_at": observed, "temperature_c": 29.4, "weather_code": 2, "wind_speed": 3, "precipitation_mm": 1.1, "precipitation_probability": 70}
        result = build_overview([reading], [{"endpoint": "Open-Meteo forecast", "status": "success", "response_data": response}], [], now)
        self.assertTrue(result["available"])
        self.assertEqual(result["freshness"], "fresh")
        self.assertEqual(result["condition"], "Partly cloudy")
        self.assertTrue(result["is_day"])
        self.assertEqual(result["feels_like_c"], 34)
        self.assertEqual(result["forecast"][1]["condition_key"], "rain")

    def test_stale_and_openweather_fallback(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(minutes=31)).isoformat()
        reading = {"provider": "openweather", "observed_at": old, "temperature_c": 27, "weather_code": 801, "wind_speed": 2}
        payload = {"current": {"temp": 27, "feels_like": 30, "humidity": 80, "weather": [{"icon": "02n"}]}, "data": []}
        result = build_overview([reading], [{"endpoint": "Open-Meteo forecast", "status": "error", "response_data": {}}, {"endpoint": "OpenWeather One Call timeline", "status": "success", "response_data": payload}], [], now)
        self.assertEqual(result["source"], "openweather")
        self.assertEqual(result["freshness"], "stale")
        self.assertFalse(result["is_day"])
        self.assertEqual(result["humidity_percent"], 80)

    def test_endpoint_payload_keeps_full_provider_and_warning_responses(self):
        meteo = {"current": {"temperature_2m": 28}, "hourly": {"time": ["2026-10-21T12:00"]}, "metadata": {"model": "test"}}
        raw_rss = "<rss><channel><title>Official feed</title></channel></rss>"
        result = build_payload({"current": meteo["current"], "response": meteo}, None, [], warning_response=raw_rss)
        calls = {call["category"]: call for call in result["endpoint_calls"]}
        self.assertEqual(calls["weather provider"]["response_data"], meteo)
        self.assertEqual(calls["official warnings"]["response_data"]["raw_response"], raw_rss)

    def test_future_forecast_skips_past_hours_and_crosses_midnight(self):
        local_now = datetime(2026, 10, 21, 22, 30, tzinfo=ZoneInfo("Asia/Colombo"))
        stamps = [(datetime(2026, 10, 21, tzinfo=ZoneInfo("Asia/Colombo")) + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(36)]
        hourly = {"time": stamps, "temperature_2m": list(range(36)), "precipitation_probability": list(range(36)), "precipitation": [0] * 36, "weather_code": [0] * 36}
        self.assertEqual(monitor.future_meteo_indices(hourly, 6, local_now), [23, 24, 25, 26, 27, 28])
        reading = {"provider": "open_meteo", "observed_at": local_now.isoformat(), "temperature_c": 29, "weather_code": 0}
        result = build_overview([reading], [{"endpoint": "Open-Meteo forecast", "status": "success", "response_data": {"current": {"is_day": 0}, "hourly": hourly}}], [], local_now.astimezone(timezone.utc))
        self.assertEqual(len(result["forecast"]), 12)
        self.assertEqual(result["forecast"][0]["time"], "2026-10-21T23:00:00+05:30")
        self.assertEqual(result["forecast"][-1]["time"], "2026-10-22T10:00:00+05:30")

    def test_openweather_forecast_uses_future_rows_only(self):
        now = datetime(2026, 10, 21, 12, 30, tzinfo=timezone.utc)
        rows = [{"dt": int((now + timedelta(hours=offset)).timestamp()), "temp": 27, "pop": .5, "weather": [{"id": 500, "icon": "10n"}]} for offset in range(-2, 14)]
        reading = {"provider": "openweather", "observed_at": now.isoformat(), "temperature_c": 27, "weather_code": 500}
        result = build_overview([reading], [{"endpoint": "OpenWeather One Call timeline", "status": "success", "response_data": {"data": rows}}], [], now)
        self.assertEqual(len(result["forecast"]), 12)
        self.assertEqual(result["forecast"][0]["time"], (now + timedelta(hours=1)).isoformat())
        self.assertFalse(result["is_day"])

    def test_delivery_status_cooldown_and_retry(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(monitor, "DATA_DIR", temporary), patch.object(monitor, "DB", str(Path(temporary) / "state.sqlite3")), patch.object(monitor, "COOLDOWN", 1800), patch.object(monitor, "telegram") as send:
            with patch.object(monitor.time, "time", return_value=1000):
                first = monitor.create_alert("storm", "forecast")
            self.assertEqual(first["status"], "accepted_by_telegram")
            with patch.object(monitor.time, "time", return_value=2799):
                suppressed = monitor.create_alert("storm", "forecast")
            self.assertEqual(suppressed["status"], "suppressed_by_cooldown")
            self.assertEqual(send.call_count, 1)
            with patch.object(monitor.time, "time", return_value=2800):
                reminder = monitor.create_alert("storm", "forecast")
            self.assertEqual(reminder["status"], "accepted_by_telegram")
            send.side_effect = TimeoutError("secret URL should not be logged")
            with patch.object(monitor.time, "time", return_value=4600):
                failed = monitor.create_alert("new warning", "forecast")
            self.assertEqual(failed["status"], "failed")
            self.assertNotIn("secret", failed["detail"])
            send.side_effect = None
            with patch.object(monitor.time, "time", return_value=4601):
                retry = monitor.create_alert("new warning", "forecast")
            self.assertEqual(retry["status"], "accepted_by_telegram")

    def test_connectivity_check_contains_no_approval_link(self):
        with patch.object(monitor, "telegram") as send:
            self.assertTrue(monitor.telegram_connectivity_check())
        self.assertNotIn("/approve/", send.call_args.args[0])

    def test_delivery_outcome_is_in_dashboard_payload(self):
        eligible = "2026-10-21T09:00:00+00:00"
        payload = build_payload(None, None, [], alert_reason="storm", telegram_status="accepted_by_telegram", telegram_detail="Telegram API accepted the alert message.", next_eligible_at=eligible)
        self.assertEqual(payload["telegram_status"], "accepted_by_telegram")
        self.assertEqual(payload["next_eligible_at"], eligible)

    def test_alert_attempt_happens_before_dashboard_record(self):
        order = []
        outcome = {"status": "failed", "detail": "Telegram delivery failed (TimeoutError); retry on the next check.", "next_eligible_at": None}
        with patch.object(monitor, "create_alert", side_effect=lambda *_: order.append("telegram") or outcome), patch.object(monitor, "record_dashboard_cycle", side_effect=lambda **_: order.append("dashboard")):
            accepted = monitor.record_alert_cycle("storm", "forecast", "alert")
        self.assertFalse(accepted)
        self.assertEqual(order, ["telegram", "dashboard"])

    def test_thunderstorm_decision_rejects_rain_only_and_unmatched_hours(self):
        hour = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        rain = {"at": hour, "code": 61, "thunder": False, "rain_chance": 100, "rain_mm": 6}
        thunder = {"at": hour, "code": 97, "thunder": True, "rain_chance": 30, "rain_mm": 0}
        self.assertIsNone(monitor.thunderstorm_decision({"hours": [rain]}, {"hours": [rain]}))
        self.assertIsNone(monitor.thunderstorm_decision({"hours": [thunder]}, {"hours": [{**rain, "at": hour + timedelta(hours=3)}]}))
        self.assertIn("Open-Meteo shows a thunderstorm", monitor.thunderstorm_decision({"hours": [thunder]}, {"hours": [rain]})["detail"])
        other_storm = {**thunder, "code": 211}
        self.assertIn("Both forecast services", monitor.thunderstorm_decision({"hours": [thunder]}, {"hours": [other_storm]})["detail"])

    def test_recent_current_thunder_is_considered(self):
        local_now = datetime.now(ZoneInfo("Asia/Colombo"))
        hourly = {"time": [(local_now + timedelta(hours=i + 1)).strftime("%Y-%m-%dT%H:%M") for i in range(6)], "weather_code": [61] * 6, "precipitation": [0] * 6, "precipitation_probability": [20] * 6}
        response = {"current": {"time": local_now.isoformat(timespec="minutes"), "weather_code": 97, "precipitation": 0}, "hourly": hourly}
        with patch.object(monitor, "fetch", return_value=json.dumps(response).encode()):
            result = monitor.weather()
        self.assertTrue(result["thunder"])
        self.assertEqual(result["hours"][0]["code"], 97)

    def test_official_warning_requires_thunder_or_lightning_terms(self):
        rss = b"<rss><channel><item><title>Heavy rain in Kalutara</title></item><item><title>Severe lightning in Kalutara</title></item><item><title>Lightning in Jaffna, Sri Lanka</title></item></channel></rss>"
        with patch.object(monitor, "fetch", return_value=rss), patch.object(monitor, "AREA", "kalutara"):
            all_warnings, saved_feed, thunder_warnings = monitor.official_warnings()
        self.assertEqual(len(all_warnings), 2)
        self.assertEqual(thunder_warnings, ["Severe lightning in Kalutara"])
        self.assertEqual(saved_feed, rss)

    def test_rain_only_cycle_does_not_request_shutdown_approval(self):
        hour = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
        rain = {"at": hour, "code": 61, "thunder": False, "rain_chance": 100, "rain_mm": 6}
        meteo = {"current": {}, "rain": 6, "probability": 100, "thunder": False, "hours": [rain], "response": {}}
        openweather = {"current": {}, "rain": 2, "probability": 100, "thunder": False, "hours": [rain], "alerts": [], "response": {}}
        with patch.object(monitor, "weather", return_value=meteo), patch.object(monitor, "openweather", return_value=openweather), patch.object(monitor, "official_warnings", return_value=([], b"<rss/>", [])), patch.object(monitor, "record_alert_cycle") as alert, patch.object(monitor, "record_dashboard_cycle") as record:
            self.assertFalse(monitor.check_once())
        alert.assert_not_called()
        record.assert_called_once()

    def test_official_lightning_warning_triggers_if_forecast_provider_fails(self):
        with patch.object(monitor, "weather", side_effect=TimeoutError("provider unavailable")), patch.object(monitor, "official_warnings", return_value=(["Severe lightning in Kalutara"], b"<rss/>", ["Severe lightning in Kalutara"])), patch.object(monitor, "openweather") as other, patch.object(monitor, "record_alert_cycle", return_value=True) as alert:
            self.assertTrue(monitor.check_once())
        other.assert_not_called()
        self.assertIn("Official thunderstorm", alert.call_args.args[0])

    def test_telegram_message_uses_html_and_review_button(self):
        with patch.object(monitor, "TELEGRAM_TOKEN", "fake-token"), patch.object(monitor, "TELEGRAM_CHAT_ID", "123"), patch.object(monitor, "fetch_response", return_value=b'{"ok": true}') as fetch:
            monitor.telegram("<b>Thunder risk</b>", approval_url="https://example.test/approve/token")
        body = json.loads(fetch.call_args.args[0].data)
        self.assertEqual(body["parse_mode"], "HTML")
        self.assertEqual(body["reply_markup"]["inline_keyboard"][0][0]["text"], "Review shutdown request")

    def test_alert_copy_escapes_provider_text_and_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(monitor, "DATA_DIR", temporary), patch.object(monitor, "DB", str(Path(temporary) / "state.sqlite3")), patch.object(monitor, "BASE_URL", "https://example.test"), patch.object(monitor, "DRY_RUN", False), patch.object(monitor, "telegram") as send, patch.object(monitor.time, "time", return_value=1000):
            monitor.create_alert("Thunderstorm or lightning risk", "OpenWeather <storm> at 2 PM")
        message = send.call_args.args[0]
        self.assertIn("&lt;storm&gt;", message)
        self.assertIn("only after your confirmation", message)
        self.assertIn("not a detected lightning strike", message)
        self.assertIn("10 minutes", message)
        self.assertTrue(send.call_args.kwargs["approval_url"].startswith("https://example.test/approve/"))


if __name__ == "__main__":
    unittest.main()
