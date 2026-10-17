"""DB lookups for the decision context: the latest sensor reading and similar previous caller reports."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from data_core.db.models import CallerRequest, Case, SensorReading
from data_core.geo import bounding_box, haversine_km
from data_core.schemas.context import CallerHistoryEvidence, SensorEvidence, SimilarReport
from data_core.timeutil import as_utc


def latest_sensor_readings(
    session: Session,
    now: datetime,
    metrics: list[str] | None = None,
    include_mocked: bool = True,
) -> list[SensorReading]:
    """The most recent sensor reading in the DB, regardless of location or age: one row per metric
    the sensor sent at that timestamp, sorted by metric.
    `include_mocked=False` drops readings flagged quality "mocked" (config.yaml sensors.mocked=false)."""
    stmt = select(SensorReading).where(SensorReading.recorded_at <= now)
    if metrics:
        stmt = stmt.where(SensorReading.metric.in_(metrics))
    if not include_mocked:
        stmt = stmt.where(SensorReading.quality != "mocked")

    newest = session.scalars(stmt.order_by(SensorReading.recorded_at.desc()).limit(1)).first()
    if newest is None:
        return []
    return list(session.scalars(
        stmt.where(SensorReading.sensor_id == newest.sensor_id, SensorReading.recorded_at == newest.recorded_at)
        .order_by(SensorReading.metric)
    ))


def distance_or_none(lat: float | None, lon: float | None, reading: SensorReading) -> float | None:
    if None in (lat, lon, reading.lat, reading.lon):
        return None
    return round(haversine_km(lat, lon, reading.lat, reading.lon), 3)


def latest_sensor_evidence(
    session: Session,
    now: datetime,
    lat: float | None = None,
    lon: float | None = None,
    metrics: list[str] | None = None,
    include_mocked: bool = True,
) -> list[SensorEvidence]:
    """`latest_sensor_readings` as evidence. `lat`/`lon` only fill in `distance_km` when both sides are known."""
    evidence = []
    for reading in latest_sensor_readings(session, now, metrics, include_mocked):
        recorded_at = as_utc(reading.recorded_at)
        evidence.append(
            SensorEvidence(
                sensor_id=reading.sensor_id,
                metric=reading.metric,
                unit=reading.unit,
                latest_value=reading.value,
                latest_at=recorded_at,
                mean=reading.value,
                min=reading.value,
                max=reading.value,
                n_readings=1,
                distance_km=distance_or_none(lat, lon, reading),
                age_s=int((now - recorded_at).total_seconds()),
                quality=reading.quality,
            )
        )
    return evidence


def similar_reports(
    session: Session,
    request: CallerRequest,
    lat: float,
    lon: float,
    radius_km: float,
    lookback_h: int,
    now: datetime,
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    include_mock: bool = True,
) -> CallerHistoryEvidence:
    """Previous caller reports near the location, flagged when they share the problem type.
    `include_mock=False` drops demo calls (config.yaml caller_requests.mocked=false)."""
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_km)
    stmt = (
        select(CallerRequest)
        .options(selectinload(CallerRequest.case).selectinload(Case.recommendation))
        .where(
            CallerRequest.id != request.id,
            CallerRequest.lat.between(min_lat, max_lat),
            CallerRequest.lon.between(min_lon, max_lon),
            CallerRequest.received_at >= now - timedelta(hours=lookback_h),
            CallerRequest.received_at <= now,
        )
    )
    if filters and filters.get("problem_type"):
        stmt = stmt.where(CallerRequest.problem_type == filters["problem_type"])
    if not include_mock:
        stmt = stmt.where(CallerRequest.is_mock.is_(False))

    items = []
    for other in session.scalars(stmt):
        distance = haversine_km(lat, lon, other.lat, other.lon)
        if distance > radius_km:
            continue
        recommendation = other.case.recommendation if other.case else None
        items.append(
            SimilarReport(
                request_id=other.id,
                received_at=as_utc(other.received_at),
                problem_type=other.problem_type,
                crop=other.crop,
                text=other.text[:300],
                distance_km=round(distance, 3),
                same_problem_type=bool(request.problem_type) and other.problem_type == request.problem_type,
                disease=recommendation.disease if recommendation else None,
                is_mock=other.is_mock,
            )
        )
    items.sort(key=lambda r: r.received_at, reverse=True)
    return CallerHistoryEvidence(
        radius_km=radius_km,
        lookback_h=lookback_h,
        total_count=len(items),
        same_problem_count=sum(1 for r in items if r.same_problem_type),
        items=items[:limit],
    )
