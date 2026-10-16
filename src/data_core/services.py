"""Wires the pluggable components (planner, weather, recommender, geocoder) from settings."""

import ssl
from dataclasses import dataclass

import httpx
import truststore

from data_core.config import Settings
from data_core.core.planner import DataNeedsPlanner, build_planner
from data_core.providers.geocoding import Geocoder, OpenMeteoGeocoder
from data_core.providers.weather.base import WeatherProvider
from data_core.providers.weather.mock import MockWeatherProvider
from data_core.providers.weather.open_meteo import OpenMeteoProvider
from data_core.recommender.base import RecommenderClient
from data_core.recommender.http_client import HttpRecommender
from data_core.recommender.mock import MockRecommender


@dataclass
class Services:
    http: httpx.Client
    planner: DataNeedsPlanner
    weather: WeatherProvider
    recommender: RecommenderClient
    geocoder: Geocoder | None

    def close(self) -> None:
        self.http.close()


def build_services(settings: Settings) -> Services:
    # Verify TLS against the OS trust store (not only certifi), so corporate/AV TLS proxies work.
    http = httpx.Client(
        headers={"User-Agent": "data-core/0.1"},
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
    )

    if settings.weather_provider == "open_meteo":
        weather: WeatherProvider = OpenMeteoProvider(http, settings.weather_timeout_s)
    else:
        weather = MockWeatherProvider()

    if settings.recommender_mode == "http":
        recommender: RecommenderClient = HttpRecommender(
            http, settings.recommender_url, settings.recommender_timeout_s, settings.recommender_api_key
        )
    else:
        recommender = MockRecommender()

    geocoder = (
        OpenMeteoGeocoder(http, settings.weather_timeout_s, settings.geocoding_country_code)
        if settings.geocoding_enabled
        else None
    )

    return Services(
        http=http,
        planner=build_planner(settings),
        weather=weather,
        recommender=recommender,
        geocoder=geocoder,
    )
