"""Case pipeline: received -> context_built -> recommended -> delivered.

Each step persists its result, so a case can be resumed from its last good state
(POST /v1/cases/{id}/retry or the /internal/tick cron). No in-process background workers are used,
which keeps the app stateless and serverless-friendly.
"""

import logging
from datetime import timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from data_core.config import Settings
from data_core.core.context import build_context
from data_core.db.models import Case, CaseStatus, DecisionContextRecord, Recommendation
from data_core.delivery.outbox import deliver_case, enqueue_events
from data_core.schemas.context import DecisionContext
from data_core.schemas.recommendation import RecommendationResult
from data_core.schemas.webhooks import WebhookPayload
from data_core.services import Services
from data_core.timeutil import utcnow

log = logging.getLogger(__name__)

RESUMABLE = (CaseStatus.RECEIVED, CaseStatus.CONTEXT_BUILT, CaseStatus.FAILED_CONTEXT, CaseStatus.FAILED_RECOMMEND)


def process_case(session: Session, case: Case, services: Services, settings: Settings) -> Case:
    case.attempts += 1
    session.commit()

    if case.status in (CaseStatus.RECEIVED, CaseStatus.FAILED_CONTEXT):
        try:
            context = build_context(session, case, services, settings)
            _store_context(case, context)
            case.status = CaseStatus.CONTEXT_BUILT
            case.last_error = None
            session.commit()
        except Exception as exc:
            session.rollback()
            _fail(session, case, CaseStatus.FAILED_CONTEXT, exc)
            return case

    if case.status in (CaseStatus.CONTEXT_BUILT, CaseStatus.FAILED_RECOMMEND):
        try:
            context = DecisionContext.model_validate(case.decision_context.context)
            result = services.recommender.recommend(context)
            _store_recommendation(case, context, result, settings, delivery_mocked=services.runtime.delivery.mocked)
            case.status = CaseStatus.RECOMMENDED
            case.last_error = None
            session.commit()
        except Exception as exc:
            session.rollback()
            _fail(session, case, CaseStatus.FAILED_RECOMMEND, exc)
            return case

    if case.status == CaseStatus.RECOMMENDED:
        deliver_case(session, case, services.http, settings)

    return case


def resume_cases(
    session: Session,
    services: Services,
    settings: Settings,
    idle_for: timedelta = timedelta(minutes=1),
    limit: int = 20,
) -> int:
    """Re-run failed or stuck cases (bounded by MAX_CASE_ATTEMPTS). Called from /internal/tick."""
    cutoff = utcnow() - idle_for
    cases = session.scalars(
        select(Case)
        .where(
            Case.attempts < settings.max_case_attempts,
            Case.status.in_(list(RESUMABLE)),
            Case.updated_at <= cutoff,
        )
        .order_by(Case.updated_at)
        .limit(limit)
    ).all()
    for case in cases:
        process_case(session, case, services, settings)
    return len(cases)


def _fail(session: Session, case: Case, status: CaseStatus, exc: Exception) -> None:
    log.warning("case %s -> %s", case.id, status, exc_info=exc)
    case.status = status
    case.last_error = f"{type(exc).__name__}: {exc}"[:2000]
    session.commit()


def _store_context(case: Case, context: DecisionContext) -> None:
    plan = context.plan.model_dump(mode="json")
    data = context.model_dump(mode="json")
    if case.decision_context is None:
        case.decision_context = DecisionContextRecord(plan=plan, context=data)
    else:
        case.decision_context.plan = plan
        case.decision_context.context = data
        case.decision_context.created_at = utcnow()


def _store_recommendation(
    case: Case, context: DecisionContext, result: RecommendationResult, settings: Settings, delivery_mocked: bool
) -> None:
    case.recommendation = Recommendation(
        disease=result.disease,
        confidence=result.confidence,
        risk_level=result.risk_level,
        explanation=result.explanation,
        actions=result.actions,
        raw=result.model_dump(mode="json"),
    )
    payload = WebhookPayload(
        case_id=case.id,
        request_id=case.request.id,
        external_id=case.request.external_id,
        channel=case.request.channel,
        caller_ref=case.request.caller_ref,
        problem_type=case.request.problem_type,
        location=context.request.location,
        recommendation=result,
        evidence_summary=evidence_summary(context),
        gaps=context.gaps,
        warnings=context.warnings,
        created_at=utcnow(),
    )
    enqueue_events(case, payload.model_dump(mode="json"), settings, mocked=delivery_mocked)


def evidence_summary(context: DecisionContext) -> list[str]:
    """Short human-readable evidence lines for the dashboard / phone script."""
    lines = []
    weather = context.evidence.weather
    if weather:
        lines.append(
            f"Weather ({weather.provider}), last {weather.past.hours} h: "
            f"{weather.past.precipitation_mm} mm rain, mean humidity {weather.past.mean_rh_pct} %, "
            f"{weather.past.hours_rh_ge_90} h with humidity >= 90 %"
        )
    for sensor in context.evidence.sensors[:5]:
        lines.append(
            f"Sensor {sensor.sensor_id}: {sensor.metric} = {sensor.latest_value}{sensor.unit or ''} "
            f"({sensor.distance_km} km away, {sensor.age_s // 60} min old)"
        )
    history = context.evidence.caller_history
    if history:
        lines.append(
            f"{history.same_problem_count} similar of {history.total_count} reports within "
            f"{history.radius_km:g} km in the last {history.lookback_h} h"
        )
    return lines
