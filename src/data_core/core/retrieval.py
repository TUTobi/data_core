"""DB lookups for the decision context: nearby sensor readings and similar previous caller reports."""

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import fmean
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from data_core.db.models import CallerRequest, Case, SensorReading
from data_core.geo import bounding_box, haversine_km
from data_core.schemas.context import CallerHistoryEvidence, SensorEvidence, SimilarReport
from data_core.timeutil import as_utc

_QUALITY_RANK = {"ok": 0, "mocked": 1, "suspect": 2}


def nearby_sensor_evidence(
    session: Session,
    lat: float,
    lon: float,
    radius_km: float,
    lookback_h: int,
    now: datetime,
    metrics: list[str] | None = None,
    include_mocked: bool = True,
) -> list[SensorEvidence]:
    """Aggregate readings per (sensor, metric) within radius and time window, nearest first.
    `include_mocked=False` drops readings flagged quality "mocked" (config.yaml sensors.mocked=false)."""
    min_lat, max_lat, min_lon, max_lon = bounding_box(lat, lon, radius_km)
    stmt = select(SensorReading).where(
        SensorReading.lat.between(min_lat, max_lat),
        SensorReading.lon.between(min_lon, max_lon),
        SensorReading.recorded_at >= now - timedelta(hours=lookback_h),
        SensorReading.recorded_at <= now,
    )
    if metrics:
        stmt = stmt.where(SensorReading.metric.in_(metrics))
    if not include_mocked:
        stmt = stmt.where(SensorReading.quality != "mocked")

    groups: dict[tuple[str, str], list[tuple[SensorReading, float]]] = defaultdict(list)
    for reading in session.scalars(stmt):
        distance = haversine_km(lat, lon, reading.lat, reading.lon)
        if distance <= radius_km:
            groups[(reading.sensor_id, reading.metric)].append((reading, distance))

    evidence = []
    for (sensor_id, metric), items in groups.items():
        items.sort(key=lambda item: as_utc(item[0].recorded_at))
        latest, distance = items[-1]
        values = [r.value for r, _ in items]
        latest_at = as_utc(latest.recorded_at)
        evidence.append(
            SensorEvidence(
                sensor_id=sensor_id,
                metric=metric,
                unit=latest.unit,
                latest_value=latest.value,
                latest_at=latest_at,
                mean=round(fmean(values), 3),
                min=min(values),
                max=max(values),
                n_readings=len(values),
                distance_km=round(distance, 3),
                age_s=int((now - latest_at).total_seconds()),
                quality=max((r.quality for r, _ in items), key=lambda q: _QUALITY_RANK.get(q, 3)),
            )
        )
    evidence.sort(key=lambda e: (e.distance_km, e.sensor_id, e.metric))
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
