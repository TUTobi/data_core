# Phone service → data_core: interface contract

This page defines how the phone/caller system (IVR, call-center tool, Telegram bot, ...) hands a farmer's call to
`data_core` and how it gets the recommendation back. It is derived from the code (`src/data_core/api/requests.py`,
`src/data_core/schemas/requests.py`, `src/data_core/schemas/cases.py`, `src/data_core/delivery/outbox.py`).
If this file and the code disagree, the code wins.
JSON Schemas: `contracts/schemas/caller_request.in.schema.json`, `contracts/schemas/webhook.case_recommended.schema.json`.

---

## 1. Summary

| Item | Value |
|---|---|
| Direction | The phone service **calls** `data_core` once per call. Optionally `data_core` calls back via webhook (§5) |
| Transport | HTTPS, `POST`, JSON body (`Content-Type: application/json`) |
| Endpoint | `POST {BASE_URL}/v1/requests` |
| Base URL (hosted) | `https://datacore-eta.vercel.app` |
| Base URL (local) | `http://localhost:8000` |
| Auth | header `X-API-Key: <input key>` (or `Authorization: Bearer <input key>`). Not needed while the server runs with `AUTH_DISABLED=true` |
| Call style | **synchronous**: the response already contains the recommendation. Typically 2–10 s, worst case up to 60 s |
| When to call | after the call has been transcribed/structured, i.e. once you have at least the farmer's description |
| Idempotency | yes, via `external_id` (§4) |

**What the phone service has to do:** turn the call into the JSON in §2, `POST` it, read
`recommendation` from the response (§3) and tell the farmer the result.

---

## 2. Request body

```json
{
  "external_id": "call-2026-10-16-0001",
  "channel": "phone_call",
  "caller_ref": "c-7f3a",
  "received_at": "2026-10-16T14:02:00Z",
  "text": "My maize leaves have been turning yellow since the heavy rains last week.",
  "problem_type": "crop_health",
  "crop": "maize",
  "symptoms": ["yellow leaves", "wilting"],
  "location": {"lat": -1.2921, "lon": 36.8219, "precision_m": 2000},
  "reported_event_time": "2026-10-09T00:00:00Z",
  "callback_url": "https://phone-service.example.com/hooks/data-core",
  "extra": {"language": "sw", "call_duration_s": 184}
}
```

Only `text` is required. Every other field improves the result, so send what you have.

| Field | Type | Required | Rules / meaning |
|---|---|:-:|---|
| `text` | string | ✅ | 1–10 000 chars. The farmer's problem in their words (transcript or summary), ideally in English |
| `external_id` | string | recommended | ≤ 128 chars. **Your** unique id for this call, e.g. the call id. Used for idempotency (§4) |
| `channel` | string | recommended | ≤ 32 chars. Use `"phone_call"` (or `"telegram"`, `"sms"`, ...). **Never `"demo"`**: that marks the call as test data |
| `caller_ref` | string | recommended | ≤ 128 chars. A **pseudonymous**, stable id per caller (e.g. a hash of the phone number). **Do not send the raw phone number.** Lets the dashboard group repeat callers |
| `received_at` | ISO-8601 datetime | – | When the call happened. UTC with `Z`. Missing → time the request arrives |
| `problem_type` | string | recommended | ≤ 64 chars. Normalised to lowercase snake_case. Not enforced, but please stick to: `crop_health`, `pests`, `weather_damage`, `soil`, `other` (the dashboard groups by it) |
| `crop` | string | recommended | ≤ 64 chars, normalised to lowercase snake_case, e.g. `maize`, `beans`, `potato`, `cassava` |
| `symptoms` | list of strings | – | Short phrases, e.g. `["yellow leaves", "brown spots"]`. A comma-separated string is also accepted |
| `location` | object | **strongly recommended** | See below. Without a location there is no weather, sensor or nearby-reports evidence |
| `reported_event_time` | ISO-8601 datetime | – | When the problem started, if the farmer says so |
| `callback_url` | URL | – | Where `data_core` should POST the result for this call (§5). Overrides the server-wide `PHONE_WEBHOOK_URL` |
| `extra` | object | – | Anything else (language, duration, IVR path, ...). Stored as-is, not interpreted |

**`location`**, give coordinates if you have them, otherwise a place name:

| Field | Type | Meaning |
|---|---|---|
| `lat`, `lon` | number | WGS84 decimal degrees. Send both or neither |
| `name` | string | Village / town / ward, e.g. `"Kiambu"`. Used only when `lat`/`lon` are missing: it is geocoded (restricted to the country configured by `GEOCODING_COUNTRY_CODE`, e.g. Kenya) |
| `precision_m` | number | How accurate the position is in metres (e.g. 5000 for "somewhere in this town") |

`"location": "Kiambu"` (a plain string) is accepted as a place name too.

**Tolerant input:** the final format is not frozen, so some alternative names are accepted and mapped automatically,
e.g. `transcript`/`description`/`message` → `text`, `call_id` → `external_id`, `caller_id` → `caller_ref`,
`latitude`/`longitude`/`village` at the top level → `location`. Unknown fields are kept in `extra`, not rejected.
Please still use the canonical names above.

---

## 3. Response

The response is the full **case**. The fields the phone service needs are marked **bold**.

```json
{
  "id": "3382833cb9a94a059a9efa1a2968dbc2",
  "status": "delivered",
  "attempts": 1,
  "last_error": null,
  "created_at": "2026-10-16T14:02:03Z",
  "updated_at": "2026-10-16T14:02:06Z",
  "request": { "external_id": "call-2026-10-16-0001", "text": "...", "lat": -1.2921, "lon": 36.8219, "...": "..." },
  "recommendation": {
    "disease": "suspected_fungal_disease",
    "confidence": 0.6,
    "risk_level": "medium",
    "explanation": "13 h with humidity >= 90 % in the last 72 h",
    "actions": [
      "Inspect leaves for spots, mould or lesions and remove affected plant parts",
      "Avoid overhead irrigation and improve air flow between plants",
      "Contact the agricultural extension officer for confirmation and treatment advice"
    ],
    "created_at": "2026-10-16T14:02:06Z"
  },
  "deliveries": [{"channel": "phone", "status": "sent", "attempts": 1, "last_error": null, "sent_at": "2026-10-16T14:02:06Z"}]
}
```

| Field | Meaning |
|---|---|
| **`id`** | Case id. Store it to look the case up later (§6) |
| **`status`** | `delivered` / `recommended` = recommendation ready. `received`, `context_built`, `failed_context`, `failed_recommend` = not ready (see 202 below) |
| **`recommendation`** | `null` if not ready |
| **`recommendation.actions`** | List of concrete steps, in order. **This is what to tell the farmer** |
| **`recommendation.risk_level`** | `low` \| `medium` \| `high` \| `unknown`. Use it for urgency ("please act today") |
| `recommendation.disease` | Suspected problem as a snake_case label, or `null`. Machine-readable, convert before reading it out |
| `recommendation.confidence` | 0–1, or `null` |
| `recommendation.explanation` | Short reason, mainly for the dashboard / extension officer |

### Status codes

| Status | When | What to do |
|---|---|---|
| `201 Created` | new call, recommendation ready | read `recommendation` |
| `200 OK` | `external_id` was already sent before. The **existing** case is returned, nothing is created twice | read `recommendation` |
| `202 Accepted` | call stored, but processing failed (e.g. recommender down). `recommendation` is `null`, `last_error` says why | tell the farmer they will be called back. The case is retried automatically (daily job); result comes via webhook (§5) or polling (§6) |
| `401 Unauthorized` | missing/wrong key | fix the key |
| `422 Unprocessable Entity` | invalid body (e.g. empty `text`, `lat` out of range, bad `callback_url`) | fix the payload, don't retry as-is |
| `5xx` / timeout / network error | server problem | retry with the **same** `external_id` (§4) |

---

## 4. Timeouts and retries

- Set the HTTP timeout to **60 s**. The request runs the whole pipeline (geocoding, weather, sensors, recommender)
  before it answers. The first request after a pause can take a few seconds longer (cold start).
- Always send `external_id`. Then a retry after a timeout is safe: if the first attempt got through, the retry
  returns the same case with `200` instead of creating a duplicate.
- Retry on network errors, timeouts and `5xx` with backoff. Don't retry on `4xx`.

---

## 5. Optional: result via webhook (data_core → phone service)

Only needed for **asynchronous** results, i.e. when the first response was `202` and the farmer should be
called back later. For the normal case the synchronous response in §3 is enough.

> **Current state:** webhook delivery is **mocked** on the server (`config.yaml: delivery.mocked: true`). Webhooks
> are only logged, nothing is sent. Tell the data_core team when your endpoint is live, so they switch it on.

When it is on, `data_core` sends this to `callback_url` (per call) or to the server-wide `PHONE_WEBHOOK_URL`:

```
POST <your url>
Content-Type: application/json
X-DataCore-Event: case.recommended
X-DataCore-Delivery: <unique delivery id>
X-DataCore-Signature: sha256=<hex HMAC-SHA256 of the raw body, key = shared WEBHOOK_SECRET>
```

```json
{
  "event": "case.recommended",
  "case_id": "3382833cb9a94a059a9efa1a2968dbc2",
  "request_id": "24337351675144d5b8a7bf6043bc006e",
  "external_id": "call-2026-10-16-0001",
  "channel": "phone_call",
  "caller_ref": "c-7f3a",
  "problem_type": "crop_health",
  "location": {"lat": -1.2921, "lon": 36.8219, "name": null, "precision_m": 2000},
  "recommendation": {
    "disease": "suspected_fungal_disease",
    "confidence": 0.6,
    "risk_level": "medium",
    "explanation": "13 h with humidity >= 90 % in the last 72 h",
    "actions": ["Inspect leaves ...", "Avoid overhead irrigation ...", "Contact the extension officer ..."]
  },
  "evidence_summary": ["Weather (open_meteo), last 72 h: 5.8 mm rain, ..."],
  "gaps": [],
  "warnings": [],
  "created_at": "2026-10-16T14:02:06Z"
}
```

Your endpoint must:
- answer with any **2xx within 5 s** (do the actual callback to the farmer afterwards, asynchronously),
- match the result to the call via `external_id` (your id) or `case_id`,
- tolerate **duplicates**: a webhook can arrive more than once. Ignore a `case_id` you already handled,
- verify `X-DataCore-Signature` if you share a `WEBHOOK_SECRET` with the data_core team:
  `"sha256=" + hex(HMAC_SHA256(secret, raw_request_body)) == header`.

On a non-2xx answer or timeout, delivery is retried with backoff (on the Vercel Hobby plan: once a day), up to 10 times.

---

## 6. Optional: look a case up later (polling)

With the same input key:

- `GET {BASE_URL}/v1/cases/{case_id}` → the case as in §3.
- `GET {BASE_URL}/v1/cases?caller_ref=c-7f3a` → all calls of one caller, newest first
  (`{"total": n, "items": [case, ...]}`).

---

## 7. Test it

```bash
curl -X POST https://datacore-eta.vercel.app/v1/requests \
     -H "Content-Type: application/json" -H "X-API-Key: <input key>" \
     -d '{"external_id":"test-call-001","channel":"phone_call","caller_ref":"c-test","text":"My maize leaves turn yellow since the heavy rains","problem_type":"crop_health","crop":"maize","location":{"name":"Kiambu"}}'
```

Interactive docs with all fields: `{BASE_URL}/docs`. Test calls with `"channel": "demo"` are labelled as demo data
everywhere (use `mocks/seed_demo.py` for bulk test data).
