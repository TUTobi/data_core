from datetime import timedelta

from fastapi import APIRouter
from pydantic import BaseModel

from data_core.api.deps import AppServices, AppSettings, DbSession, require_role
from data_core.core.pipeline import resume_cases
from data_core.delivery.outbox import deliver_due
from data_core.providers.weather.cached import prune_weather_cache

router = APIRouter(prefix="/internal", tags=["internal"])


class TickResult(BaseModel):
    webhooks_attempted: int
    webhooks_sent: int
    cases_resumed: int
    weather_snapshots_pruned: int


@router.post("/tick", response_model=TickResult, dependencies=[require_role("internal")])
@router.get("/tick", response_model=TickResult, dependencies=[require_role("internal")], operation_id="tick_get")
def tick(db: DbSession, services: AppServices, settings: AppSettings) -> TickResult:
    """Periodic maintenance, triggered by an external scheduler (Vercel Cron, Azure Container Apps job,
    GitHub Actions, ...): retry due webhooks, resume failed/stuck cases, prune the weather cache."""
    delivery = deliver_due(db, services.http, settings)
    resumed = resume_cases(db, services, settings)
    pruned = prune_weather_cache(db, older_than=timedelta(days=7))
    db.commit()
    return TickResult(
        webhooks_attempted=delivery["attempted"],
        webhooks_sent=delivery["sent"],
        cases_resumed=resumed,
        weather_snapshots_pruned=pruned,
    )
