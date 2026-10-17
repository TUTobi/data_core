import math
from datetime import timedelta

from data_core.providers.weather.base import summarize_window
from data_core.schemas.context import WeatherEvidence
from data_core.timeutil import utcnow


class MockWeatherProvider:
    """Deterministic, humid synthetic weather for offline development and tests."""

    name = "mock"

    def get(self, lat: float, lon: float, past_h: int, forecast_h: int) -> WeatherEvidence:
        now = utcnow().replace(minute=0, second=0, microsecond=0)
        rows = []
        for h in range(-past_h + 1, forecast_h + 1):
            t = now + timedelta(hours=h)
            phase = math.sin(t.hour / 24 * 2 * math.pi)
            rows.append(
                {
                    "time": t,
                    "temperature_2m": round(22 + 6 * phase, 1),
                    "relative_humidity_2m": round(min(100.0, 82 - 12 * phase), 1),
                    "precipitation": 1.5 if h <= 0 and t.hour in (14, 15, 16) else 0.0,
                    "soil_moisture_0_to_1cm": 0.32,
                }
            )
        past = [r for r in rows if r["time"] <= now]
        future = [r for r in rows if r["time"] > now]
        return WeatherEvidence(
            provider=self.name,
            lat=lat,
            lon=lon,
            fetched_at=utcnow(),
            current={k: v for k, v in past[-1].items() if k != "time"},
            past=summarize_window(past, past_h),
            forecast=summarize_window(future, forecast_h),
            hourly=[{**r, "time": r["time"].isoformat()} for r in rows],
        )
