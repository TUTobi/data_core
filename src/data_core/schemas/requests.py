from typing import Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from data_core.input.adapters import adapt_payload
from data_core.schemas.common import UtcDatetime


class Location(BaseModel):
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    name: str | None = Field(None, max_length=200, description="Village / place; geocoded if no coordinates")
    precision_m: float | None = Field(None, ge=0)


class CallerRequestIn(BaseModel):
    """Structured caller input from the phone/Telegram workstream.

    The layout is not final: aliases (e.g. `description`, `latitude`, `source`) are accepted and
    unknown fields are kept in `extra` - see data_core.input.adapters.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "external_id": "call-2026-10-16-0001",
                    "channel": "phone_call",
                    "caller_ref": "c-7f3a",
                    "text": "My crops have started dying since the heavy rains.",
                    "problem_type": "crop_health",
                    "crop": "maize",
                    "symptoms": ["wilting", "yellow leaves"],
                    "location": {"lat": -1.2921, "lon": 36.8219, "precision_m": 2000},
                }
            ]
        }
    )

    external_id: str | None = Field(None, max_length=128, description="Idempotency key from the input system")
    channel: str = Field("unknown", max_length=32)
    caller_ref: str | None = Field(None, max_length=128, description="Pseudonymous caller id")
    received_at: UtcDatetime | None = None
    text: str = Field(min_length=1, max_length=10_000)
    problem_type: str | None = Field(None, max_length=64)
    crop: str | None = Field(None, max_length=64)
    symptoms: list[str] = Field(default_factory=list)
    location: Location | None = None
    reported_event_time: UtcDatetime | None = None
    callback_url: AnyHttpUrl | None = Field(None, description="Where the phone system wants the result pushed")
    extra: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _adapt(cls, data: Any) -> Any:
        return adapt_payload(data, set(cls.model_fields))

    @field_validator("problem_type", "crop")
    @classmethod
    def _normalise_label(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().lower().replace(" ", "_")
        return v or None
