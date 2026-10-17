# data_core → Frontend API Reference

This is the precise reference for what data the `data_core` backend serves to a frontend (the dashboard SPA)
and how to get it. It is derived directly from the code in `src/data_core/` (routers in `api/`, response
models in `schemas/`). If this file and the code disagree, the code wins. The live OpenAPI spec at
`GET /openapi.json` (Swagger UI at `/docs`) is generated from the same models.

---

## 1. Connection basics

| Item | Value |
|---|---|
| Base URL (local) | `http://localhost:8000` |
| Base URL (hosted) | the Vercel deployment URL, e.g. `https://data-core-xxxx.vercel.app` |
| Protocol | HTTPS/HTTP, JSON request and response bodies (`Content-Type: application/json`) |
| Versioning | all data endpoints are under `/v1/...` |
| Push / realtime | **none for browsers**. No WebSocket or SSE. To pick up updates, poll `GET /v1/cases` (see §6) |
| Machine-readable spec | `GET /openapi.json` (no auth). Good input for type generators such as `openapi-typescript` |

### 1.1 Authentication

Every `/v1/*` endpoint needs an API key. Send it in **one** of these headers:

```
X-API-Key: <key>
Authorization: Bearer <key>
```

Keys are grouped by **role** (configured server-side with `PI_KEYS`, `INPUT_KEYS`, `DASHBOARD_KEYS`, `INTERNAL_KEYS`).
The frontend uses a **dashboard** key. Local default: `dev-dashboard-key`.
The key ends up in the JS bundle, so treat it as a demo key, not a secret.

A missing or wrong key returns:

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer

{"detail": "Invalid or missing API key"}
```

If the server runs with `AUTH_DISABLED=true`, every key (or none) is accepted.

### 1.2 CORS

The browser origin must be listed in the server's `CORS_ORIGINS` env var (comma-separated). The default is
`http://localhost:5173` (`vite dev`). Allowed methods: `GET, POST, OPTIONS`. Allowed request headers:
`X-API-Key, Authorization, Content-Type`. If your dev server runs on another port or host, ask for it to be added.

### 1.3 What a dashboard key can access

| Method & path | dashboard key | Purpose |
|---|:-:|---|
| `GET /health` | no auth needed | Liveness and DB check |
| `GET /v1/stats/summary` | ✅ | Aggregated call statistics |
| `GET /v1/cases` | ✅ | List/filter cases (calls with their recommendations) |
| `GET /v1/cases/{case_id}` | ✅ | One case |
| `GET /v1/cases/{case_id}/context` | ✅ | Full evidence behind a case's recommendation |
| `GET /v1/sensors` | ✅ | All registered field sensors |
| `GET /v1/observations` | ✅ | Raw sensor readings (+ optional weather) around a point |
| `POST /v1/requests` | ❌ (input role) | Submit a caller request. Phone system only |
| `POST /v1/sensor-readings`, `POST /v1/sensors` | ❌ (pi role) | Device ingestion |
| `POST /v1/cases/{id}/retry`, `/internal/tick` | ❌ (internal role) | Ops |

The frontend is **read-only**: no dashboard-accessible endpoint changes data. One side effect exists:
`GET /v1/observations?include_weather=true` may fetch weather from Open-Meteo and cache it in the DB.

---

## 2. Conventions that apply to every response

- **Timestamps** are ISO-8601 strings, always in **UTC with a `Z` suffix**. Fractional seconds are present when non-zero
  and omitted otherwise, so both forms occur:
  `"2026-10-16T19:39:30.572097Z"` and `"2026-10-16T19:39:29Z"`. Parse with `new Date(s)`.
  Query parameters of type datetime accept ISO-8601. Values without a timezone are treated as UTC.
- **Dates** (only in `weather.daily[].date`) are `"YYYY-MM-DD"` strings (UTC days).
- **IDs** (`case.id`, `request.id`) are 32-char lowercase hex strings (UUID4 without dashes).
  `external_id`, `caller_ref` and `sensor_id` are free-form strings set by upstream systems.
- **Nullability**: a field typed `T | null` below is always present in the JSON, with value `null` when unknown.
  The backend does not omit keys.
- **Coordinates**: WGS84 decimal degrees, `lat` ∈ [-90, 90], `lon` ∈ [-180, 180].
- **Distances** are kilometres (`*_km`), rounded to 3 decimals. **Durations** use suffixes `_h` (hours) or `_s` (seconds).
- **Labels** `problem_type` and `crop` are normalised on ingest: trimmed, lowercased, spaces → `_`
  (e.g. `"Crop Health"` → `"crop_health"`).
- **Errors** always come as `{"detail": ...}`:
  - `401`: `{"detail": "Invalid or missing API key"}`
  - `404`: `{"detail": "Case not found"}` or `{"detail": "Context not built yet"}`
  - `422` (bad query param): `{"detail": [{"type": "...", "loc": ["query", "limit"], "msg": "...", "input": ...}]}`
  - `503` from `/health` only: `{"status": "error", "db": "<error text>"}`

---

## 3. Domain model (what the data means)

```
Caller (pseudonymous caller_ref)
  └─ CallerRequest   one phone call / Telegram message: text, problem_type, crop, symptoms, location
       └─ Case       processing state of that request through the pipeline (1:1 with the request)
            ├─ DecisionContext  evidence gathered for it: weather, nearby sensors, nearby earlier reports
            ├─ Recommendation   result of the recommender: disease, confidence, risk_level, actions
            └─ Deliveries       webhook push attempts to the dashboard/phone backends

Sensor (field device, e.g. Raspberry Pi)
  └─ SensorReading   one metric value at one time (humidity_pct, temperature_c, ...)
```

The **case** is the main record for the UI. A case embeds its request, its recommendation and its delivery
status. Its evidence is fetched separately via `/context` because it is large.

### 3.1 Case lifecycle (`case.status`)

```
received ──► context_built ──► recommended ──► delivered
    │               │
    ▼               ▼
failed_context   failed_recommend      (both are retried automatically, up to 5 attempts in total)
```

| status | Meaning | `recommendation` | `/context` |
|---|---|---|---|
| `received` | Stored, processing not finished | `null` | 404 |
| `context_built` | Evidence gathered, recommender not yet answered | `null` | ✅ |
| `failed_context` | Gathering evidence crashed; `last_error` says why | `null` | 404 (unless built in an earlier attempt) |
| `failed_recommend` | Recommender call failed; `last_error` says why | `null` | ✅ |
| `recommended` | Recommendation exists, ≥1 webhook not yet delivered | ✅ | ✅ |
| `delivered` | Recommendation exists and all webhooks were sent (also set directly when no webhooks are configured) | ✅ | ✅ |

For display, **`recommended` and `delivered` both mean "has a solution"**. Processing is synchronous (the
phone system's POST waits for it), so in practice almost all cases are `delivered`, or `failed_*` on errors.

---

## 4. Endpoints in detail

### 4.1 `GET /health`

No auth. Use it for a connectivity indicator and a "what is mocked" banner.

```json
{
  "status": "ok", "db": "ok", "version": "0.1.0",
  "mocks": {
    "weather": false, "geocoding": false, "sensors": true, "caller_requests": true,
    "recommender": true, "delivery": true, "planner": "fetch_all"
  }
}
```

`mocks` mirrors the backend's `config.yaml`. `true` means that component is a stand-in (or mock data is accepted).
When `caller_requests` is `false`, demo calls never appear in `/v1/cases` or the stats. When `sensors` is `false`,
readings with `quality: "mocked"` never appear. Similar reports in the context carry `is_mock` per item.

On DB failure: HTTP `503`, `{"status": "error", "db": "<message>"}`.

---

### 4.2 `GET /v1/stats/summary`: call statistics

| Query param | Type | Default | Constraint |
|---|---|---|---|
| `days` | int | `30` | 1–365. Window = the last `days` × 24 h before *now* |

The window is applied to `request.received_at` (when the call came in).

**Response `StatsSummary`**

| Field | Type | Meaning |
|---|---|---|
| `since` | datetime | Start of the window (`now - days`) |
| `days` | int | Echo of the parameter |
| `total_calls` | int | Caller requests received in the window (each case counted once) |
| `distinct_callers` | int | Distinct non-null `caller_ref`. Anonymous calls are not counted here |
| `repeat_callers` | int | Callers with > 1 call in the window |
| `problems` | `ProblemCount[]` | Calls per `problem_type`, most frequent first, ties alphabetical. One entry may have `problem_type: null` (unclassified) |

```json
{
  "since": "2026-09-16T12:00:00.000000Z",
  "days": 30,
  "total_calls": 30,
  "distinct_callers": 17,
  "repeat_callers": 9,
  "problems": [
    {"problem_type": "crop_health", "count": 12},
    {"problem_type": "pests", "count": 10},
    {"problem_type": null, "count": 1}
  ]
}
```

---

### 4.3 `GET /v1/cases`: list and filter cases

Use it for the call history, map pins, a caller's earlier calls, and polling for new data.

| Query param | Type | Default | Filters on |
|---|---|---|---|
| `status` | string | – | `case.status` exact match (see §3.1) |
| `problem_type` | string | – | `request.problem_type` exact match (use the normalised form, e.g. `crop_health`) |
| `caller_ref` | string | – | `request.caller_ref` exact match → all calls of one caller |
| `since` | datetime | – | `request.received_at >= since` |
| `until` | datetime | – | `request.received_at <= until` |
| `min_lat`, `max_lat`, `min_lon`, `max_lon` | float | – | Bounding box on `request.lat/lon`. Each bound applies independently. When any bound is set, cases without coordinates are excluded |
| `limit` | int | `50` | 1–500 |
| `offset` | int | `0` | ≥ 0 |

All filters combine with AND.

**Ordering:** newest first by **`case.created_at`** (when the backend stored it). Usually this equals
`request.received_at`. For back-dated imports such as demo seed data, `received_at` can be older, so sort
client-side by `request.received_at` if you show a call timeline.

**Pagination:** `total` is the number of matches ignoring `limit`/`offset`. Page with `offset += limit` until `offset >= total`.

**Response `CaseList`**

```json
{ "total": 123, "items": [ /* CaseOut, see below */ ] }
```

---

### 4.4 `GET /v1/cases/{case_id}`: one case

Returns `CaseOut`. `404 {"detail":"Case not found"}` for an unknown id.

**`CaseOut`**

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Case id |
| `status` | string | See §3.1 |
| `attempts` | int | Processing attempts so far (max 5 automatic) |
| `last_error` | string \| null | Error of the last failed step, e.g. `"HTTPStatusError: ..."`. `null` when OK |
| `created_at` | datetime | Case stored |
| `updated_at` | datetime | Last status change |
| `request` | `CallerRequestOut` | What the caller reported (below) |
| `recommendation` | `RecommendationOut` \| null | The solution given. `null` until status `recommended` |
| `deliveries` | `DeliveryOut[]` | Webhook delivery attempts. Empty when no webhooks are configured |

**`CallerRequestOut`** (`case.request`)

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Request id (≠ case id) |
| `external_id` | string \| null | Id from the phone/Telegram system (idempotency key) |
| `channel` | string | Origin: e.g. `phone_call`, `telegram`, `demo`, `unknown` (free-form) |
| `caller_ref` | string \| null | Pseudonymous caller id. Group by it for "earlier calls" |
| `received_at` | datetime | When the call/message was received |
| `text` | string | What the farmer said (transcript/summary), up to 10 000 chars |
| `problem_type` | string \| null | Category, normalised (e.g. `crop_health`, `pests`, `weather_damage`, `soil`). Open vocabulary, not an enum |
| `crop` | string \| null | Normalised crop name (e.g. `maize`, `beans`) |
| `symptoms` | string[] | Free-text symptoms (e.g. `["yellow leaves","wilting"]`). May be empty |
| `lat`, `lon` | float \| null | Caller location. `null` if unknown |
| `location_name` | string \| null | Village/place name as reported |
| `location_precision_m` | float \| null | Uncertainty radius in metres (geocoded places: `5000`) |
| `location_source` | string \| null | `"caller"` (coordinates given), `"geocoded"` (derived from `location_name`, approximate), or `null` (no location) |
| `reported_event_time` | datetime \| null | When the problem started, if the caller said so |
| `extra` | object | Any additional upstream fields, passed through unchanged. Known keys (all optional): `duration_s` (int, call length in s), `reported_weather` (string, weather as described by the farmer), `demo` (`true` on seeded demo data) |

**`RecommendationOut`** (`case.recommendation`)

| Field | Type | Meaning |
|---|---|---|
| `disease` | string \| null | Predicted disease/problem, snake_case (e.g. `suspected_fungal_disease`). `null` = nothing identified |
| `confidence` | float \| null | 0–1 |
| `risk_level` | string \| null | `low` \| `medium` \| `high` \| `unknown` |
| `explanation` | string \| null | Human-readable reasoning. The current mock recommender prefixes it with `[MOCK RECOMMENDER]` |
| `actions` | string[] | Recommended actions for the farmer, in order |
| `created_at` | datetime | When the recommendation was produced |

**`DeliveryOut`** (`case.deliveries[]`)

| Field | Type | Meaning |
|---|---|---|
| `channel` | string | `dashboard` or `phone` |
| `status` | string | `pending` \| `sent` \| `failed` (gave up after 10 attempts) |
| `attempts` | int | Send attempts |
| `last_error` | string \| null | Last send error |
| `sent_at` | datetime \| null | When it was delivered |

Full example: [`examples/case_response.json`](examples/case_response.json).

---

### 4.5 `GET /v1/cases/{case_id}/context`: evidence behind a recommendation

Returns the **`DecisionContext`**, the exact data package the recommender received. It is a snapshot taken
when the case was processed. It does not change later, even if new sensor data arrives.

Errors: `404 {"detail":"Case not found"}`, `404 {"detail":"Context not built yet"}` (status `received`/`failed_context`).

**`DecisionContext`**

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | string | Currently `"1.0"` |
| `case_id` | string | |
| `generated_at` | datetime | When the evidence was collected |
| `request` | `RequestSummary` | Snapshot of the request (below) |
| `plan` | `DataPlan` | Which data the core decided to fetch and why |
| `evidence` | `Evidence` | The gathered data: `weather`, `sensors`, `caller_history` |
| `gaps` | string[] | Data that was wanted but is unavailable. Show these as "missing data" |
| `warnings` | string[] | Caveats about the data that was used. Show these as "data quality" notes |

**`RequestSummary`**: same information as `CallerRequestOut`, shaped differently:
`request_id, external_id, channel, received_at, text, problem_type, crop, symptoms, location, location_source, reported_event_time`,
where `location` is `{lat, lon, name, precision_m}` (each nullable) or `null` when neither coordinates nor a name exist.
It contains no `caller_ref` and no `extra`.

**`DataPlan`**

```ts
{ strategy: string;            // currently always "fetch_all"
  needs: DataNeed[];           // one per source
  notes: string[] }
DataNeed = { source: "sensors" | "weather" | "caller_history";
             metrics: string[] | null; radius_km: number | null;
             lookback_h: number | null; forecast_h: number | null;
             filters: object; priority: "required" | "optional"; reason: string }
```

With the current defaults: weather (336 h / 14 days back, 48 h forecast), sensors within 50 km over 336 h, caller history within 50 km over 336 h.

**`evidence.weather`: `WeatherEvidence | null`** (`null` if the caller location is unknown or weather failed, in which case there is a gap entry)

| Field | Type | Meaning |
|---|---|---|
| `provider` | string | `open_meteo` (real) or `mock` (synthetic, also adds a warning) |
| `lat`, `lon` | float | Grid point the weather refers to (can differ slightly from the caller location) |
| `fetched_at` | datetime | When it was fetched from the provider |
| `from_cache` | bool | Served from the ~15-min backend cache |
| `current` | object | Conditions at fetch time. Keys for `open_meteo`: `temperature_2m` (°C), `relative_humidity_2m` (%), `precipitation` (mm), `wind_speed_10m` (km/h). The `mock` provider has `soil_moisture_0_to_1cm` instead of wind. Treat the keys as optional |
| `past` | `WeatherWindow` | Aggregate over the last `past.hours` hours |
| `forecast` | `WeatherWindow` | Aggregate over the next `forecast.hours` hours |
| `daily` | object[] | Per-day rows `{date: "YYYY-MM-DD", temperature_2m_max, temperature_2m_min, precipitation_sum}` (°C, °C, mm), covering past and forecast days. **Empty array for the `mock` provider** |

`WeatherWindow` (all aggregates are `null` when there were no data points):

| Field | Type | Unit / meaning |
|---|---|---|
| `hours` | int | Window length |
| `n_points` | int | Hourly points aggregated |
| `precipitation_mm` | float \| null | Total rain (mm) |
| `mean_temp_c`, `min_temp_c`, `max_temp_c` | float \| null | °C |
| `mean_rh_pct` | float \| null | Mean relative humidity (%) |
| `hours_rh_ge_90` | int \| null | Hours with humidity ≥ 90 % (leaf-wetness proxy, key disease indicator) |
| `mean_soil_moisture` | float \| null | Volumetric, m³/m³ (0–1), top 1 cm |

**`evidence.sensors`: `SensorEvidence[]`**: one entry per (sensor, metric) within the radius/window, nearest first. Empty if none.

| Field | Type | Meaning |
|---|---|---|
| `sensor_id` | string | |
| `metric` | string | snake_case metric name, e.g. `humidity_pct`, `temperature_c`, `rain_mm` |
| `unit` | string \| null | e.g. `%`, `°C`, `mm`, `hPa`, `NTU`, `m/s`, `lx` |
| `latest_value` | float | Most recent value |
| `latest_at` | datetime | Time of the most recent value |
| `mean`, `min`, `max` | float | Over the window |
| `n_readings` | int | Readings aggregated |
| `distance_km` | float | Distance from the caller |
| `age_s` | int | Age of `latest_value` at context time. > 21 600 s (6 h) produces a "stale" warning |
| `quality` | string | Worst quality in the window: `ok` < `mocked` < `suspect` |

**`evidence.caller_history`: `CallerHistoryEvidence | null`**: earlier reports from *other* calls nearby

| Field | Type | Meaning |
|---|---|---|
| `radius_km`, `lookback_h` | number | Search window used |
| `total_count` | int | Reports found in the window |
| `same_problem_count` | int | Of those, with the same `problem_type` |
| `items` | `SimilarReport[]` | Newest first, max 50 |

`SimilarReport`: `request_id, received_at, problem_type, crop, text` (truncated to 300 chars),
`distance_km, same_problem_type` (bool), `disease` (the recommendation given for that earlier report, or `null`).
These items contain a `request_id`, not a case id. To link to the earlier case, query `GET /v1/cases` (there is no lookup by request id).

**Possible `gaps` strings** (match on prefixes, the texts are not a formal enum):
- `"Caller location unknown: weather, sensor and caller-history lookups skipped"`
- `"No sensor readings within 50 km in the last 336 h"`
- `"<source> unavailable: <ErrorType>: <message>"` (e.g. weather API down)

**Possible `warnings` strings:**
- `"Location approximated from place name 'Kiambu'"`
- `"Weather data is mocked"`
- `"Some sensor data is mocked"`
- `"Stale sensor data (> 6 h old): pi-field-01, pi-field-02"`

Full example: [`examples/decision_context.json`](examples/decision_context.json).
In that example file, `°C` appears mis-encoded as `Â°C`. The API itself returns proper UTF-8 `°C`.

---

### 4.6 `GET /v1/sensors`: sensor registry / coverage

No parameters, no pagination. Returns all sensors ordered by `id`.

**`SensorOut[]`**

| Field | Type | Meaning |
|---|---|---|
| `id` | string | Sensor id (e.g. `pi-field-01`) |
| `name` | string \| null | Display name, if registered |
| `kind` | string \| null | e.g. `humidity`, `rain`, `multi` |
| `lat`, `lon` | float \| null | Last known position (updated by every reading that carries coordinates) |
| `meta` | object | Free-form metadata |
| `created_at` | datetime | First seen / registered |
| `last_seen_at` | datetime \| null | Server time of the last received reading. **Use this for "online/offline"**, e.g. offline if older than 1–6 h. `null` = registered but never sent data |

Sensors auto-register on their first reading, so most of them have `name`, `kind` and `meta` empty.

---

### 4.7 `GET /v1/observations`: raw readings (and weather) around a point

Use it for sensor charts/time series and current weather at a map location.

| Query param | Type | Default | Constraint / meaning |
|---|---|---|---|
| `lat` | float | **required** | -90…90 |
| `lon` | float | **required** | -180…180 |
| `radius_km` | float | `10` | > 0, ≤ 200 |
| `since_h` | int | `72` | 1–744. Readings with `recorded_at` within the last N hours |
| `metric` | string | – | Only this metric (e.g. `humidity_pct`) |
| `include_weather` | bool | `false` | Also return `WeatherEvidence` for the point (past window = `since_h`, forecast 48 h) |
| `limit` | int | `1000` | 1–5000, max readings returned |

**Response**

```ts
{ sensors: SensorReadingOut[];       // newest first (by recorded_at), across all sensors/metrics in range
  weather: WeatherEvidence | null }  // null unless include_weather=true
```

`SensorReadingOut`: one row per metric per measurement.

| Field | Type | Meaning |
|---|---|---|
| `sensor_id` | string | |
| `metric` | string | e.g. `humidity_pct` |
| `value` | float | |
| `unit` | string \| null | |
| `recorded_at` | datetime | Measurement time (device clock) |
| `lat`, `lon` | float \| null | Position at measurement time |
| `quality` | string | `ok` \| `suspect` \| `mocked` |
| `distance_km` | float | Distance from the query point |

For a chart, group by `(sensor_id, metric)` and sort ascending by `recorded_at`. If `limit` is reached,
the **oldest** readings are dropped.
If an upstream weather call fails with `include_weather=true`, the whole request fails (HTTP 500). Retry without weather if needed.

---

## 5. TypeScript types

These are hand-written from the Pydantic models. You can generate them instead from `/openapi.json`.

```ts
export type ISODateTime = string; // UTC, "Z" suffix

export type CaseStatus =
  | "received" | "context_built" | "recommended" | "delivered"
  | "failed_context" | "failed_recommend";

export interface CallerRequestOut {
  id: string;
  external_id: string | null;
  channel: string;
  caller_ref: string | null;
  received_at: ISODateTime;
  text: string;
  problem_type: string | null;
  crop: string | null;
  symptoms: string[];
  lat: number | null;
  lon: number | null;
  location_name: string | null;
  location_precision_m: number | null;
  location_source: "caller" | "geocoded" | null;
  reported_event_time: ISODateTime | null;
  extra: { duration_s?: number; reported_weather?: string; demo?: boolean; [k: string]: unknown };
}

export interface RecommendationOut {
  disease: string | null;
  confidence: number | null;           // 0..1
  risk_level: "low" | "medium" | "high" | "unknown" | null;
  explanation: string | null;
  actions: string[];
  created_at: ISODateTime;
}

export interface DeliveryOut {
  channel: "dashboard" | "phone";
  status: "pending" | "sent" | "failed";
  attempts: number;
  last_error: string | null;
  sent_at: ISODateTime | null;
}

export interface CaseOut {
  id: string;
  status: CaseStatus;
  attempts: number;
  last_error: string | null;
  created_at: ISODateTime;
  updated_at: ISODateTime;
  request: CallerRequestOut;
  recommendation: RecommendationOut | null;
  deliveries: DeliveryOut[];
}

export interface CaseList { total: number; items: CaseOut[] }

export interface StatsSummary {
  since: ISODateTime;
  days: number;
  total_calls: number;
  distinct_callers: number;
  repeat_callers: number;
  problems: { problem_type: string | null; count: number }[];
}

export interface Location { lat: number | null; lon: number | null; name: string | null; precision_m: number | null }

export interface WeatherWindow {
  hours: number;
  n_points: number;
  precipitation_mm: number | null;
  mean_temp_c: number | null;
  min_temp_c: number | null;
  max_temp_c: number | null;
  mean_rh_pct: number | null;
  hours_rh_ge_90: number | null;
  mean_soil_moisture: number | null;
}

export interface WeatherEvidence {
  provider: "open_meteo" | "mock" | string;
  lat: number;
  lon: number;
  fetched_at: ISODateTime;
  from_cache: boolean;
  current: {
    temperature_2m?: number; relative_humidity_2m?: number; precipitation?: number;
    wind_speed_10m?: number; soil_moisture_0_to_1cm?: number; [k: string]: number | undefined;
  };
  past: WeatherWindow;
  forecast: WeatherWindow;
  daily: { date: string; temperature_2m_max: number | null; temperature_2m_min: number | null; precipitation_sum: number | null }[];
}

export interface SensorEvidence {
  sensor_id: string; metric: string; unit: string | null;
  latest_value: number; latest_at: ISODateTime;
  mean: number; min: number; max: number; n_readings: number;
  distance_km: number; age_s: number; quality: "ok" | "suspect" | "mocked";
}

export interface SimilarReport {
  request_id: string; received_at: ISODateTime;
  problem_type: string | null; crop: string | null; text: string;
  distance_km: number; same_problem_type: boolean; disease: string | null;
}

export interface CallerHistoryEvidence {
  radius_km: number; lookback_h: number;
  total_count: number; same_problem_count: number; items: SimilarReport[];
}

export interface DataNeed {
  source: "sensors" | "weather" | "caller_history";
  metrics: string[] | null; radius_km: number | null;
  lookback_h: number | null; forecast_h: number | null;
  filters: Record<string, unknown>; priority: "required" | "optional"; reason: string;
}

export interface DecisionContext {
  schema_version: string;
  case_id: string;
  generated_at: ISODateTime;
  request: {
    request_id: string; external_id: string | null; channel: string; received_at: ISODateTime;
    text: string; problem_type: string | null; crop: string | null; symptoms: string[];
    location: Location | null; location_source: "caller" | "geocoded" | null;
    reported_event_time: ISODateTime | null;
  };
  plan: { strategy: string; needs: DataNeed[]; notes: string[] };
  evidence: {
    weather: WeatherEvidence | null;
    sensors: SensorEvidence[];
    caller_history: CallerHistoryEvidence | null;
  };
  gaps: string[];
  warnings: string[];
}

export interface SensorOut {
  id: string; name: string | null; kind: string | null;
  lat: number | null; lon: number | null; meta: Record<string, unknown>;
  created_at: ISODateTime; last_seen_at: ISODateTime | null;
}

export interface SensorReadingOut {
  sensor_id: string; metric: string; value: number; unit: string | null;
  recorded_at: ISODateTime; lat: number | null; lon: number | null;
  quality: "ok" | "suspect" | "mocked"; distance_km: number | null;
}

export interface ObservationsOut { sensors: SensorReadingOut[]; weather: WeatherEvidence | null }
```

### Minimal client

```ts
const BASE = import.meta.env.VITE_API_URL;        // e.g. http://localhost:8000
const KEY  = import.meta.env.VITE_API_KEY;        // a DASHBOARD_KEYS value

async function api<T>(path: string, params: Record<string, string | number | boolean | undefined> = {}): Promise<T> {
  const url = new URL(path, BASE);
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  const res = await fetch(url, { headers: { "X-API-Key": KEY } });
  if (!res.ok) throw new Error(`${res.status}: ${JSON.stringify((await res.json().catch(() => ({}))).detail)}`);
  return res.json() as Promise<T>;
}

// api<StatsSummary>("/v1/stats/summary", { days: 30 })
// api<CaseList>("/v1/cases", { since: d.toISOString(), problem_type: "pests", limit: 100 })
// api<DecisionContext>(`/v1/cases/${id}/context`)
// api<ObservationsOut>("/v1/observations", { lat, lon, radius_km: 5, include_weather: true })
```

---

## 6. Recipes: UI need → request

| UI need | Request | Notes |
|---|---|---|
| KPI tiles (calls, callers, repeat callers) | `GET /v1/stats/summary?days=30` | |
| Problem breakdown chart | same, `problems[]` | `null` problem_type = "unclassified" |
| Call history table | `GET /v1/cases?limit=50&offset=…` | Status, request fields, recommendation summary in one call |
| Map pins of calls | `GET /v1/cases?min_lat=…&max_lat=…&min_lon=…&max_lon=…&since=…&limit=500` | Use `request.lat/lon`. Show `location_precision_m` as an uncertainty circle when `location_source="geocoded"` |
| Filter by problem / time | `problem_type=`, `since=`, `until=` | |
| Earlier calls of the same caller | `GET /v1/cases?caller_ref=<request.caller_ref>` | Skip when `caller_ref` is `null`. The result includes the current case |
| Call detail + solution | `GET /v1/cases/{id}` | `recommendation` may be `null` → show status/`last_error` |
| "Why this recommendation?" panel | `GET /v1/cases/{id}/context` | Weather at call time, sensors used, similar nearby reports, `gaps`, `warnings` |
| Weather at the time of the call | `/context` → `evidence.weather` | Historic snapshot. Weather "now" comes from `/v1/observations?include_weather=true` |
| Sensor map / online status | `GET /v1/sensors` | Online if `now - last_seen_at` < threshold you choose |
| Sensor time-series chart | `GET /v1/observations?lat=<sensor.lat>&lon=<sensor.lon>&radius_km=0.1&since_h=168` | Filter client-side by `sensor_id`. Add `metric=` to restrict |
| Current weather at a point | `GET /v1/observations?lat=…&lon=…&include_weather=true&limit=1` | `weather.current`, `weather.forecast`, `weather.daily` |
| Mark demo data | `request.channel === "demo"` or `request.extra.demo === true` | |
| Call duration | `request.extra.duration_s` | Optional |
| Farmer-described weather | `request.extra.reported_weather` | Optional |
| Live updates | Poll `GET /v1/cases?since=<newest received_at seen>` every 10–30 s | No push channel for browsers |
| Backend reachable? | `GET /health` | |

---

## 7. Things the backend does **not** provide (as of now)

- No push to browsers (no WebSocket/SSE). The `case.recommended` webhook goes server-to-server only.
- No write endpoints for the dashboard: no editing cases or recommendations, no notes or acknowledgements.
- No full-text search over `text`, no sorting options, no filtering by `crop`, `channel`, `risk_level` or `disease`. Do these client-side on the fetched page.
- No lookup by `request_id` or `external_id` (the `/v1/cases` filters don't include them).
- No per-sensor history endpoint. Use `/v1/observations` around the sensor's position.
- No caller identity data beyond the pseudonymous `caller_ref`.
- Vocabularies (`problem_type`, `crop`, `disease`, `metric`, `channel`) are open strings set by upstream systems, not fixed enums.
- The recommender is currently a **mock** (`explanation` starts with `[MOCK RECOMMENDER]`, `disease` is `suspected_fungal_disease` or `null`).

## 8. Local setup for frontend developers

```bash
# in this repo
pip install -e ".[dev]" && cp .env.example .env
uvicorn data_core.asgi:app --reload                      # http://localhost:8000/docs
python mocks/pi_simulator.py --backfill-hours 24 --count 3   # sensor data
python mocks/seed_demo.py --count 30                         # 30 demo calls over the last 30 days
```

Frontend env: `VITE_API_URL=http://localhost:8000`, `VITE_API_KEY=dev-dashboard-key`. Run the dev server on
`http://localhost:5173` or add your origin to `CORS_ORIGINS` in `.env`.
