"""ORM models. Schema changes go through Alembic (alembic/versions)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from data_core.db.base import Base
from data_core.timeutil import utcnow


def new_id() -> str:
    return uuid.uuid4().hex


class CaseStatus(StrEnum):
    RECEIVED = "received"
    CONTEXT_BUILT = "context_built"
    RECOMMENDED = "recommended"
    DELIVERED = "delivered"
    FAILED_CONTEXT = "failed_context"
    FAILED_RECOMMEND = "failed_recommend"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class Sensor(Base):
    __tablename__ = "sensors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    kind: Mapped[str | None] = mapped_column(String(50))
    lat: Mapped[float | None]
    lon: Mapped[float | None]
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime | None]


class SensorReading(Base):
    """One metric of one measurement. A Pi post with several metrics becomes several rows."""

    __tablename__ = "sensor_readings"
    __table_args__ = (
        UniqueConstraint("sensor_id", "recorded_at", "metric", name="uq_sensor_readings_key"),
        Index("ix_sensor_readings_recorded_at", "recorded_at"),
        Index("ix_sensor_readings_lat_lon", "lat", "lon"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sensor_id: Mapped[str] = mapped_column(ForeignKey("sensors.id"))
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[float]
    unit: Mapped[str | None] = mapped_column(String(32))
    recorded_at: Mapped[datetime]
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
    lat: Mapped[float | None]
    lon: Mapped[float | None]
    quality: Mapped[str] = mapped_column(String(16), default="ok")
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class CallerRequest(Base):
    """A structured caller input (phone call, Telegram, ...). Doubles as the 'previous callers' history."""

    __tablename__ = "caller_requests"
    __table_args__ = (
        Index("ix_caller_requests_received_at", "received_at"),
        Index("ix_caller_requests_lat_lon", "lat", "lon"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    external_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    channel: Mapped[str] = mapped_column(String(32), default="unknown")
    caller_ref: Mapped[str | None] = mapped_column(String(128))
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
    text: Mapped[str] = mapped_column(Text)
    problem_type: Mapped[str | None] = mapped_column(String(64))
    crop: Mapped[str | None] = mapped_column(String(64))
    symptoms: Mapped[list[str]] = mapped_column(JSON, default=list)
    lat: Mapped[float | None]
    lon: Mapped[float | None]
    location_name: Mapped[str | None] = mapped_column(String(200))
    location_precision_m: Mapped[float | None]
    location_source: Mapped[str | None] = mapped_column(String(32))  # "caller" | "geocoded"
    reported_event_time: Mapped[datetime | None]
    callback_url: Mapped[str | None] = mapped_column(String(500))
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    case: Mapped["Case | None"] = relationship(back_populates="request")


class Case(Base):
    """Processing state of one caller request through the pipeline."""

    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    request_id: Mapped[str] = mapped_column(ForeignKey("caller_requests.id"), unique=True)
    status: Mapped[str] = mapped_column(String(32), default=CaseStatus.RECEIVED, index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    request: Mapped[CallerRequest] = relationship(back_populates="case")
    decision_context: Mapped["DecisionContextRecord | None"] = relationship(cascade="all, delete-orphan")
    recommendation: Mapped["Recommendation | None"] = relationship(cascade="all, delete-orphan")
    outbox_events: Mapped[list["OutboxEvent"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="OutboxEvent.id"
    )


class DecisionContextRecord(Base):
    __tablename__ = "decision_contexts"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    context: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"

    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), primary_key=True)
    disease: Mapped[str | None] = mapped_column(String(200))
    confidence: Mapped[float | None]
    risk_level: Mapped[str | None] = mapped_column(String(32))
    explanation: Mapped[str | None] = mapped_column(Text)
    actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class OutboxEvent(Base):
    """Transactional outbox: a webhook that must reach the dashboard / phone system."""

    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_status_next_attempt", "status", "next_attempt_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32))  # "dashboard" | "phone"
    target_url: Mapped[str] = mapped_column(String(500))
    event: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default=OutboxStatus.PENDING)
    attempts: Mapped[int] = mapped_column(default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None]

    case: Mapped[Case] = relationship(back_populates="outbox_events")


class WeatherSnapshot(Base):
    """Cache of normalised weather responses, keyed by provider + rounded coordinates + time window."""

    __tablename__ = "weather_snapshots"
    __table_args__ = (
        Index("ix_weather_lookup", "provider", "lat_key", "lon_key", "window_key", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    lat_key: Mapped[float]
    lon_key: Mapped[float]
    window_key: Mapped[str] = mapped_column(String(32))
    fetched_at: Mapped[datetime] = mapped_column(default=utcnow)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
