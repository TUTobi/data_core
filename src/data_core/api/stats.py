from datetime import timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from data_core.api.deps import AppServices, DbSession, require_role
from data_core.db.models import CallerRequest
from data_core.schemas.stats import ProblemCount, StatsSummary
from data_core.timeutil import utcnow

router = APIRouter(prefix="/v1", tags=["stats"])


@router.get("/stats/summary", response_model=StatsSummary, dependencies=[require_role("dashboard", "internal")])
def stats_summary(db: DbSession, services: AppServices, days: int = Query(30, ge=1, le=365)) -> StatsSummary:
    """Call statistics for the dashboard landing page: calls, distinct/repeat callers, reported problems.
    Demo calls are excluded when config.yaml sets caller_requests.mocked=false."""
    since = utcnow() - timedelta(days=days)
    in_window = CallerRequest.received_at >= since
    if not services.runtime.caller_requests.mocked:
        in_window = in_window & CallerRequest.is_mock.is_(False)

    total = db.scalar(select(func.count()).select_from(CallerRequest).where(in_window))
    per_caller = (
        select(CallerRequest.caller_ref, func.count().label("n"))
        .where(in_window, CallerRequest.caller_ref.is_not(None))
        .group_by(CallerRequest.caller_ref)
        .subquery()
    )
    distinct = db.scalar(select(func.count()).select_from(per_caller))
    repeat = db.scalar(select(func.count()).select_from(per_caller).where(per_caller.c.n > 1))

    n = func.count().label("n")
    problems = db.execute(
        select(CallerRequest.problem_type, n)
        .where(in_window)
        .group_by(CallerRequest.problem_type)
        .order_by(n.desc(), CallerRequest.problem_type)
    ).all()

    return StatsSummary(
        since=since,
        days=days,
        total_calls=total,
        distinct_callers=distinct,
        repeat_callers=repeat,
        problems=[ProblemCount(problem_type=p, count=c) for p, c in problems],
    )
