from fastapi import APIRouter, Query
from pydantic import BaseModel

from data_core.api.deps import AppServices, AppSettings, DbSession, require_role
from data_core.core.retrieval import distance_or_none, latest_sensor_readings
from data_core.providers.weather.cached import fetch_weather_cached
from data_core.schemas.context import WeatherEvidence
from data_core.schemas.sensors import SensorReadingOut
from data_core.timeutil import utcnow

router = APIRouter(prefix="/v1", tags=["observations"])


class ObservationsOut(BaseModel):
    sensors: list[SensorReadingOut]
    weather: WeatherEvidence | None = None


@router.get("/observations", response_model=ObservationsOut, dependencies=[require_role("dashboard", "internal")])
def get_observations(
    db: DbSession,
    services: AppServices,
    settings: AppSettings,
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
    radius_km: float = Query(10.0, gt=0, le=200),
    since_h: int = Query(72, ge=1, le=24 * 31),
    metric: str | None = None,
    include_weather: bool = False,
    limit: int = Query(1000, ge=1, le=5000),
) -> ObservationsOut:
    """The most recent sensor reading in the DB (optionally of one `metric`), regardless of location or age,
    plus optional weather at `lat`/`lon` - for the dashboard. `radius_km` is accepted for compatibility but
    ignored; `since_h` only sets the weather window."""
    readings = []
    metrics = [metric] if metric else None
    for r in latest_sensor_readings(db, utcnow(), metrics, include_mocked=services.runtime.sensors.mocked)[:limit]:
        out = SensorReadingOut.model_validate(r)
        out.distance_km = distance_or_none(lat, lon, r)
        readings.append(out)

    weather = None
    if include_weather:
        weather = fetch_weather_cached(
            db, services.weather, lat, lon, since_h, settings.default_forecast_h, settings.weather_cache_ttl_s
        )
        db.commit()
    return ObservationsOut(sensors=readings, weather=weather)
