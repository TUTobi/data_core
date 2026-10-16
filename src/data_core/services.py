"""Wires the pluggable components: mock or real is decided by config.yaml (RuntimeConfig),
URLs / secrets / tuning come from Settings (env vars)."""

import ssl
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import truststore

from data_core.config import Settings
from data_core.core.planner import DataNeedsPlanner, build_planner
from data_core.providers.geocoding import Geocoder, MockGeocoder, OpenMeteoGeocoder
from data_core.providers.weather.base import WeatherProvider
from data_core.providers.weather.mock import MockWeatherProvider
from data_core.providers.weather.open_meteo import OpenMeteoProvider
from data_core.recommender.base import RecommenderClient
from data_core.recommender.http_client import HttpRecommender
from data_core.recommender.mock import MockRecommender
from data_core.recommender.potato_engine import PotatoEngineRecommender
from data_core.runtime_config import RuntimeConfig, RuntimeConfigError, load_runtime_config


@dataclass
class Services:
    http: httpx.Client
    runtime: RuntimeConfig
    planner: DataNeedsPlanner
    weather: WeatherProvider
    recommender: RecommenderClient
    geocoder: Geocoder

    def close(self) -> None:
        self.http.close()


def build_services(settings: Settings, runtime: RuntimeConfig | None = None) -> Services:
    runtime = runtime or load_runtime_config(settings.config_file)

    if not runtime.recommender.mocked and not settings.recommender_url:
        raise RuntimeConfigError("config.yaml sets recommender.mocked=false, but RECOMMENDER_URL is not set")

    # Verify TLS against the OS trust store (not only certifi), so corporate/AV TLS proxies work.
    http = httpx.Client(
        headers={"User-Agent": "data-core/0.1"},
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
    )

    weather: WeatherProvider = (
        MockWeatherProvider() if runtime.weather.mocked else OpenMeteoProvider(http, settings.weather_timeout_s)
    )
    geocoder: Geocoder = (
        MockGeocoder()
        if runtime.geocoding.mocked
        else OpenMeteoGeocoder(http, settings.weather_timeout_s, settings.geocoding_country_code)
    )
    recommender: RecommenderClient
    if runtime.recommender.mocked:
        recommender = MockRecommender()
    elif urlparse(settings.recommender_url).path.rstrip("/").endswith("/analyze"):
        # The potato engine (recommendation-engine-2) has its own contract; everything else gets the DecisionContext.
        recommender = PotatoEngineRecommender(
            http, settings.recommender_url, settings.recommender_timeout_s, settings.weather_timeout_s
        )
    else:
        recommender = HttpRecommender(
            http, settings.recommender_url, settings.recommender_timeout_s, settings.recommender_api_key
        )

    return Services(
        http=http,
        runtime=runtime,
        planner=build_planner(runtime.planner.strategy, settings),
        weather=weather,
        recommender=recommender,
        geocoder=geocoder,
    )
