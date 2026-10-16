# Deploying to Azure

Recommended setup: **Azure Container Apps** (runs the Docker image) + **Azure Database for PostgreSQL – Flexible Server**.
The app is stateless, so it can scale out; all state lives in Postgres.

> These commands are a sketch for later. They have not been run against a real subscription yet.

## 1. Resources

```bash
RG=datacore-rg; LOC=westeurope; PG=datacore-pg-$RANDOM
az group create -n $RG -l $LOC

# Postgres (smallest burstable tier is enough for the hackathon)
az postgres flexible-server create -g $RG -n $PG -l $LOC \
  --tier Burstable --sku-name Standard_B1ms --version 16 \
  --admin-user datacore --admin-password '<strong-password>' \
  --public-access 0.0.0.0          # allows Azure services; tighten for production
az postgres flexible-server db create -g $RG -s $PG -d datacore
```

## 2. App (built from this repo's Dockerfile)

```bash
az containerapp up -g $RG -n data-core --location $LOC \
  --source . --ingress external --target-port 8000

az containerapp secret set -g $RG -n data-core --secrets \
  db-url='postgresql+psycopg://datacore:<strong-password>@'$PG'.postgres.database.azure.com:5432/datacore?sslmode=require' \
  pi-keys='<random>' input-keys='<random>' dashboard-keys='<random>' internal-keys='<random>' \
  webhook-secret='<random>'

az containerapp update -g $RG -n data-core --set-env-vars \
  DATABASE_URL=secretref:db-url CREATE_TABLES_ON_STARTUP=false \
  PI_KEYS=secretref:pi-keys INPUT_KEYS=secretref:input-keys \
  DASHBOARD_KEYS=secretref:dashboard-keys INTERNAL_KEYS=secretref:internal-keys \
  WEBHOOK_SECRET=secretref:webhook-secret \
  GEOCODING_COUNTRY_CODE=KE \
  RECOMMENDER_URL=https://<recommender-host>/predict \
  DASHBOARD_WEBHOOK_URL=https://<dashboard-host>/hooks/case \
  PHONE_WEBHOOK_URL=https://<phone-host>/hooks/case
```

On startup the container runs `alembic upgrade head`, then `uvicorn` (see `Dockerfile`).

## 3. Periodic tick (webhook retries, resuming failed cases)

Use a scheduled Container Apps Job that calls the internal endpoint:

```bash
APP_URL=https://$(az containerapp show -g $RG -n data-core --query properties.configuration.ingress.fqdn -o tsv)
az containerapp job create -g $RG -n data-core-tick --environment <containerapps-env-name> \
  --trigger-type Schedule --cron-expression "*/5 * * * *" --replica-timeout 60 \
  --image curlimages/curl:8.10.1 --cpu 0.25 --memory 0.5Gi \
  --secrets internal-key='<one of INTERNAL_KEYS>' \
  --env-vars INTERNAL_KEY=secretref:internal-key \
  --command "sh" --args "-c" "curl -fsS -X POST -H \"X-API-Key: \$INTERNAL_KEY\" $APP_URL/internal/tick"
```

## Alternatives
- **Azure App Service (Linux, container):** works the same way. Set `PORT`/`WEBSITES_PORT=8000` and use a Logic App or GitHub Action for the tick.
- **Azure SQL** (as suggested in `project_overview.md`) would need the `mssql+pyodbc` driver plus an ODBC driver in the image. This is untested; Postgres is the supported target.
