# Deploying to Vercel

The whole FastAPI app runs as **one Python serverless function** (`api/index.py`). `vercel.json` routes every path to it and schedules the `/internal/tick` cron.

> This is a sketch for later. It has not been deployed yet.

## Constraints to know
- **No local disk:** SQLite cannot be used. Use hosted Postgres such as **Neon** (Vercel Marketplace) or Supabase, and prefer the *pooled* connection string. `postgres://` URLs are converted to the psycopg driver automatically.
- **No background processes:** this is why the pipeline runs inside the request and retries go through the cron → `/internal/tick`.
- **Function duration:** a request runs the full pipeline (weather API + recommender). Check your plan's max duration and raise `maxDuration` if the recommender is slow.
- **Cron frequency:** depends on the plan. Hobby allows only daily crons, so for frequent webhook retries use Pro or an external scheduler (e.g. GitHub Actions) that calls `/internal/tick`.

## Steps
1. Create a Postgres database (Neon) and copy its connection string.
2. Create the schema once from your machine:
   ```bash
   DATABASE_URL='postgres://...' alembic upgrade head
   ```
   (or set `CREATE_TABLES_ON_STARTUP=true` for a quick demo).
3. `vercel link`, then set the environment variables (Project → Settings → Environment Variables):
   `DATABASE_URL`, `PI_KEYS`, `INPUT_KEYS`, `DASHBOARD_KEYS`, `INTERNAL_KEYS`, `WEBHOOK_SECRET`,
   `RECOMMENDER_MODE`/`RECOMMENDER_URL`, `DASHBOARD_WEBHOOK_URL`, `PHONE_WEBHOOK_URL`, `GEOCODING_COUNTRY_CODE`.
4. Set **`CRON_SECRET`** to the same value as one of the `INTERNAL_KEYS`. Vercel Cron sends it as
   `Authorization: Bearer <CRON_SECRET>`, which the API accepts.
5. `vercel deploy --prod`. Dependencies are installed from `requirements.txt`.
