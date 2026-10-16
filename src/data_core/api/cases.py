from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from data_core.api.deps import AppServices, AppSettings, DbSession, require_role
from data_core.core.pipeline import process_case
from data_core.db.models import CallerRequest, Case, CaseStatus
from data_core.ingestion.request_service import load_case
from data_core.schemas.cases import CaseList, CaseOut
from data_core.schemas.common import UtcDatetime
from data_core.schemas.context import DecisionContext

router = APIRouter(prefix="/v1", tags=["cases"])


@router.get("/cases", response_model=CaseList, dependencies=[require_role("dashboard", "input", "internal")])
def list_cases(
    db: DbSession,
    services: AppServices,
    status: str | None = None,
    problem_type: str | None = None,
    caller_ref: str | None = None,
    since: UtcDatetime | None = None,
    until: UtcDatetime | None = None,
    min_lat: float | None = None,
    max_lat: float | None = None,
    min_lon: float | None = None,
    max_lon: float | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> CaseList:
    """Cases for the dashboard (map, filters). Newest call (received_at) first."""
    stmt = select(Case).join(Case.request)
    if not services.runtime.caller_requests.mocked:
        stmt = stmt.where(CallerRequest.is_mock.is_(False))
    if status:
        stmt = stmt.where(Case.status == status)
    if problem_type:
        stmt = stmt.where(CallerRequest.problem_type == problem_type)
    if caller_ref:
        stmt = stmt.where(CallerRequest.caller_ref == caller_ref)
    if since:
        stmt = stmt.where(CallerRequest.received_at >= since)
    if until:
        stmt = stmt.where(CallerRequest.received_at <= until)
    if min_lat is not None:
        stmt = stmt.where(CallerRequest.lat >= min_lat)
    if max_lat is not None:
        stmt = stmt.where(CallerRequest.lat <= max_lat)
    if min_lon is not None:
        stmt = stmt.where(CallerRequest.lon >= min_lon)
    if max_lon is not None:
        stmt = stmt.where(CallerRequest.lon <= max_lon)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(
        stmt.options(selectinload(Case.request), selectinload(Case.recommendation), selectinload(Case.outbox_events))
        .order_by(CallerRequest.received_at.desc(), Case.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return CaseList(total=total, items=[CaseOut.model_validate(c) for c in items])


def _get_case_or_404(db, case_id: str) -> Case:
    case = load_case(db, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get("/cases/{case_id}", response_model=CaseOut, dependencies=[require_role("dashboard", "input", "internal")])
def get_case(case_id: str, db: DbSession) -> Case:
    return _get_case_or_404(db, case_id)


@router.get(
    "/cases/{case_id}/context",
    response_model=DecisionContext,
    dependencies=[require_role("dashboard", "internal")],
)
def get_case_context(case_id: str, db: DbSession) -> dict:
    """The full evidence package (plan, weather, sensors, similar reports, gaps) behind a recommendation."""
    case = _get_case_or_404(db, case_id)
    if case.decision_context is None:
        raise HTTPException(status_code=404, detail="Context not built yet")
    return case.decision_context.context


@router.post("/cases/{case_id}/retry", response_model=CaseOut, dependencies=[require_role("internal")])
def retry_case(case_id: str, db: DbSession, services: AppServices, settings: AppSettings) -> Case:
    """Resume a case from its last successful step."""
    case = _get_case_or_404(db, case_id)
    if case.status != CaseStatus.DELIVERED:
        process_case(db, case, services, settings)
    return load_case(db, case_id)
