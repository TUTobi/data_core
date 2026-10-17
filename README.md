# data_core
BCG Hackathon for the data core of the product

- [`project_overview.md`](project_overview.md) — overview of the whole hackathon project (all workstreams)
- [`project.md`](project.md) — spec of this subsystem: data ingestion, retrieval, the decision core and delivery
- [`contracts/`](contracts) — JSON schemas + real example payloads for the other teams
  - [`sensor_service_api.md`](contracts/sensor_service_api.md) — how field devices push sensor readings
  - [`phone_service_api.md`](contracts/phone_service_api.md) — how the phone system submits calls and gets recommendations back
  - [`frontend_api.md`](contracts/frontend_api.md) — what the dashboard can read
- [`deploy/azure.md`](deploy/azure.md), [`deploy/vercel.md`](deploy/vercel.md) — deployment guides

## Quickstart (local, no Docker)

```bash
python -m venv .venv && .venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn data_core.asgi:app --reload                   # http://localhost:8000/docs
```

Feed it some data:

```bash
python mocks/pi_simulator.py --backfill-hours 24 --count 3          # Raspberry Pi stand-in
python mocks/seed_demo.py --count 30                                 # 30 DEMO caller requests (channel="demo")
curl -X POST localhost:8000/v1/requests -H "X-API-Key: dev-input-key" -H "Content-Type: application/json" \
     -d '{"text":"My crops are dying since the heavy rains","problem_type":"crop_health","lat":-1.2921,"lon":36.8219}'
```

The response contains the case, including the recommendation. Use `GET /v1/cases/{id}/context` to see all the evidence behind it.

To also use the mock recommender and see the webhooks:

```bash
uvicorn mocks.mock_recommender:app --port 8001
WEBHOOK_SECRET=dev-webhook-secret uvicorn mocks.mock_webhook_sink:app --port 8002
# in config.yaml: recommender.mocked: false, delivery.mocked: false
# in .env: RECOMMENDER_URL=http://localhost:8001/predict,
#          DASHBOARD_WEBHOOK_URL=http://localhost:8002/hooks/dashboard, PHONE_WEBHOOK_URL=http://localhost:8002/hooks/phone
curl localhost:8002/received
```

## What is mocked? (`config.yaml`)

[`config.yaml`](config.yaml) is the **single switchboard** for mock vs. real. Env vars keep only secrets, URLs and keys.
The active flags are reported by `GET /health` → `"mocks"`. Changing a flag means editing the file and redeploying.

| Component | Current | `mocked: true` | `mocked: false` (strictly real) |
|---|---|---|---|
| `weather` | real | synthetic humid weather | Open-Meteo; an outage becomes a *gap* in the context |
| `geocoding` | real | small built-in demo gazetteer | Open-Meteo place search |
| `sensors` | **mocked** | readings with `quality: "mocked"` (Pi simulator) accepted + used | mock readings → **422**; existing ones ignored everywhere |
| `caller_requests` | **mocked** | demo calls (`channel: "demo"` / `extra.demo`) accepted + used | demo calls → **422**; hidden from evidence, `/v1/cases`, stats |
| `recommender` | real | built-in heuristic (not a disease model) | `RECOMMENDER_URL`; **startup fails** if unset. A URL ending in `/analyze` = the potato engine (`recommender/potato_engine.py` adapts the format) |
| `delivery` | **mocked** | webhooks only logged, marked `sent` (`mock://…`) | signed POSTs to `DASHBOARD_/PHONE_WEBHOOK_URL`; unset URL = channel off |
| `planner.strategy` | `fetch_all` | – (not a mock: placeholder until the data-selection logic is defined) | |

Every mock that ends up in a result is labelled: context `warnings` ("Recommendation is mocked …", "Weather data is mocked",
"Some sensor data is mocked", …) and `is_mock` on demo calls. A typo or missing component in `config.yaml` stops the app at
startup. `docker compose` uses [`config.docker.yaml`](config.docker.yaml) (real HTTP paths against the mock services).

## Dashboard integration

The dashboard (`hackathon-dashboard`, React SPA) talks to this API directly from the browser.
Full field-level reference for the frontend: [`contracts/frontend_api.md`](contracts/frontend_api.md).

- **CORS:** add the dashboard's origin to `CORS_ORIGINS` (comma-separated; default `http://localhost:5173` for `vite dev`). `CORS_ORIGIN_REGEX` additionally allows every matching origin (e.g. all Vercel preview URLs of the dashboard).
- **Auth:** send a `DASHBOARD_KEYS` value as the `X-API-Key` header. It ships in the JS bundle, so treat it as a demo key, not a secret.
- **Updates:** poll `GET /v1/cases`. The `DASHBOARD_WEBHOOK_URL` push doesn't apply to a browser app (it can't receive POSTs).

| Dashboard block | Endpoint |
|---|---|
| Call stats + problem summary (last N days) | `GET /v1/stats/summary?days=30` |
| Call history, map pins | `GET /v1/cases?since=&problem_type=&min_lat=…` |
| Earlier calls from the same caller | `GET /v1/cases?caller_ref=…` |
| Call detail / provided solution | `GET /v1/cases/{id}` |
| Weather at call time, sensors considered, nearby reports, gaps/warnings | `GET /v1/cases/{id}/context` |
| Sensor coverage | `GET /v1/sensors` (`last_seen_at` → working or not) |
| Weather / readings around a point | `GET /v1/observations?lat=&lon=&include_weather=true` |

Optional fields the phone system can send in `extra` (kept as-is, no schema change): `duration_s` (call duration in
seconds), `reported_weather` (weather the farmer described). Demo records have `channel="demo"` and `extra.demo=true`.

## Full stack with Docker

```bash
docker compose up --build      # API + Postgres + mock recommender + webhook sink + tick cron
```

## Deployment

| Option | When | Guide |
|---|---|---|
| **Vercel** (Hobby) + Neon Postgres | Hosted demo; `npx vercel deploy --prod` | [`deploy/vercel.md`](deploy/vercel.md) |
| Azure Container Apps + PostgreSQL | Docker-based hosting | [`deploy/azure.md`](deploy/azure.md) |
| Docker / local | Development, full stack with mocks | above |

## Tests

```bash
pytest
```

## Schema changes

```bash
alembic revision --autogenerate -m "describe change"   # uses DATABASE_URL
alembic upgrade head
python scripts/export_schemas.py                         # refresh contracts/schemas
```
