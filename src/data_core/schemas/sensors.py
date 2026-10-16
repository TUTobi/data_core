import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from data_core.schemas.common import UtcDatetime

Quality = Literal["ok", "suspect", "mocked"]
_METRIC_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class SensorIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str | None = None
    kind: str | None = Field(None, description="e.g. 'humidity', 'rain', 'multi'")
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    meta: dict[str, Any] = Field(default_factory=dict)


class SensorOut(SensorIn):
    model_config = ConfigDict(from_attributes=True)

    created_at: UtcDatetime
    last_seen_at: UtcDatetime | None


class SensorReadingIn(BaseModel):
    """One measurement as posted by a field device (e.g. the Raspberry Pi)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "sensor_id": "pi-field-01",
                    "recorded_at": "2026-10-16T14:00:00Z",
                    "lat": -1.2921,
                    "lon": 36.8219,
                    "metrics": {"humidity_pct": 87.5, "temperature_c": 22.4},
                }
            ]
        }
    )

    sensor_id: str = Field(min_length=1, max_length=64)
    recorded_at: UtcDatetime | None = Field(None, description="Measurement time; defaults to time of receipt")
    lat: float | None = Field(None, ge=-90, le=90, description="Falls back to the registered sensor position")
    lon: float | None = Field(None, ge=-180, le=180)
    metrics: dict[str, float] = Field(min_length=1, description="metric name -> value, e.g. humidity_pct")
    units: dict[str, str] = Field(default_factory=dict, description="Optional units; inferred from suffix")
    quality: Quality = "ok"

    @field_validator("metrics")
    @classmethod
    def _metric_names(cls, v: dict[str, float]) -> dict[str, float]:
        bad = [k for k in v if not _METRIC_RE.match(k)]
        if bad:
            raise ValueError(f"invalid metric names (use snake_case, e.g. humidity_pct): {bad}")
        return v


class SensorReadingBatch(BaseModel):
    readings: list[SensorReadingIn] = Field(min_length=1, max_length=1000)


class IngestResult(BaseModel):
    accepted: int
    duplicates: int
    sensors: list[str]


class SensorReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sensor_id: str
    metric: str
    value: float
    unit: str | None
    recorded_at: UtcDatetime
    lat: float | None
    lon: float | None
    quality: str
    distance_km: float | None = None
