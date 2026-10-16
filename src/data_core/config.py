"""Runtime configuration (12-factor: everything comes from env vars / .env)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- persistence -------------------------------------------------------
    database_url: str = "sqlite:///./data_core.db"
    # Convenient for local dev / demo; use `alembic upgrade head` in deployments.
    create_tables_on_startup: bool = True

    # --- auth (comma-separated API keys per client role) ---------------------
    auth_disabled: bool = False
    pi_keys: str = ""
    input_keys: str = ""
    dashboard_keys: str = ""
    internal_keys: str = ""

    # --- weather -------------------------------------------------------------
    weather_provider: Literal["open_meteo", "mock"] = "open_meteo"
    weather_cache_ttl_s: int = 900
    weather_timeout_s: float = 8.0
    geocoding_enabled: bool = True
    geocoding_country_code: str = ""  # ISO-3166 alpha-2, narrows place-name lookups (e.g. "KE")

    # --- core / planner ------------------------------------------------------
    planner_strategy: str = "fetch_all"
    default_radius_km: float = 10.0
    default_lookback_h: int = 72
    default_forecast_h: int = 48
    max_case_attempts: int = 5

    # --- recommender (external system) --------------------------------------
    recommender_mode: Literal["mock", "http"] = "mock"
    recommender_url: str = ""  # full endpoint, e.g. http://recommender:8001/predict
    recommender_api_key: str = ""
    recommender_timeout_s: float = 20.0

    # --- delivery (webhooks to dashboard / phone system) ---------------------
    dashboard_webhook_url: str = ""
    phone_webhook_url: str = ""  # fallback when a request has no callback_url
    webhook_secret: str = ""  # HMAC-SHA256 signing secret for outgoing webhooks
    webhook_timeout_s: float = 5.0
    webhook_max_attempts: int = 10

    def keys_for(self, role: str) -> set[str]:
        raw = getattr(self, f"{role}_keys", "")
        return {k.strip() for k in raw.split(",") if k.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
