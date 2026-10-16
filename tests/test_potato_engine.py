import json
from datetime import UTC, datetime, timedelta

import pytest

from data_core.providers.weather.open_meteo import FORECAST_URL
from data_core.recommender.potato_engine import soil_moisture_to_raw
from tests.conftest import auth

LAT, LON = -1.2921, 36.8219
ENGINE_URL = "http://engine.test/analyze"
ENGINE_RESPONSE = {
    "diseases": [
        {"name": "Early blight", "probability": 15},
        {"name": "Late blight", "probability": 88},
    ],
    "recommendation": {
        "summary": "Cool, very wet conditions strongly indicate late blight.",
        "actions": [
            {"action": "apply_fungicide", "detail": "Spray a late-blight fungicide now."},
            {"action": "no_change", "detail": "Not applicable."},
        ],
    },
    "input": {"wetness_readings": 72},
}


def _open_meteo_payload(now: datetime) -> dict:
    today = now.date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(31, -1, -1)]  # 31 past days + today
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=80)
    hours = [start + timedelta(hours=h) for h in range(90)]
    return {
        "daily": {"time": days, "temperature_2m_mean": [15.0 + i % 5 for i in range(len(days))]},
        "hourly": {"time": [h.strftime("%Y-%m-%dT%H:%M") for h in hours], "soil_moisture_0_to_1cm": [0.38] * len(hours)},
    }


@pytest.fixture
def engine(make_client, webhooks):
    client = make_client(mocks={"recommender": False}, recommender_url=ENGINE_URL)
    webhooks.get(FORECAST_URL, name="open_meteo").respond(200, json=_open_meteo_payload(datetime.now(UTC)))
    webhooks.post(ENGINE_URL, name="engine").respond(200, json=ENGINE_RESPONSE)
    return client, webhooks


def test_call_is_translated_for_the_engine(engine):
    client, router = engine
    r = client.post(
        "/v1/requests",
        json={"text": "Dark patches on leaves", "crop": "potato", "symptoms": ["white fuzz"], "lat": LAT, "lon": LON},
        headers=auth("input"),
    )
    assert r.status_code == 201

    sent = json.loads(router["engine"].calls.last.request.content)
    assert len(sent["temperatures"]) == 30
    assert sent["temperatures"][-1]["date"] < datetime.now(UTC).date().isoformat()
    assert sent["wetness_hourly"] and all(120 <= w["value"] <= 3600 for w in sent["wetness_hourly"])
    assert sent["plant_description"] == "Dark patches on leaves Crop: potato. Symptoms: white fuzz."

    rec = r.json()["recommendation"]
    assert rec["disease"] == "Late blight"
    assert rec["confidence"] == 0.88
    assert rec["risk_level"] == "high"
    assert rec["explanation"].startswith("Cool, very wet")
    assert rec["actions"] == ["Spray a late-blight fungicide now."]


def test_nearby_soil_sensor_is_the_current_reading(engine):
    client, router = engine
    recorded = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=10)
    reading = {
        "sensor_id": "pi-soil-01",
        "recorded_at": recorded.isoformat(),
        "lat": LAT + 0.005,
        "lon": LON,
        "metrics": {"soil_wetness_raw": 3400},
    }
    assert client.post("/v1/sensor-readings", json=reading, headers=auth("pi")).status_code == 201

    r = client.post("/v1/requests", json={"text": "Wilting", "lat": LAT, "lon": LON}, headers=auth("input"))
    assert r.status_code == 201
    last = json.loads(router["engine"].calls.last.request.content)["wetness_hourly"][-1]
    assert last["value"] == 3400
    assert datetime.fromisoformat(last["timestamp"]) == recorded


def test_call_without_location_fails_recommendation(engine):
    client, router = engine
    r = client.post("/v1/requests", json={"text": "Spots on leaves"}, headers=auth("input"))
    assert r.status_code == 202
    assert r.json()["status"] == "failed_recommend"
    assert "location" in r.json()["last_error"]
    assert not router["engine"].called


@pytest.mark.parametrize(("m3m3", "raw"), [(0.05, 120), (0.10, 120), (0.20, 850), (0.35, 2500), (0.50, 3600)])
def test_soil_moisture_mapping(m3m3, raw):
    assert soil_moisture_to_raw(m3m3) == raw
