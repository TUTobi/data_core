"""config.yaml switchboard: mocked=true uses/accepts mocks, mocked=false is strictly real
(rejects incoming mock data with 422, ignores existing mock records, fails without real config)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_core.config import Settings
from data_core.main import create_app
from data_core.runtime_config import RuntimeConfigError, load_runtime_config
from tests.conftest import auth, write_config

LAT, LON = -1.2921, 36.8219
REPO_ROOT = Path(__file__).resolve().parents[1]


def _reading(sensor_id: str, quality: str, hours_ago: int = 1) -> dict:
    return {
        "sensor_id": sensor_id,
        "recorded_at": (datetime.now(UTC) - timedelta(hours=hours_ago)).replace(microsecond=0).isoformat(),
        "lat": LAT,
        "lon": LON,
        "metrics": {"humidity_pct": 90.0},
        "quality": quality,
    }


def _call(client, text: str, channel: str = "phone_call", **extra) -> dict:
    body = {"text": text, "channel": channel, "problem_type": "crop_health", "lat": LAT, "lon": LON, **extra}
    r = client.post("/v1/requests", json=body, headers=auth("input"))
    assert r.status_code == 201, r.text
    return r.json()


# --- loading ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["config.yaml", "config.docker.yaml"])
def test_shipped_config_files_are_valid(name):
    runtime = load_runtime_config(str(REPO_ROOT / name))
    assert runtime.planner.strategy == "fetch_all"


def test_unknown_key_missing_component_and_missing_file_fail(tmp_path):
    typo = tmp_path / "typo.yaml"
    typo.write_text(Path(write_config(tmp_path / "ok.yaml")).read_text() + "wheather: {mocked: true}\n")
    with pytest.raises(RuntimeConfigError, match="wheather"):
        load_runtime_config(str(typo))

    incomplete = tmp_path / "incomplete.yaml"
    incomplete.write_text("weather: {mocked: true}\n")
    with pytest.raises(RuntimeConfigError, match="recommender"):
        load_runtime_config(str(incomplete))

    with pytest.raises(RuntimeConfigError, match="not found"):
        load_runtime_config(str(tmp_path / "nope.yaml"))


def test_real_recommender_without_url_fails_at_startup(settings, tmp_path):
    cfg = write_config(tmp_path / "real_rec.yaml", recommender=False)
    with pytest.raises(RuntimeConfigError, match="RECOMMENDER_URL"):
        create_app(settings.model_copy(update={"config_file": cfg, "recommender_url": ""}))


def test_config_path_from_env(monkeypatch, tmp_path):
    cfg = write_config(tmp_path / "from_env.yaml")
    monkeypatch.setenv("DATA_CORE_CONFIG", cfg)
    assert Settings(_env_file=None).config_file == cfg


def test_health_reports_flags(client):
    mocks = client.get("/health").json()["mocks"]
    assert mocks == {
        "weather": True,
        "geocoding": True,
        "sensors": True,
        "caller_requests": True,
        "recommender": True,
        "delivery": False,
        "planner": "fetch_all",
    }


# --- sensors ---------------------------------------------------------------------------------------------


def test_sensors_not_mocked_rejects_and_ignores_mock_readings(make_client, webhooks):
    mocked_ok = make_client()  # sensors.mocked=true: mock readings accepted
    assert mocked_ok.post("/v1/sensor-readings", json=_reading("sim", "mocked"), headers=auth("pi")).status_code == 201

    strict = make_client(mocks={"sensors": False})  # same DB, sensors.mocked=false
    r = strict.post("/v1/sensor-readings", json=_reading("sim", "mocked", hours_ago=2), headers=auth("pi"))
    assert r.status_code == 422 and "sensors.mocked=false" in r.text
    assert strict.post("/v1/sensor-readings", json=_reading("real", "ok"), headers=auth("pi")).status_code == 201

    case = _call(strict, "Leaves wilting")
    ctx = strict.get(f"/v1/cases/{case['id']}/context", headers=auth("dashboard")).json()
    assert {s["sensor_id"] for s in ctx["evidence"]["sensors"]} == {"real"}
    assert "Some sensor data is mocked" not in ctx["warnings"]

    obs = strict.get("/v1/observations", params={"lat": LAT, "lon": LON}, headers=auth("dashboard")).json()
    assert {o["sensor_id"] for o in obs["sensors"]} == {"real"}
    # with sensors mocked, the simulator data is visible again
    obs = mocked_ok.get("/v1/observations", params={"lat": LAT, "lon": LON}, headers=auth("dashboard")).json()
    assert {o["sensor_id"] for o in obs["sensors"]} == {"real", "sim"}


# --- caller requests ---------------------------------------------------------------------------------------


def test_caller_requests_not_mocked_rejects_and_hides_demo_calls(make_client, webhooks):
    demo_ok = make_client()
    demo = _call(demo_ok, "Demo: aphids", channel="demo")
    assert demo["request"]["channel"] == "demo"
    _call(demo_ok, "Demo via extra flag", extra={"demo": True})

    strict = make_client(mocks={"caller_requests": False})
    r = strict.post("/v1/requests", json={"text": "x", "channel": "demo"}, headers=auth("input"))
    assert r.status_code == 422 and "caller_requests.mocked=false" in r.text
    r = strict.post("/v1/requests", json={"text": "x", "extra": {"demo": True}}, headers=auth("input"))
    assert r.status_code == 422

    real = _call(strict, "Real: leaves turning yellow")
    listed = strict.get("/v1/cases", headers=auth("dashboard")).json()
    assert [c["id"] for c in listed["items"]] == [real["id"]] and listed["total"] == 1
    assert strict.get("/v1/stats/summary", headers=auth("dashboard")).json()["total_calls"] == 1
    ctx = strict.get(f"/v1/cases/{real['id']}/context", headers=auth("dashboard")).json()
    assert ctx["evidence"]["caller_history"]["total_count"] == 0

    # with caller_requests mocked, the demo calls are visible and labelled
    assert demo_ok.get("/v1/cases", headers=auth("dashboard")).json()["total"] == 3
    later = _call(demo_ok, "Another real call")
    ctx = demo_ok.get(f"/v1/cases/{later['id']}/context", headers=auth("dashboard")).json()
    assert any(r["is_mock"] for r in ctx["evidence"]["caller_history"]["items"])
    assert "Some previous reports are demo/mock data" in ctx["warnings"]


# --- delivery / recommender / geocoding ------------------------------------------------------------------


def test_mocked_delivery_makes_no_http_calls(make_client, webhooks):
    client = make_client(mocks={"delivery": True})
    case = _call(client, "Leaf spots")
    assert case["status"] == "delivered"
    assert {(d["channel"], d["status"]) for d in case["deliveries"]} == {("dashboard", "sent"), ("phone", "sent")}
    assert webhooks.calls.call_count == 0


def test_mocked_recommender_and_gazetteer_are_labelled(make_client, webhooks):
    client = make_client()
    r = client.post(
        "/v1/requests", json={"text": "Spots on beans", "village": "Kiambu"}, headers=auth("input")
    ).json()
    assert r["request"]["location_source"] == "geocoded" and r["request"]["lat"] == pytest.approx(-1.1714)
    ctx = client.get(f"/v1/cases/{r['id']}/context", headers=auth("dashboard")).json()
    assert "Recommendation is mocked (built-in heuristic, not a disease model)" in ctx["warnings"]
    assert any("mock gazetteer" in w for w in ctx["warnings"])
