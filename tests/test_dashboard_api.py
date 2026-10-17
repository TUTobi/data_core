from datetime import UTC, datetime, timedelta

from tests.conftest import auth

LAT, LON = -0.30, 36.08


def _submit(client, caller_ref, problem_type, days_ago=1):
    body = {
        "text": "Yellow leaves",
        "caller_ref": caller_ref,
        "problem_type": problem_type,
        "received_at": (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(),
        "lat": LAT,
        "lon": LON,
    }
    r = client.post("/v1/requests", json=body, headers=auth("input"))
    assert r.status_code in (201, 202)
    return r.json()


def test_stats_summary_counts_calls_callers_and_problems(client, webhooks):
    _submit(client, "a", "pests")
    _submit(client, "a", "pests")
    _submit(client, "b", "crop_health")
    _submit(client, None, "pests")
    _submit(client, "c", "pests", days_ago=40)  # outside the 30-day window

    assert client.get("/v1/stats/summary").status_code == 401
    body = client.get("/v1/stats/summary", headers=auth("dashboard")).json()
    assert body["days"] == 30
    assert body["total_calls"] == 4
    assert body["distinct_callers"] == 2
    assert body["repeat_callers"] == 1
    assert body["problems"] == [{"problem_type": "pests", "count": 3}, {"problem_type": "crop_health", "count": 1}]

    assert client.get("/v1/stats/summary", params={"days": 60}, headers=auth("dashboard")).json()["total_calls"] == 5


def test_cases_filter_by_caller_ref(client, webhooks):
    _submit(client, "a", "pests")
    _submit(client, "a", "soil")
    _submit(client, "b", "pests")
    body = client.get("/v1/cases", params={"caller_ref": "a"}, headers=auth("dashboard")).json()
    assert body["total"] == 2
    assert {c["request"]["caller_ref"] for c in body["items"]} == {"a"}


def test_cors_preflight_allows_configured_origin(make_client):
    client = make_client(cors_origins="http://localhost:5173,https://dash.example")
    preflight = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-api-key"}

    r = client.options("/v1/cases", headers={"Origin": "https://dash.example", **preflight})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://dash.example"

    r = client.get("/v1/cases", headers={"Origin": "http://localhost:5173", **auth("dashboard")})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"

    r = client.options("/v1/cases", headers={"Origin": "https://evil.example", **preflight})
    assert "access-control-allow-origin" not in r.headers


def test_cors_origin_regex_allows_preview_urls(make_client):
    client = make_client(
        cors_origins="https://dash.example/",
        cors_origin_regex=r"https://dash-[a-z0-9]+-team\.vercel\.app",
    )
    preflight = {"Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "x-api-key"}

    for origin in ("https://dash.example", "https://dash-me6vglldc-team.vercel.app"):
        r = client.options("/v1/cases", headers={"Origin": origin, **preflight})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == origin

    # The regex must match the whole origin, not just a prefix.
    for origin in ("https://dash-abc-team.vercel.app.evil.example", "https://dash-abc-other.vercel.app"):
        r = client.options("/v1/cases", headers={"Origin": origin, **preflight})
        assert "access-control-allow-origin" not in r.headers
