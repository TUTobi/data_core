"""Small geo helpers. Spatial queries use a bounding-box SQL prefilter + exact haversine in Python,
which keeps the DB portable (no PostGIS needed). The antimeridian is not handled."""

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bounding_box(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """(min_lat, max_lat, min_lon, max_lon) of a box enclosing the circle around (lat, lon)."""
    dlat = math.degrees(radius_km / EARTH_RADIUS_KM)
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    dlon = min(math.degrees(radius_km / (EARTH_RADIUS_KM * cos_lat)), 180.0)
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon
