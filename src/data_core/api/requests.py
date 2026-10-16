from fastapi import APIRouter, HTTPException, Response
from sqlalchemy.exc import IntegrityError

from data_core.api.deps import AppServices, AppSettings, DbSession, require_role
from data_core.core.pipeline import process_case
from data_core.db.models import Case, CaseStatus
from data_core.ingestion.request_service import create_request, find_by_external_id, is_mock_request, load_case
from data_core.schemas.cases import CaseOut
from data_core.schemas.requests import CallerRequestIn

router = APIRouter(prefix="/v1", tags=["requests"])


@router.post(
    "/requests",
    response_model=CaseOut,
    status_code=201,
    dependencies=[require_role("input")],
    responses={
        200: {"model": CaseOut, "description": "Duplicate external_id: the existing case is returned"},
        202: {"model": CaseOut, "description": "Stored, but processing is incomplete (see status/last_error)"},
    },
)
def submit_request(
    data: CallerRequestIn, response: Response, db: DbSession, services: AppServices, settings: AppSettings
) -> Case:
    """Receive a structured caller input and run the pipeline synchronously:
    store -> plan data needs -> gather DB/weather data -> recommender -> deliver (webhooks).
    The response already contains the recommendation when processing succeeded.
    Demo calls (channel "demo" / extra.demo) are refused when config.yaml sets caller_requests.mocked=false."""
    if not services.runtime.caller_requests.mocked and is_mock_request(data):
        raise HTTPException(
            status_code=422, detail="Demo/mock caller requests are disabled (config.yaml: caller_requests.mocked=false)"
        )
    if data.external_id and (existing := find_by_external_id(db, data.external_id)):
        response.status_code = 200
        return load_case(db, existing.case.id)

    try:
        case = create_request(db, data, services.geocoder)
    except IntegrityError:  # same external_id submitted concurrently
        db.rollback()
        existing = find_by_external_id(db, data.external_id)
        response.status_code = 200
        return load_case(db, existing.case.id)

    process_case(db, case, services, settings)
    if case.status not in (CaseStatus.RECOMMENDED, CaseStatus.DELIVERED):
        response.status_code = 202
    return load_case(db, case.id)
