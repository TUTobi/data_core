"""Adapter for the recommendation team's potato engine (recommendation-engine-2, `POST /analyze`).

The engine has its own input format: 30 daily temperatures, an hourly raw soil-wetness series and a free-text
plant description. This adapter builds that from the DecisionContext plus one extra Open-Meteo call (30 days of
history), and maps the engine's disease probabilities back onto a RecommendationResult.
"""

from datetime import UTC, datetime, timedelta

import httpx

from data_core.providers.weather.open_meteo import OpenMeteoProvider
from data_core.schemas.context import DecisionContext
from data_core.schemas.recommendation import RecommendationResult
from data_core.timeutil import as_utc, utcnow

REQUIRED_DAYS = 30
WETNESS_HOURS = 72
MAX_DESCRIPTION_CHARS = 2000
SOIL_SENSOR_METRIC = "soil_wetness_raw"  # a Pi soil-wetness sensor posting the raw value on the engine's scale

# Open-Meteo soil moisture (m³/m³, 0-1 cm) -> the engine's raw sensor scale
# (Dry ~120, A bit wet ~850, Very wet ~2500, Submerged ~3600). Rough calibration, tune when real sensor data exists.
SOIL_MOISTURE_TO_RAW = [(0.10, 120.0), (0.20, 850.0), (0.35, 2500.0), (0.45, 3600.0)]


def soil_moisture_to_raw(m3m3: float) -> float:
    points = SOIL_MOISTURE_TO_RAW
    if m3m3 <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if m3m3 <= x1:
            return round(y0 + (y1 - y0) * (m3m3 - x0) / (x1 - x0))
    return points[-1][1]


def risk_level(probability: int) -> str:
    if probability >= 70:
        return "high"
    if probability >= 40:
        return "medium"
    return "low"


class PotatoEngineRecommender:
    name = "potato_engine"

    def __init__(self, http: httpx.Client, url: str, timeout_s: float, weather_timeout_s: float = 8.0):
        self.http = http
        self.url = url
        self.timeout_s = timeout_s
        self.open_meteo = OpenMeteoProvider(http, weather_timeout_s)

    def recommend(self, context: DecisionContext) -> RecommendationResult:
        loc = context.request.location
        if loc is None or loc.lat is None or loc.lon is None:
            raise ValueError("potato engine needs the caller location (for temperature and soil history)")

        temperatures, wetness = self._history(loc.lat, loc.lon, utcnow())
        soil = next((s for s in context.evidence.sensors if s.metric == SOIL_SENSOR_METRIC), None)
        if soil is not None:  # nearest real sensor wins as the current reading
            wetness.append({"timestamp": as_utc(soil.latest_at).isoformat(), "value": soil.latest_value})

        resp = self.http.post(
            self.url,
            json={
                "temperatures": temperatures,
                "wetness_hourly": wetness,
                "plant_description": self._description(context),
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        return self._to_result(resp.json())

    def _history(self, lat: float, lon: float, now: datetime) -> tuple[list[dict], list[dict]]:
        payload = self.open_meteo._get_with_retry(
            {
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_mean",
                "hourly": "soil_moisture_0_to_1cm",
                "past_days": REQUIRED_DAYS + 1,
                "forecast_days": 1,
                "timezone": "GMT",
            }
        ).json()

        today = now.date().isoformat()
        daily = payload.get("daily") or {}
        days = [
            {"date": d, "temp_c": t}
            for d, t in zip(daily.get("time", []), daily.get("temperature_2m_mean", []))
            if d < today and t is not None
        ][-REQUIRED_DAYS:]
        if len(days) < REQUIRED_DAYS:
            raise ValueError(f"only {len(days)} of {REQUIRED_DAYS} days of temperature history available")

        hourly = payload.get("hourly") or {}
        since = now - timedelta(hours=WETNESS_HOURS)
        wetness = []
        for t, v in zip(hourly.get("time", []), hourly.get("soil_moisture_0_to_1cm", [])):
            at = datetime.fromisoformat(t).replace(tzinfo=UTC)
            if v is not None and since <= at <= now:
                wetness.append({"timestamp": at.isoformat(), "value": soil_moisture_to_raw(v)})
        if not wetness:
            raise ValueError("no soil moisture history available")
        return days, wetness

    @staticmethod
    def _description(context: DecisionContext) -> str:
        req = context.request
        parts = [req.text.strip()]
        if req.crop:
            parts.append(f"Crop: {req.crop}.")
        if req.symptoms:
            parts.append(f"Symptoms: {', '.join(req.symptoms)}.")
        return " ".join(parts)[:MAX_DESCRIPTION_CHARS]

    @staticmethod
    def _to_result(data: dict) -> RecommendationResult:
        diseases = sorted(data.get("diseases") or [], key=lambda d: d["probability"], reverse=True)
        rec = data.get("recommendation") or {}
        engine_actions = rec.get("actions") or []
        top = diseases[0] if diseases else None
        return RecommendationResult(
            disease=top["name"] if top else None,
            confidence=top["probability"] / 100 if top else None,
            risk_level=risk_level(top["probability"]) if top else "unknown",
            explanation=rec.get("summary") or None,
            actions=[a["detail"] for a in engine_actions if a.get("action") != "no_change" and a.get("detail")],
            model="potato-engine",
            diseases=diseases,
            engine_actions=engine_actions,
        )
