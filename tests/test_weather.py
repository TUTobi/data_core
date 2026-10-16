from datetime import UTC, datetime, timedelta

import httpx
import respx
from sqlalchemy.orm import Session

from data_core.db.base import Base
from data_core.db.session import make_engine
from data_core.providers.weather.cached import fetch_weather_cached
from data_core.providers.weather.open_meteo import FORECAST_URL, OpenMeteoProvider, parse_forecast

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)


def _payload(past_h=72, forecast_h=48):
    times = [NOW + timedelta(hours=h) for h in range(-past_h, forecast_h + 1)]
    return {
        "latitude": -1.29,
        "longitude": 36.82,
        "current": {"time": "2026-10-16T12:00", "interval": 900, "temperature_2m": 21.3, "relative_humidity_2m": 88},
        "hourly": {
            "time": [t.strftime("%Y-%m-%dT%H:%M") for t in times],
            "temperature_2m": [20.0 if t <= NOW else 25.0 for t in times],
            "relative_humidity_2m": [95 if t <= NOW else 60 for t in times],
            "precipitation": [0.5 if t <= NOW else 0.0 for t in times],
            "soil_moisture_0_to_1cm": [0.3] * len(times),
        },
        "daily": {"time": ["2026-10-16"], "temperature_2m_max": [26.0], "temperature_2m_min": [15.0], "precipitation_sum": [4.2]},
    }


def test_parse_forecast_splits_past_and_future():
    ev = parse_forecast(_payload(), -1.29, 36.82, past_h=72, forecast_h=48, now=NOW)
    assert ev.past.n_points == 73  # inclusive window [now-72h, now]
    assert ev.past.precipitation_mm == 36.5
    assert ev.past.hours_rh_ge_90 == 73
    assert ev.past.mean_temp_c == 20.0
    assert ev.forecast.n_points == 48
    assert ev.forecast.mean_rh_pct == 60
    assert ev.current == {"temperature_2m": 21.3, "relative_humidity_2m": 88}
    assert ev.daily[0]["precipitation_sum"] == 4.2


def test_open_meteo_request_and_db_cache(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}")
    Base.metadata.create_all(engine)
    with respx.mock() as router, httpx.Client() as http, Session(engine) as session:
        route = router.get(FORECAST_URL).respond(200, json=_payload())
        provider = OpenMeteoProvider(http, timeout_s=5)

        first = fetch_weather_cached(session, provider, -1.2921, 36.8219, 72, 48, ttl_s=900)
        second = fetch_weather_cached(session, provider, -1.2939, 36.8201, 72, 48, ttl_s=900)  # same ~1 km cell

        assert route.call_count == 1
        params = route.calls.last.request.url.params
        assert params["past_days"] == "3" and params["latitude"] == "-1.29"
        assert first.from_cache is False and second.from_cache is True
        assert second.past == first.past


def test_open_meteo_retries_transient_errors(monkeypatch):
    monkeypatch.setattr("data_core.providers.weather.open_meteo.time.sleep", lambda _s: None)
    with respx.mock() as router, httpx.Client() as http:
        route = router.get(FORECAST_URL).mock(
            side_effect=[httpx.Response(503), httpx.Response(429), httpx.Response(200, json=_payload())]
        )
        ev = OpenMeteoProvider(http, timeout_s=5).get(-1.29, 36.82, 72, 48)
        assert route.call_count == 3
        assert ev.provider == "open_meteo"


def test_open_meteo_does_not_retry_client_errors():
    with respx.mock() as router, httpx.Client() as http:
        route = router.get(FORECAST_URL).respond(400)
        try:
            OpenMeteoProvider(http, timeout_s=5).get(-1.29, 36.82, 72, 48)
        except httpx.HTTPStatusError:
            pass
        assert route.call_count == 1
