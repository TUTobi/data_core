"""Runtime configuration from env vars / .env: secrets, URLs, keys and tuning.

What is mocked vs. real is NOT configured here but in config.yaml (see runtime_config.py).
"""

import os
from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Former mock switches, now in config.yaml. Still set somewhere (e.g. on Vercel) -> startup warning.
LEGACY_MOCK_ENV_VARS = ("WEATHER_PROVIDER", "RECOMMENDER_MODE", "GEOCODING_ENABLED", "PLANNER_STRATEGY")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- mock switchboard ----------------------------------------------------
    config_file: str = Field("config.yaml", validation_alias=AliasChoices("DATA_CORE_CONFIG", "config_file"))

    # --- persistence -------------------------------------------------------
    database_url: str = "sqlite:///./data_core.db"
    # Convenient for local dev / demo; use `alembic upgrade head` in deployments.
    create_tables_on_startup: bool = True
    # Disable SQLAlchemy connection pooling (automatically on when running on Vercel).
    db_null_pool: bool = False

    # --- auth (comma-separated API keys per client role) ---------------------
    auth_disabled: bool = False
    pi_keys: str = ""
    input_keys: str = ""
    dashboard_keys: str = ""
    internal_keys: str = ""

    # --- CORS (comma-separated browser origins allowed to call the API, e.g. the dashboard) ---
    cors_origins: str = "http://localhost:5173"
    # Optional full-match regex for extra origins, e.g. every Vercel preview URL of the dashboard
    cors_origin_regex: str = ""

    # --- weather / geocoding (mock or real: config.yaml) ------------------------
    weather_cache_ttl_s: int = 900
    weather_timeout_s: float = 8.0
    geocoding_country_code: str = ""  # ISO-3166 alpha-2, narrows place-name lookups (e.g. "KE")

    # --- core / planner (strategy: config.yaml) ------------------------------
    default_radius_km: float = 50.0
    default_lookback_h: int = 336  # 14 days
    default_forecast_h: int = 48
    max_case_attempts: int = 5
    # Caps that keep the DecisionContext (and so the recommender's LLM prompt) bounded
    max_similar_reports: int = 300
    similar_report_text_chars: int = 1000
    max_sensor_points: int = 500  # raw readings per sensor/metric, most recent kept

    # --- recommender (external system; mock or real: config.yaml) -----------
    recommender_url: str = ""  # full endpoint, e.g. http://recommender:8001/predict
    recommender_api_key: str = ""
    recommender_timeout_s: float = 20.0

    # --- delivery (webhooks to dashboard / phone system; mock or real: config.yaml) ---
    dashboard_webhook_url: str = ""
    phone_webhook_url: str = ""  # fallback when a request has no callback_url
    webhook_secret: str = ""  # HMAC-SHA256 signing secret for outgoing webhooks
    webhook_timeout_s: float = 5.0
    webhook_max_attempts: int = 10

    def keys_for(self, role: str) -> set[str]:
        raw = getattr(self, f"{role}_keys", "")
        return {k.strip() for k in raw.split(",") if k.strip()}

    def cors_origin_list(self) -> list[str]:
        # Browsers send origins without a trailing slash; tolerate one pasted from the address bar.
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]


def running_on_vercel() -> bool:
    # Vercel sets VERCEL=1 in every build and function environment.
    return bool(os.environ.get("VERCEL"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
