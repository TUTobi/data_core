"""Executes a DataPlan and assembles the DecisionContext for the recommender."""

import logging

from sqlalchemy.orm import Session

from data_core.config import Settings
from data_core.core.retrieval import latest_sensor_evidence, similar_reports
from data_core.db.models import Case
from data_core.providers.weather.cached import fetch_weather_cached
from data_core.schemas.context import DataNeed, DecisionContext, Evidence, RequestSummary
from data_core.schemas.requests import Location
from data_core.services import Services
from data_core.timeutil import as_utc, utcnow

log = logging.getLogger(__name__)

STALE_SENSOR_AFTER_S = 6 * 3600


def build_context(session: Session, case: Case, services: Services, settings: Settings) -> DecisionContext:
    now = utcnow()
    req = case.request
    plan = services.planner.plan(req)
    evidence = Evidence()
    gaps: list[str] = []
    warnings: list[str] = []

    runtime = services.runtime
    if runtime.recommender.mocked:
        warnings.append("Recommendation is mocked (built-in heuristic, not a disease model)")
    if req.is_mock:
        warnings.append("This call is demo/mock data")

    has_location = req.lat is not None and req.lon is not None
    if not has_location:
        gaps.append("Caller location unknown: weather and caller-history lookups skipped")
    elif req.location_source == "geocoded":
        source = "mock gazetteer" if runtime.geocoding.mocked else "place name"
        warnings.append(f"Location approximated from {source} {req.location_name!r}")

    for need in plan.needs:
        if not has_location and need.source != "sensors":  # the latest sensor reading is location-independent
            continue
        try:
            _collect(session, need, req, evidence, gaps, warnings, services, settings, now)
        except Exception as exc:
            if need.priority == "required":
                raise
            log.warning("optional data source %s failed", need.source, exc_info=True)
            gaps.append(f"{need.source} unavailable: {type(exc).__name__}: {exc}")

    location = None
    if has_location or req.location_name:
        location = Location(lat=req.lat, lon=req.lon, name=req.location_name, precision_m=req.location_precision_m)

    return DecisionContext(
        case_id=case.id,
        generated_at=now,
        request=RequestSummary(
            request_id=req.id,
            external_id=req.external_id,
            channel=req.channel,
            received_at=as_utc(req.received_at),
            text=req.text,
            problem_type=req.problem_type,
            crop=req.crop,
            symptoms=req.symptoms or [],
            location=location,
            location_source=req.location_source,
            reported_event_time=as_utc(req.reported_event_time),
        ),
        plan=plan,
        evidence=evidence,
        gaps=gaps,
        warnings=warnings,
    )


def _collect(session, need: DataNeed, req, evidence: Evidence, gaps, warnings, services, settings, now) -> None:
    radius = need.radius_km or settings.default_radius_km
    lookback = need.lookback_h or settings.default_lookback_h

    if need.source == "weather":
        evidence.weather = fetch_weather_cached(
            session,
            services.weather,
            req.lat,
            req.lon,
            past_h=lookback,
            forecast_h=need.forecast_h or settings.default_forecast_h,
            ttl_s=settings.weather_cache_ttl_s,
            now=now,
        )
        if evidence.weather.provider == "mock":
            warnings.append("Weather data is mocked")

    elif need.source == "sensors":
        evidence.sensors = latest_sensor_evidence(
            session, now, req.lat, req.lon, need.metrics,
            include_mocked=services.runtime.sensors.mocked,
        )
        if not evidence.sensors:
            gaps.append("No sensor readings in the database")
        if any(s.quality == "mocked" for s in evidence.sensors):
            warnings.append("Some sensor data is mocked")
        stale = sorted({s.sensor_id for s in evidence.sensors if s.age_s > STALE_SENSOR_AFTER_S})
        if stale:
            warnings.append(f"Stale sensor data (> {STALE_SENSOR_AFTER_S // 3600} h old): {', '.join(stale)}")

    elif need.source == "caller_history":
        evidence.caller_history = similar_reports(
            session, req, req.lat, req.lon, radius, lookback, now, need.filters,
            include_mock=services.runtime.caller_requests.mocked,
        )
        if any(r.is_mock for r in evidence.caller_history.items):
            warnings.append("Some previous reports are demo/mock data")
