"""DB-backed weather cache: keeps API calls low and makes repeated requests fast.
Stored in the DB (not in memory) so it also works across serverless instances."""

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from data_core.db.models import WeatherSnapshot
from data_core.providers.weather.base import WeatherProvider
from data_core.schemas.context import WeatherEvidence
from data_core.timeutil import utcnow


def fetch_weather_cached(
    session: Session,
    provider: WeatherProvider,
    lat: float,
    lon: float,
    past_h: int,
    forecast_h: int,
    ttl_s: int,
    now: datetime | None = None,
) -> WeatherEvidence:
    now = now or utcnow()
    # ~1 km grid: nearby callers share a cache entry (weather models are coarser anyway).
    lat_key, lon_key = round(lat, 2), round(lon, 2)
    window_key = f"{past_h}:{forecast_h}"

    if ttl_s > 0:
        snapshot = session.scalars(
            select(WeatherSnapshot)
            .where(
                WeatherSnapshot.provider == provider.name,
                WeatherSnapshot.lat_key == lat_key,
                WeatherSnapshot.lon_key == lon_key,
                WeatherSnapshot.window_key == window_key,
                WeatherSnapshot.fetched_at >= now - timedelta(seconds=ttl_s),
            )
            .order_by(WeatherSnapshot.fetched_at.desc())
            .limit(1)
        ).first()
        if snapshot is not None:
            cached = WeatherEvidence.model_validate(snapshot.payload)
            cached.from_cache = True
            return cached

    evidence = provider.get(lat_key, lon_key, past_h, forecast_h)
    session.add(
        WeatherSnapshot(
            provider=provider.name,
            lat_key=lat_key,
            lon_key=lon_key,
            window_key=window_key,
            fetched_at=now,
            payload=evidence.model_dump(mode="json"),
        )
    )
    session.flush()
    return evidence


def prune_weather_cache(session: Session, older_than: timedelta) -> int:
    result = session.execute(delete(WeatherSnapshot).where(WeatherSnapshot.fetched_at < utcnow() - older_than))
    return result.rowcount or 0
