"""Open-Meteo (https://open-meteo.com): free, no API key, recent past + forecast in one call."""

import math
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from data_core.providers.weather.base import summarize_window
from data_core.schemas.context import WeatherEvidence
from data_core.timeutil import utcnow

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY = ["temperature_2m", "relative_humidity_2m", "precipitation", "soil_moisture_0_to_1cm"]
CURRENT = ["temperature_2m", "relative_humidity_2m", "precipitation", "wind_speed_10m"]
DAILY = ["temperature_2m_max", "temperature_2m_min", "precipitation_sum"]


class OpenMeteoProvider:
    name = "open_meteo"

    def __init__(self, http: httpx.Client, timeout_s: float):
        self.http = http
        self.timeout_s = timeout_s

    def get(self, lat: float, lon: float, past_h: int, forecast_h: int) -> WeatherEvidence:
        params = {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(HOURLY),
            "current": ",".join(CURRENT),
            "daily": ",".join(DAILY),
            "past_days": min(92, max(0, math.ceil(past_h / 24))),
            "forecast_days": min(16, max(1, math.ceil(forecast_h / 24) + 1)),
            "timezone": "GMT",
        }
        resp = self._get_with_retry(params)
        return parse_forecast(resp.json(), lat, lon, past_h, forecast_h, now=utcnow())

    def _get_with_retry(self, params: dict, attempts: int = 3, backoff_s: float = 0.5) -> httpx.Response:
        """Open-Meteo occasionally answers 503/429; retry briefly before giving up (caller reports a gap)."""
        for attempt in range(1, attempts + 1):
            last_attempt = attempt == attempts
            try:
                resp = self.http.get(FORECAST_URL, params=params, timeout=self.timeout_s)
            except httpx.TransportError:
                if last_attempt:
                    raise
            else:
                transient = resp.status_code >= 500 or resp.status_code == 429
                if not transient or last_attempt:
                    resp.raise_for_status()
                    return resp
            time.sleep(backoff_s * attempt)
        raise AssertionError("unreachable")


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def parse_forecast(
    payload: dict[str, Any], lat: float, lon: float, past_h: int, forecast_h: int, now: datetime
) -> WeatherEvidence:
    hourly = payload.get("hourly") or {}
    times = [_ts(t) for t in hourly.get("time", [])]
    rows = [{"time": t, **{k: (hourly.get(k) or [None] * len(times))[i] for k in HOURLY}} for i, t in enumerate(times)]
    past = [r for r in rows if now - timedelta(hours=past_h) <= r["time"] <= now]
    future = [r for r in rows if now < r["time"] <= now + timedelta(hours=forecast_h)]

    daily_raw = payload.get("daily") or {}
    daily = [
        {"date": d, **{k: (daily_raw.get(k) or [None] * len(daily_raw["time"]))[i] for k in DAILY}}
        for i, d in enumerate(daily_raw.get("time", []))
    ]
    current = {k: v for k, v in (payload.get("current") or {}).items() if k not in ("time", "interval")}

    return WeatherEvidence(
        provider=OpenMeteoProvider.name,
        lat=payload.get("latitude", lat),
        lon=payload.get("longitude", lon),
        fetched_at=now,
        current=current,
        past=summarize_window(past, past_h),
        forecast=summarize_window(future, forecast_h),
        daily=daily,
    )
