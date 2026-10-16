
# Sensor service → data_core: interface contract

This page defines how a field device (Raspberry Pi or any other sensor gateway) sends measurements to `data_core`.
It is derived from the code (`src/data_core/api/sensors.py`, `src/data_core/schemas/sensors.py`,
`src/data_core/ingestion/sensor_service.py`). If this file and the code disagree, the code wins.
JSON Schemas: `contracts/schemas/sensor_reading.in.schema.json`, `contracts/schemas/sensor_reading_batch.in.schema.json`.

---

## 1. Summary

| Item | Value |
|---|---|
| Direction | **Push**: the sensor service calls `data_core`. `data_core` never calls the sensor service |
| Transport | HTTPS, `POST`, JSON body (`Content-Type: application/json`) |
| Endpoint | `POST {BASE_URL}/v1/sensor-readings` |
| Base URL (hosted) | `https://datacore-eta.vercel.app` |
| Base URL (local) | `http://localhost:8000` |
| Auth | header `X-API-Key: <pi key>` (or `Authorization: Bearer <pi key>`). Not needed while the server runs with `AUTH_DISABLED=true` |
| Call style | synchronous request/response, fire-and-forget from the device's point of view |
| Frequency | free to choose. Recommended: every 5–15 min, or buffer and send a batch |
| Idempotency | yes: re-sending the same reading is safe (see §5) |
| Registration | not required. An unknown `sensor_id` is registered automatically on its first reading |

---

## 2. Request body

Send either **one reading** or a **batch** `{"readings": [...]}` with 1–1000 readings.

### 2.1 One reading

```json
{
  "sensor_id": "pi-field-01",
  "recorded_at": "2026-10-16T14:00:00Z",
  "lat": -1.175,
  "lon": 36.836,
  "metrics": {
    "humidity_pct": 87.5,
    "temperature_c": 22.4
  }
}
```

| Field | Type | Required | Rules / meaning |
|---|---|:-:|---|
| `sensor_id` | string | ✅ | 1–64 chars. Stable, unique id per device, e.g. `pi-field-01` |
| `recorded_at` | ISO-8601 datetime | – | Time of **measurement**. Send UTC with `Z` (a timestamp without a timezone is read as UTC). Missing → time of receipt. **Always send it** if the device buffers readings, otherwise idempotency and time windows break |
| `lat` | number | – | −90…90, WGS84 decimal degrees. Missing → last known position of the sensor |
| `lon` | number | – | −180…180. Must be sent together with `lat` |
| `metrics` | object `{name: number}` | ✅ | At least one entry. Values must be numbers (no strings, no `null`) |
| `units` | object `{name: string}` | – | Optional unit per metric. Missing → derived from the name suffix (§3) |
| `quality` | `"ok"` \| `"suspect"` \| `"mocked"` | – | Default `"ok"`. Use `"suspect"` for implausible values, `"mocked"` for simulated data |

**Location:** a device without GPS should send `lat`/`lon` at least once (or register via §6). Readings without
any known position are stored but **never used** for recommendations, because the core searches sensors by
distance to the caller (default radius 10 km, last 72 h).

### 2.2 Batch

```json
{
  "readings": [
    {"sensor_id": "pi-field-01", "recorded_at": "2026-10-16T14:00:00Z", "metrics": {"humidity_pct": 87.5}},
    {"sensor_id": "pi-field-01", "recorded_at": "2026-10-16T14:10:00Z", "metrics": {"humidity_pct": 88.1}}
  ]
}
```

The whole batch is validated first: one invalid reading rejects the whole batch with `422`.

---

## 3. Metric names and units

Metric names must be **snake_case**: start with a lowercase letter, then `a-z`, `0-9`, `_`, at most 64 chars
(regex `^[a-z][a-z0-9_]{0,63}$`). Put the unit in the name as a suffix, so it is derived automatically:

| Suffix | Unit | Example |
|---|---|---|
| `_pct` | % | `humidity_pct`, `soil_moisture_pct` |
| `_c` | °C | `temperature_c`, `soil_temperature_c` |
| `_mm` | mm | `rain_mm` |
| `_hpa` | hPa | `pressure_hpa` |
| `_ms` | m/s | `wind_speed_ms` |
| `_lux` | lx | `light_lux` |
| `_ntu` | NTU | `turbidity_ntu` |

Please use these names for the common measurements, so all devices report comparable data:
`humidity_pct` (relative air humidity), `temperature_c` (air temperature), `soil_moisture_pct`, `rain_mm`
(rain **since the previous reading**). Any other metric is accepted and stored as well.

**Soil-wetness sensor:** send its raw value as `soil_wetness_raw` (scale of the recommender: Dry ≈ 120,
A bit wet ≈ 850, Very wet ≈ 2500, Submerged ≈ 3600). The nearest such reading is passed to the recommender as the
current soil condition; without one, soil moisture is estimated from weather data.

---

## 4. Responses

| Status | When | Body |
|---|---|---|
| `201 Created` | stored (also when some or all readings were duplicates) | `{"accepted": 2, "duplicates": 0, "sensors": ["pi-field-01"]}` |
| `401 Unauthorized` | missing/wrong key | `{"detail": "Invalid or missing API key"}` |
| `409 Conflict` | the same reading arrived twice at the same moment | `{"detail": "Concurrent duplicate reading; retry the request"}` → retry |
| `422 Unprocessable Entity` | invalid body (bad metric name, missing `metrics`, `lat` out of range, ...) or `quality: "mocked"` while mock data is disabled | `{"detail": [...]}` describing the problem. **Do not retry**, fix the payload |
| `5xx` / network error | server or connection problem | retry later |

`accepted` and `duplicates` count **metric values**, not readings: one reading with two metrics counts as 2.

---

## 5. Retries and buffering (recommended device behaviour)

- Readings are unique per (`sensor_id`, `recorded_at`, metric). Sending the same reading again is ignored and
  counted as a duplicate, so **retrying after a timeout or network error is always safe**.
- This only works if `recorded_at` is set by the device. Without it the server uses its own time and a retry creates
  a second reading.
- While offline, keep readings in a local buffer and send them later as a batch (≤ 1000 per request).
- Retry on network errors, `409` and `5xx` with backoff (e.g. 10 s, 30 s, 2 min, ...). Drop on `422`.
- Use a request timeout of ~30 s. The first request after a pause can take a few seconds longer (cold start).

---

## 6. Optional: register or describe a sensor

Not needed for sending data, but useful to give a sensor a name and a fixed position (e.g. a device without GPS).

`POST {BASE_URL}/v1/sensors` (same pi key) — creates or updates (fields left out stay unchanged):

```json
{
  "id": "pi-field-01",
  "name": "Kiambu demo field",
  "kind": "multi",
  "lat": -1.175,
  "lon": 36.836,
  "meta": {"hardware": "Raspberry Pi 4 + DHT22"}
}
```

Response `200` with the stored sensor (`id`, `name`, `kind`, `lat`, `lon`, `meta`, `created_at`, `last_seen_at`).

---

## 7. Test it

```bash
curl -X POST https://datacore-eta.vercel.app/v1/sensor-readings \
     -H "Content-Type: application/json" -H "X-API-Key: <pi key>" \
     -d '{"sensor_id":"pi-test-01","recorded_at":"2026-10-17T10:00:00Z","lat":-1.2921,"lon":36.8219,"metrics":{"humidity_pct":88,"temperature_c":21.5}}'
```

A simulator that behaves like a real device: `python mocks/pi_simulator.py --url <BASE_URL> --key <pi key>`.
Interactive docs with all fields: `{BASE_URL}/docs`.
