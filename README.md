# data_core
BCG Hackathon for the data core of the product

- [`project_overview.md`](project_overview.md) — overview of the whole hackathon project (all workstreams)
- [`project.md`](project.md) — spec of this subsystem: data ingestion, retrieval, the decision core and delivery
- [`contracts/`](contracts) — JSON schemas + real example payloads for the other teams
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
curl -X POST localhost:8000/v1/requests -H "X-API-Key: dev-input-key" -H "Content-Type: application/json" \
     -d '{"text":"My crops are dying since the heavy rains","problem_type":"crop_health","lat":-1.2921,"lon":36.8219}'
```

The response contains the case, including the recommendation. Use `GET /v1/cases/{id}/context` to see all the evidence behind it.

To also use the mock recommender and see the webhooks:

```bash
uvicorn mocks.mock_recommender:app --port 8001
WEBHOOK_SECRET=dev-webhook-secret uvicorn mocks.mock_webhook_sink:app --port 8002
# in .env: RECOMMENDER_MODE=http, RECOMMENDER_URL=http://localhost:8001/predict,
#          DASHBOARD_WEBHOOK_URL=http://localhost:8002/hooks/dashboard, PHONE_WEBHOOK_URL=http://localhost:8002/hooks/phone
curl localhost:8002/received
```

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
