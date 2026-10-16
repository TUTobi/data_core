import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from data_core.db.models import OutboxEvent
from data_core.delivery.outbox import sign
from data_core.timeutil import utcnow
from tests.conftest import WEBHOOK_SECRET, auth

LAT, LON = -1.2921, 36.8219


def _post_humid_readings(client, n_hours=6):
    now = datetime.now(UTC).replace(microsecond=0)
    readings = [
        {
            "sensor_id": "pi-field-01",
            "recorded_at": (now - timedelta(hours=h)).isoformat(),
            "lat": LAT + 0.005,
            "lon": LON,
            "metrics": {"humidity_pct": 93.0, "temperature_c": 21.0},
        }
        for h in range(1, n_hours + 1)
    ]
    r = client.post("/v1/sensor-readings", json={"readings": readings}, headers=auth("pi"))
    assert r.status_code == 201


def test_end_to_end_request_to_delivery(client, webhooks):
    _post_humid_readings(client)
    previous = client.post(
        "/v1/requests",
        json={"text": "Brown spots on leaves", "problem_type": "crop_health", "location": {"lat": LAT + 0.01, "lon": LON}},
        headers=auth("input"),
    )
    assert previous.status_code == 201

    # Overview-style payload (aliases) with an idempotency key.
    payload = {
        "external_id": "call-42",
        "problem_type": "crop_health",
        "description": "Crops started dying after heavy rainfall",
        "latitude": LAT,
        "longitude": LON,
        "source": "phone_call",
    }
    r = client.post("/v1/requests", json=payload, headers=auth("input"))
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["status"] == "delivered"
    assert case["request"]["channel"] == "phone_call"
    assert case["recommendation"]["risk_level"] in {"medium", "high"}
    assert {(d["channel"], d["status"]) for d in case["deliveries"]} == {("dashboard", "sent"), ("phone", "sent")}

    ctx = client.get(f"/v1/cases/{case['id']}/context", headers=auth("dashboard")).json()
    assert ctx["plan"]["strategy"] == "fetch_all"
    assert {s["metric"] for s in ctx["evidence"]["sensors"]} == {"humidity_pct", "temperature_c"}
    assert ctx["evidence"]["sensors"][0]["distance_km"] < 1
    assert ctx["evidence"]["caller_history"]["total_count"] == 1
    assert ctx["evidence"]["caller_history"]["same_problem_count"] == 1
    assert ctx["evidence"]["weather"]["provider"] == "mock"
    assert "Weather data is mocked" in ctx["warnings"]

    # Webhooks are signed with HMAC-SHA256 over the raw body.
    call = webhooks["dashboard"].calls.last
    assert call.request.headers["X-DataCore-Signature"] == sign(WEBHOOK_SECRET, call.request.content)
    body = json.loads(call.request.content)
    assert body["event"] == "case.recommended" and body["external_id"] == "call-42"
    assert body["evidence_summary"]

    # Same external_id again -> existing case, no reprocessing.
    again = client.post("/v1/requests", json=payload, headers=auth("input"))
    assert again.status_code == 200 and again.json()["id"] == case["id"]

    listed = client.get("/v1/cases", params={"problem_type": "crop_health"}, headers=auth("dashboard")).json()
    assert listed["total"] == 2


def test_request_without_location_reports_gap(client, webhooks):
    r = client.post("/v1/requests", json={"text": "My goats are coughing"}, headers=auth("input"))
    assert r.status_code == 201
    ctx = client.get(f"/v1/cases/{r.json()['id']}/context", headers=auth("dashboard")).json()
    assert ctx["evidence"]["weather"] is None
    assert any("location unknown" in g for g in ctx["gaps"])
    assert r.json()["recommendation"]["risk_level"] == "unknown"


def test_recommender_failure_then_retry(make_client, webhooks):
    client = make_client(mocks={"recommender": False}, recommender_url="http://recommender.test/predict")
    route = webhooks.post("http://recommender.test/predict", name="recommender")
    route.respond(503)

    r = client.post("/v1/requests", json={"text": "Wilting maize", "lat": LAT, "lon": LON}, headers=auth("input"))
    assert r.status_code == 202
    case = r.json()
    assert case["status"] == "failed_recommend"
    assert "503" in case["last_error"]
    assert case["recommendation"] is None

    route.respond(200, json={"disease": "late_blight", "confidence": 0.8, "risk_level": "high", "actions": ["x"], "model": "v1"})
    r = client.post(f"/v1/cases/{case['id']}/retry", headers=auth("internal"))
    assert r.status_code == 200
    assert r.json()["status"] == "delivered"
    assert r.json()["recommendation"]["disease"] == "late_blight"

    sent = json.loads(route.calls.last.request.content)
    assert sent["schema_version"] == "1.0" and sent["case_id"] == case["id"]


def test_failed_webhook_is_retried_by_tick(client, webhooks):
    webhooks["dashboard"].respond(500)
    r = client.post("/v1/requests", json={"text": "Leaf curl", "lat": LAT, "lon": LON}, headers=auth("input"))
    assert r.status_code == 201
    case = r.json()
    assert case["status"] == "recommended"
    dashboard = next(d for d in case["deliveries"] if d["channel"] == "dashboard")
    assert dashboard["status"] == "pending" and dashboard["attempts"] == 1

    # Not due yet (backoff) -> nothing attempted.
    tick = client.post("/internal/tick", headers=auth("internal")).json()
    assert tick["webhooks_attempted"] == 0

    with client.app.state.sessionmaker() as s:
        s.execute(update(OutboxEvent).values(next_attempt_at=utcnow() - timedelta(seconds=1)))
        s.commit()
    webhooks["dashboard"].respond(200)
    tick = client.get("/internal/tick", headers={"Authorization": "Bearer internal-key"}).json()
    assert tick["webhooks_sent"] == 1

    assert client.get(f"/v1/cases/{case['id']}", headers=auth("dashboard")).json()["status"] == "delivered"
