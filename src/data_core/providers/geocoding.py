"""Resolve a place name (village) to coordinates when the caller gave no GPS position."""

from dataclasses import dataclass
from typing import Protocol

import httpx


@dataclass(frozen=True)
class GeoResult:
    lat: float
    lon: float
    name: str
    precision_m: float


class Geocoder(Protocol):
    def geocode(self, name: str) -> GeoResult | None: ...


class MockGeocoder:
    """Offline stand-in (config.yaml: geocoding.mocked=true): a few demo places, anything else is unknown."""

    PLACES = {
        "nairobi": (-1.2921, 36.8219),
        "kiambu": (-1.1714, 36.8356),
        "thika": (-1.0333, 37.0693),
        "machakos": (-1.5177, 37.2634),
        "nyeri": (-0.4201, 36.9476),
        "nakuru": (-0.3031, 36.0800),
    }

    def geocode(self, name: str) -> GeoResult | None:
        hit = self.PLACES.get(name.strip().lower())
        if hit is None:
            return None
        return GeoResult(lat=hit[0], lon=hit[1], name=f"{name.strip().title()} (mock gazetteer)", precision_m=5000.0)


class OpenMeteoGeocoder:
    URL = "https://geocoding-api.open-meteo.com/v1/search"
    # A place-name match is only a rough position (village/town centre).
    PRECISION_M = 5000.0

    def __init__(self, http: httpx.Client, timeout_s: float, country_code: str = ""):
        self.http = http
        self.timeout_s = timeout_s
        self.country_code = country_code

    def geocode(self, name: str) -> GeoResult | None:
        params: dict[str, str | int] = {"name": name, "count": 1, "format": "json"}
        if self.country_code:
            params["countryCode"] = self.country_code
        resp = self.http.get(self.URL, params=params, timeout=self.timeout_s)
        resp.raise_for_status()
        results = resp.json().get("results") or []
        if not results:
            return None
        top = results[0]
        label = ", ".join(p for p in (top.get("name"), top.get("admin1"), top.get("country")) if p)
        return GeoResult(lat=top["latitude"], lon=top["longitude"], name=label, precision_m=self.PRECISION_M)
