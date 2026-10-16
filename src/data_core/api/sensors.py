from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from data_core.api.deps import DbSession, require_role
from data_core.db.models import Sensor
from data_core.ingestion.sensor_service import ingest_readings, upsert_sensor
from data_core.schemas.sensors import IngestResult, SensorIn, SensorOut, SensorReadingBatch, SensorReadingIn

router = APIRouter(prefix="/v1", tags=["sensors"])


@router.post("/sensor-readings", response_model=IngestResult, status_code=201, dependencies=[require_role("pi")])
def post_sensor_readings(body: SensorReadingIn | SensorReadingBatch, db: DbSession) -> IngestResult:
    """Endpoint the field devices (Raspberry Pi) push to: a single reading or `{"readings": [...]}`.
    Idempotent per (sensor_id, recorded_at, metric), so devices can safely re-send after network errors."""
    readings = body.readings if isinstance(body, SensorReadingBatch) else [body]
    try:
        return ingest_readings(db, readings)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Concurrent duplicate reading; retry the request") from None


@router.post("/sensors", response_model=SensorOut, dependencies=[require_role("pi", "internal")])
def register_sensor(data: SensorIn, db: DbSession) -> Sensor:
    return upsert_sensor(db, data)


@router.get("/sensors", response_model=list[SensorOut], dependencies=[require_role("dashboard", "internal")])
def list_sensors(db: DbSession) -> list[Sensor]:
    return list(db.scalars(select(Sensor).order_by(Sensor.id)))
