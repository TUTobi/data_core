"""The data-needs planner: decides WHICH data the recommender needs for a given caller request.

NOTE: How the core should make this decision is still undecided (see project.md, section on the
core). It depends on what the recommendation system needs. Only the interface is fixed:
    plan(request) -> DataPlan
Strategies are interchangeable and selected via PLANNER_STRATEGY. For now there is only the
`fetch_all` baseline; rule-based / LLM-assisted / hybrid strategies can be added to PLANNERS.
"""

from collections.abc import Callable
from typing import Protocol

from data_core.config import Settings
from data_core.db.models import CallerRequest
from data_core.schemas.context import DataNeed, DataPlan


class DataNeedsPlanner(Protocol):
    name: str

    def plan(self, request: CallerRequest) -> DataPlan: ...


class FetchAllPlanner:
    """Baseline: request every available source around the caller with default radius / windows."""

    name = "fetch_all"

    def __init__(self, radius_km: float, lookback_h: int, forecast_h: int):
        self.radius_km = radius_km
        self.lookback_h = lookback_h
        self.forecast_h = forecast_h

    def plan(self, request: CallerRequest) -> DataPlan:
        return DataPlan(
            strategy=self.name,
            needs=[
                DataNeed(
                    source="weather",
                    lookback_h=self.lookback_h,
                    forecast_h=self.forecast_h,
                    reason="Recent and forecast weather (humidity, rain, temperature) drive crop-disease risk",
                ),
                DataNeed(
                    source="sensors",
                    radius_km=self.radius_km,
                    lookback_h=self.lookback_h,
                    reason="Local field measurements near the caller",
                ),
                DataNeed(
                    source="caller_history",
                    radius_km=self.radius_km,
                    lookback_h=self.lookback_h,
                    reason="Similar reports nearby may indicate a regional outbreak",
                ),
            ],
            notes=["Baseline strategy: the final data-selection logic is not decided yet"],
        )


PLANNERS: dict[str, Callable[[Settings], DataNeedsPlanner]] = {
    "fetch_all": lambda s: FetchAllPlanner(s.default_radius_km, s.default_lookback_h, s.default_forecast_h),
}


def build_planner(settings: Settings) -> DataNeedsPlanner:
    try:
        return PLANNERS[settings.planner_strategy](settings)
    except KeyError:
        raise ValueError(
            f"Unknown PLANNER_STRATEGY {settings.planner_strategy!r}; available: {sorted(PLANNERS)}"
        ) from None
