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


def test_observations_return_latest_reading_regardless_of_location(client):
    far_newest = _reading("far", hours_ago=1, lat=None, lon=None, humidity_pct=91.0, rain_mm=0.5)
    client.post(
        "/v1/sensor-readings",
        json={"readings": [_reading("near", hours_ago=2), _reading("near", hours_ago=500), far_newest]},
        headers=auth("pi"),
    )
    params = {"lat": -1.29, "lon": 36.83, "radius_km": 5, "since_h": 72, "include_weather": True}
    r = client.get("/v1/observations", params=params, headers=auth("dashboard"))
    assert r.status_code == 200
    body = r.json()
    assert [(o["sensor_id"], o["metric"], o["value"]) for o in body["sensors"]] == [
        ("far", "humidity_pct", 91.0),
        ("far", "rain_mm", 0.5),
    ]
    assert body["sensors"][0]["unit"] == "%" and body["sensors"][0]["distance_km"] is None
    assert body["weather"]["provider"] == "mock"

    # `metric` picks the newest reading of that metric, wherever and whenever it was recorded.
    r = client.get("/v1/observations", params={**params, "metric": "rain_mm"}, headers=auth("dashboard"))
    assert [(o["sensor_id"], o["metric"]) for o in r.json()["sensors"]] == [("far", "rain_mm")]
