"""The DecisionContext: the evidence package the core hands to the recommender."""

from typing import Any, Literal

from pydantic import BaseModel, Field

from data_core.schemas.common import UtcDatetime
from data_core.schemas.requests import Location

DataSourceName = Literal["sensors", "weather", "caller_history"]


class DataNeed(BaseModel):
    source: DataSourceName
    metrics: list[str] | None = None
    radius_km: float | None = None
    lookback_h: int | None = None
    forecast_h: int | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    priority: Literal["required", "optional"] = "optional"
    reason: str = ""


class DataPlan(BaseModel):
    strategy: str
    needs: list[DataNeed]
    notes: list[str] = Field(default_factory=list)


class RequestSummary(BaseModel):
    request_id: str
    external_id: str | None
    channel: str
    received_at: UtcDatetime
    text: str
    problem_type: str | None
    crop: str | None
    symptoms: list[str]
    location: Location | None
    location_source: str | None
    reported_event_time: UtcDatetime | None


class SensorEvidence(BaseModel):
    sensor_id: str
    metric: str
    unit: str | None
    latest_value: float
    latest_at: UtcDatetime
    mean: float
    min: float
    max: float
    n_readings: int
    distance_km: float
    age_s: int
    quality: str


class WeatherWindow(BaseModel):
    hours: int
    n_points: int = 0
    precipitation_mm: float | None = None
    mean_temp_c: float | None = None
    min_temp_c: float | None = None
    max_temp_c: float | None = None
    mean_rh_pct: float | None = None
    hours_rh_ge_90: int | None = Field(None, description="Hours with relative humidity >= 90 % (leaf-wetness proxy)")
    mean_soil_moisture: float | None = None


class WeatherEvidence(BaseModel):
    provider: str
    lat: float
    lon: float
    fetched_at: UtcDatetime
    from_cache: bool = False
    current: dict[str, Any] = Field(default_factory=dict)
    past: WeatherWindow
    forecast: WeatherWindow
    daily: list[dict[str, Any]] = Field(default_factory=list)


class SimilarReport(BaseModel):
    request_id: str
    received_at: UtcDatetime
    problem_type: str | None
    crop: str | None
    text: str
    distance_km: float
    same_problem_type: bool
    disease: str | None = None
    is_mock: bool = Field(False, description="Demo/mock call (channel 'demo' / extra.demo)")


class CallerHistoryEvidence(BaseModel):
    radius_km: float
    lookback_h: int
    total_count: int
    same_problem_count: int
    items: list[SimilarReport]


class Evidence(BaseModel):
    weather: WeatherEvidence | None = None
    sensors: list[SensorEvidence] = Field(default_factory=list)
    caller_history: CallerHistoryEvidence | None = None


class DecisionContext(BaseModel):
    schema_version: str = "1.0"
    case_id: str
    generated_at: UtcDatetime
    request: RequestSummary
    plan: DataPlan
    evidence: Evidence
    gaps: list[str] = Field(default_factory=list, description="Data that was wanted but is unavailable")
    warnings: list[str] = Field(default_factory=list, description="Caveats: mocked, stale or approximate data")
