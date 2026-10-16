# Deploying to Vercel (Hobby plan + Neon Postgres)

The whole FastAPI app runs as **one Python serverless function** (`api/index.py`). `vercel.json` routes every path to it, sets `maxDuration: 60`, keeps tests/mocks/docs out of the bundle, and schedules a **daily** cron for `/internal/tick`.

## What runs where

| Piece | On Vercel |
|---|---|
| API (`/v1/...`, `/docs`) | Serverless function `api/index.py` |
| Database | **Neon** Postgres (Vercel Marketplace). SQLite is refused on Vercel with a clear error |
| Recommender | `RECOMMENDER_MODE=mock` (in-process) until the real service exists. Then `RECOMMENDER_MODE=http` + `RECOMMENDER_URL` |
| Retry job | Vercel Cron, daily at 06:00 UTC → `/internal/tick` |
| Local dev / full stack with mocks | unchanged: `uvicorn` or `docker compose` |

### What the daily cron does (and doesn't do)
`/internal/tick` pulls **no data**. Sensor data is pushed by the Pi, and weather is fetched per caller request. The tick only:
1. re-sends webhooks that previously failed,
2. resumes cases whose context or recommendation step failed,
3. deletes weather-cache entries older than 7 days.

Normal requests never wait for it. On Hobby, a failed delivery is therefore retried once a day. To retry sooner, call `POST /v1/cases/{id}/retry` or `GET /internal/tick` (with an internal key) by hand.

## Steps

1. **Log in and link the project** (from the repo root):
   ```bash
   npx vercel login
   npx vercel link          # create/link project "data-core"
   ```
2. **Add Neon:** Vercel dashboard → project → *Storage* → *Create Database* → **Neon** → connect it to the project.
   This injects `DATABASE_URL` (pooled), `DATABASE_URL_UNPOOLED` (direct) and a few `PG*` variables.
3. **Create the schema** once from your laptop, using the *unpooled* URL:
   ```bash
   npx vercel env pull .env.vercel                        # downloads the env vars locally
   # copy DATABASE_URL_UNPOOLED from .env.vercel, then:
   DATABASE_URL='<DATABASE_URL_UNPOOLED>' alembic upgrade head
   ```
   Rerun this after every schema change (`alembic revision --autogenerate ...`).
4. **Set the environment variables** (dashboard → *Settings → Environment Variables*, or `npx vercel env add NAME production`):

   | Variable | Value |
   |---|---|
   | `CREATE_TABLES_ON_STARTUP` | `false` (schema comes from Alembic) |
   | `PI_KEYS`, `INPUT_KEYS`, `DASHBOARD_KEYS`, `INTERNAL_KEYS` | long random strings (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) |
   | `CRON_SECRET` | **the same value as one of the `INTERNAL_KEYS`**. Vercel Cron sends it as `Authorization: Bearer …` |
   | `WEBHOOK_SECRET` | random string; share it with the dashboard and phone teams |
   | `RECOMMENDER_MODE` | `mock` for now |
   | `GEOCODING_COUNTRY_CODE` | e.g. `KE` |
   | `DASHBOARD_WEBHOOK_URL`, `PHONE_WEBHOOK_URL` | leave empty until those systems exist (delivery is then skipped) |

   `DATABASE_URL` comes from the Neon integration. Connection pooling is switched off in the app automatically on Vercel (`VERCEL=1`), because Neon's pooler does it.
5. **Deploy:**
   ```bash
   npx vercel deploy --prod
   ```
   Dependencies are installed from `requirements.txt` (runtime-only list). Check the build log once to see which file Vercel used.
6. **Smoke test** (replace the URL and keys):
   ```bash
   URL=https://data-core-xxxx.vercel.app
   curl $URL/health
   curl -X POST $URL/v1/sensor-readings -H "X-API-Key: $PI_KEY" -H "Content-Type: application/json" \
        -d '{"sensor_id":"pi-field-01","lat":-1.2921,"lon":36.8219,"metrics":{"humidity_pct":88}}'
   curl -X POST $URL/v1/requests -H "X-API-Key: $INPUT_KEY" -H "Content-Type: application/json" \
        -d '{"text":"My crops are dying since the heavy rains","problem_type":"crop_health","lat":-1.2921,"lon":36.8219}'
   curl $URL/internal/tick -H "Authorization: Bearer $CRON_SECRET"
   ```
   Then point the Raspberry Pi at `$URL/v1/sensor-readings`:
   `python mocks/pi_simulator.py --url $URL --key $PI_KEY`.

## Limits to keep in mind
- **Function duration** is capped at 60 s via `vercel.json`, which covers weather + recommender calls. Increase it if the real recommender is slow.
- **Cold starts:** the first request after idle takes ~1–2 s longer.
- **Cron:** Hobby allows only daily schedules. A more frequent schedule needs Pro (edit `crons` in `vercel.json`) or an external scheduler calling `/internal/tick`.
