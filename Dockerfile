FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install .

COPY alembic.ini config.yaml config.docker.yaml ./
COPY alembic ./alembic
COPY mocks ./mocks

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
# Migrate, then serve. PORT is set by most PaaS (Azure App Service / Container Apps, Render, ...).
CMD ["sh", "-c", "alembic upgrade head && uvicorn data_core.asgi:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
