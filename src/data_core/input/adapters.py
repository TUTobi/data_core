"""Tolerant mapping of incoming caller payloads onto the internal request model.

The final layout of the structured input (phone call / Telegram / ...) is not decided yet.
When the upstream format changes, add aliases here instead of touching the core:
- known aliases are renamed to canonical fields,
- flat location fields (latitude/longitude/village...) are folded into `location`,
- anything unknown is preserved in `extra` rather than rejected.
"""

from typing import Any

FIELD_ALIASES: dict[str, str] = {
    "description": "text",
    "transcript": "text",
    "message": "text",
    "summary": "text",
    "source": "channel",
    "reported_at": "received_at",
    "created_at": "received_at",
    "timestamp": "received_at",
    "id": "external_id",
    "request_id": "external_id",
    "call_id": "external_id",
    "problem": "problem_type",
    "category": "problem_type",
    "caller_id": "caller_ref",
    "event_time": "reported_event_time",
    "callback": "callback_url",
}

LOCATION_ALIASES: dict[str, str] = {
    "lat": "lat",
    "latitude": "lat",
    "lon": "lon",
    "lng": "lon",
    "longitude": "lon",
    "village": "name",
    "place": "name",
    "location_name": "name",
    "accuracy_m": "precision_m",
    "precision_m": "precision_m",
}


def adapt_payload(data: Any, known_fields: set[str]) -> Any:
    if not isinstance(data, dict):
        return data

    extra: dict[str, Any] = dict(data.get("extra") or {})
    raw_location = data.get("location")
    if isinstance(raw_location, dict):
        location = {LOCATION_ALIASES.get(k, k): v for k, v in raw_location.items()}
    elif isinstance(raw_location, str):
        location = {"name": raw_location}
    else:
        location = {}

    out: dict[str, Any] = {}
    # Canonical names first so they win over aliases.
    for key, value in data.items():
        if key in known_fields and key not in ("extra", "location"):
            out[key] = value
    for key, value in data.items():
        if key in known_fields or key in ("extra", "location"):
            continue
        if key in LOCATION_ALIASES:
            location.setdefault(LOCATION_ALIASES[key], value)
            continue
        target = FIELD_ALIASES.get(key)
        if target and target in known_fields and target not in out:
            out[target] = value
        else:
            extra[key] = value

    if isinstance(out.get("symptoms"), str):
        out["symptoms"] = [s.strip() for s in out["symptoms"].split(",") if s.strip()]
    if location:
        out["location"] = location
    if extra:
        out["extra"] = extra
    return out
