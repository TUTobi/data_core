import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from data_core.db.models import CallerRequest, Case, CaseStatus
from data_core.providers.geocoding import Geocoder
from data_core.schemas.requests import CallerRequestIn
from data_core.timeutil import utcnow

log = logging.getLogger(__name__)


def is_mock_request(data: CallerRequestIn) -> bool:
    """Demo/mock calls, e.g. from mocks/seed_demo.py."""
    return data.channel == "demo" or data.extra.get("demo") is True


def find_by_external_id(session: Session, external_id: str) -> CallerRequest | None:
    return session.scalars(select(CallerRequest).where(CallerRequest.external_id == external_id)).first()


def create_request(session: Session, data: CallerRequestIn, geocoder: Geocoder | None) -> Case:
    """Persist the caller input and open a case for it. If only a place name is given, try to geocode it
    here so the stored request is usable as 'previous caller' history later on."""
    loc = data.location
    lat = loc.lat if loc else None
    lon = loc.lon if loc else None
    name = loc.name if loc else None
    precision = loc.precision_m if loc else None
    source = None

    if lat is not None and lon is not None:
        source = "caller"
    else:
        lat = lon = None
        if name and geocoder is not None:
            try:
                hit = geocoder.geocode(name)
            except Exception:  # geocoding is best effort; the context will report the gap
                log.warning("geocoding failed for %r", name, exc_info=True)
                hit = None
            if hit is not None:
                lat, lon, source = hit.lat, hit.lon, "geocoded"
                precision = precision or hit.precision_m

    request = CallerRequest(
        external_id=data.external_id,
        channel=data.channel,
        caller_ref=data.caller_ref,
        received_at=data.received_at or utcnow(),
        text=data.text,
        problem_type=data.problem_type,
        crop=data.crop,
        symptoms=data.symptoms,
        lat=lat,
        lon=lon,
        location_name=name,
        location_precision_m=precision,
        location_source=source,
        reported_event_time=data.reported_event_time,
        callback_url=str(data.callback_url) if data.callback_url else None,
        extra=data.extra,
        is_mock=is_mock_request(data),
    )
    case = Case(request=request, status=CaseStatus.RECEIVED)
    session.add(case)
    session.commit()
    return case


def load_case(session: Session, case_id: str) -> Case | None:
    stmt = (
        select(Case)
        .where(Case.id == case_id)
        .options(selectinload(Case.request), selectinload(Case.recommendation), selectinload(Case.outbox_events))
        .execution_options(populate_existing=True)
    )
    return session.scalars(stmt).first()
