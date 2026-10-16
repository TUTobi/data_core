from datetime import timedelta

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from data_core.api.deps import AppServices, AppSettings, DbSession, require_role
from data_core.db.models import SensorReading
from data_core.geo import bounding_box, haversine_km
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
    """Raw sensor readings around a point (newest first), optionally with weather - for the dashboard."""
    now = utcnow()
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_km)
    stmt = select(SensorReading).where(
        SensorReading.lat.between(min_lat, max_lat),
        SensorReading.lon.between(min_lon, max_lon),
        SensorReading.recorded_at >= now - timedelta(hours=since_h),
    )
    if metric:
        stmt = stmt.where(SensorReading.metric == metric)

    readings = []
    for r in db.scalars(stmt.order_by(SensorReading.recorded_at.desc())):
        distance = haversine_km(lat, lon, r.lat, r.lon)
        if distance <= radius_km:
            out = SensorReadingOut.model_validate(r)
            out.distance_km = round(distance, 3)
            readings.append(out)
            if len(readings) >= limit:
                break

    weather = None
    if include_weather:
        weather = fetch_weather_cached(
            db, services.weather, lat, lon, since_h, settings.default_forecast_h, settings.weather_cache_ttl_s
        )
        db.commit()
    return ObservationsOut(sensors=readings, weather=weather)
