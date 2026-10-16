from datetime import UTC, datetime, timedelta

from tests.conftest import auth


def _reading(sensor_id="pi-01", hours_ago=1, lat=-1.29, lon=36.82, **metrics):
    return {
        "sensor_id": sensor_id,
        "recorded_at": (datetime.now(UTC) - timedelta(hours=hours_ago)).replace(microsecond=0).isoformat(),
        "lat": lat,
        "lon": lon,
        "metrics": metrics or {"humidity_pct": 80.0},
    }


def test_requires_matching_api_key(client):
    body = _reading()
    assert client.post("/v1/sensor-readings", json=body).status_code == 401
    assert client.post("/v1/sensor-readings", json=body, headers=auth("input")).status_code == 401
    assert client.post("/v1/sensor-readings", json=body, headers={"Authorization": "Bearer pi-key"}).status_code == 201


def test_single_and_batch_ingestion_is_idempotent(client):
    single = _reading(humidity_pct=88.0, temperature_c=21.5)
    r = client.post("/v1/sensor-readings", json=single, headers=auth("pi"))
    assert r.status_code == 201
    assert r.json() == {"accepted": 2, "duplicates": 0, "sensors": ["pi-01"]}

    batch = {"readings": [single, _reading(hours_ago=2)]}
    r = client.post("/v1/sensor-readings", json=batch, headers=auth("pi"))
    assert r.json() == {"accepted": 1, "duplicates": 2, "sensors": ["pi-01"]}


def test_sensor_is_auto_registered_with_last_position(client):
    client.post("/v1/sensor-readings", json=_reading(lat=-1.3, lon=36.9), headers=auth("pi"))
    sensors = client.get("/v1/sensors", headers=auth("dashboard")).json()
    assert [(s["id"], s["lat"], s["lon"]) for s in sensors] == [("pi-01", -1.3, 36.9)]
    assert sensors[0]["last_seen_at"].endswith("Z") or "+00:00" in sensors[0]["last_seen_at"]


def test_invalid_metric_name_rejected(client):
    r = client.post("/v1/sensor-readings", json=_reading(**{"Humidity %": 1.0}), headers=auth("pi"))
    assert r.status_code == 422


def test_observations_radius_filter(client):
    client.post(
        "/v1/sensor-readings",
        json={"readings": [_reading("near"), _reading("far", lat=-1.29, lon=37.5)]},
        headers=auth("pi"),
    )
    r = client.get(
        "/v1/observations",
        params={"lat": -1.29, "lon": 36.83, "radius_km": 5, "include_weather": True},
        headers=auth("dashboard"),
    )
    assert r.status_code == 200
    body = r.json()
    assert {o["sensor_id"] for o in body["sensors"]} == {"near"}
    assert body["sensors"][0]["unit"] == "%"
    assert body["weather"]["provider"] == "mock"
