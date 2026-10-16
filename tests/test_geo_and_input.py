import pytest

from data_core.geo import bounding_box, haversine_km
from data_core.schemas.requests import CallerRequestIn


def test_haversine_nairobi_mombasa():
    assert haversine_km(-1.2921, 36.8219, -4.0435, 39.6682) == pytest.approx(440, abs=5)


def test_bounding_box_contains_circle():
    lat, lon, r = -1.29, 36.82, 10
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, r)
    assert haversine_km(lat, lon, max_lat, lon) == pytest.approx(r, rel=1e-3)
    assert haversine_km(lat, lon, lat, max_lon) == pytest.approx(r, rel=1e-3)
    assert min_lat < lat < max_lat and min_lon < lon < max_lon


def test_overview_style_payload_is_adapted():
    """The example payload from project_overview.md must be accepted as-is."""
    req = CallerRequestIn.model_validate(
        {
            "problem_type": "Crop Health",
            "description": "Crops started dying after heavy rainfall",
            "latitude": -1.2921,
            "longitude": 36.8219,
            "reported_at": "2026-10-16T14:30:00Z",
            "source": "phone_call",
            "language": "sw",
        }
    )
    assert req.text == "Crops started dying after heavy rainfall"
    assert req.channel == "phone_call"
    assert req.problem_type == "crop_health"
    assert req.location.lat == -1.2921 and req.location.lon == 36.8219
    assert req.received_at.isoformat() == "2026-10-16T14:30:00+00:00"
    assert req.extra == {"language": "sw"}


def test_canonical_fields_win_and_village_is_location_name():
    req = CallerRequestIn.model_validate(
        {"text": "canonical", "description": "alias", "village": "Kiambu", "symptoms": "wilting, spots"}
    )
    assert req.text == "canonical"
    assert req.extra == {"description": "alias"}
    assert req.location.name == "Kiambu" and req.location.lat is None
    assert req.symptoms == ["wilting", "spots"]
