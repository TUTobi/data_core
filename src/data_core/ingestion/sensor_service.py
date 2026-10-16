from sqlalchemy import select
from sqlalchemy.orm import Session

from data_core.db.models import Sensor, SensorReading
from data_core.schemas.sensors import IngestResult, SensorIn, SensorReadingIn
from data_core.timeutil import utcnow

_UNIT_SUFFIXES = {"_pct": "%", "_c": "°C", "_mm": "mm", "_hpa": "hPa", "_ntu": "NTU", "_ms": "m/s", "_lux": "lx"}


def default_unit(metric: str) -> str | None:
    for suffix, unit in _UNIT_SUFFIXES.items():
        if metric.endswith(suffix):
            return unit
    return None


def upsert_sensor(session: Session, data: SensorIn) -> Sensor:
    sensor = session.get(Sensor, data.id)
    if sensor is None:
        sensor = Sensor(id=data.id, meta={})
        session.add(sensor)
    for field in ("name", "kind", "lat", "lon"):
        value = getattr(data, field)
        if value is not None:
            setattr(sensor, field, value)
    if data.meta:
        sensor.meta = {**(sensor.meta or {}), **data.meta}
    session.commit()
    return sensor


def _exists(session: Session, sensor_id: str, recorded_at, metric: str) -> bool:
    return (
        session.scalar(
            select(SensorReading.id).where(
                SensorReading.sensor_id == sensor_id,
                SensorReading.recorded_at == recorded_at,
                SensorReading.metric == metric,
            )
        )
        is not None
    )


def ingest_readings(session: Session, readings: list[SensorReadingIn]) -> IngestResult:
    """Store readings idempotently (sensor_id, recorded_at, metric). Unknown sensors are auto-registered,
    so a new Pi can start posting without a separate registration step."""
    now = utcnow()
    accepted = duplicates = 0
    seen: set[tuple] = set()
    sensors: dict[str, Sensor] = {}

    for reading in readings:
        sensor = sensors.get(reading.sensor_id) or session.get(Sensor, reading.sensor_id)
        if sensor is None:
            sensor = Sensor(id=reading.sensor_id, meta={}, created_at=now)
            session.add(sensor)
        sensors[reading.sensor_id] = sensor
        if reading.lat is not None and reading.lon is not None:
            sensor.lat, sensor.lon = reading.lat, reading.lon  # devices may be moved; keep the latest position
        sensor.last_seen_at = now

        recorded_at = reading.recorded_at or now
        lat = reading.lat if reading.lat is not None else sensor.lat
        lon = reading.lon if reading.lon is not None else sensor.lon
        raw = reading.model_dump(mode="json")

        for metric, value in reading.metrics.items():
            key = (reading.sensor_id, recorded_at, metric)
            if key in seen or _exists(session, *key):
                duplicates += 1
                continue
            seen.add(key)
            session.add(
                SensorReading(
                    sensor_id=reading.sensor_id,
                    metric=metric,
                    value=value,
                    unit=reading.units.get(metric) or default_unit(metric),
                    recorded_at=recorded_at,
                    received_at=now,
                    lat=lat,
                    lon=lon,
                    quality=reading.quality,
                    raw=raw,
                )
            )
            accepted += 1

    session.commit()
    return IngestResult(accepted=accepted, duplicates=duplicates, sensors=sorted(sensors))
