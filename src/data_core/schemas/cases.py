from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from data_core.schemas.common import UtcDatetime


class CallerRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str | None
    channel: str
    caller_ref: str | None
    received_at: UtcDatetime
    text: str
    problem_type: str | None
    crop: str | None
    symptoms: list[str]
    lat: float | None
    lon: float | None
    location_name: str | None
    location_precision_m: float | None
    location_source: str | None
    reported_event_time: UtcDatetime | None
    extra: dict[str, Any]


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    disease: str | None
    confidence: float | None
    risk_level: str | None
    explanation: str | None
    actions: list[str]
    created_at: UtcDatetime


class DeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel: str
    status: str
    attempts: int
    last_error: str | None
    sent_at: UtcDatetime | None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    attempts: int
    last_error: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    request: CallerRequestOut
    recommendation: RecommendationOut | None
    deliveries: list[DeliveryOut] = Field(validation_alias="outbox_events")


class CaseList(BaseModel):
    total: int
    items: list[CaseOut]
