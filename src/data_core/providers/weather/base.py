from statistics import fmean
from typing import Any, Protocol

from data_core.schemas.context import WeatherEvidence, WeatherWindow


class WeatherProvider(Protocol):
    """A weather source. Add new APIs by implementing this and registering it in services.py."""

    name: str

    def get(self, lat: float, lon: float, past_h: int, forecast_h: int) -> WeatherEvidence: ...


def _mean(values: list[float]) -> float | None:
    return round(fmean(values), 2) if values else None


def summarize_window(rows: list[dict[str, Any]], hours: int) -> WeatherWindow:
    """Aggregate hourly rows (keys: temperature_2m, relative_humidity_2m, precipitation,
    soil_moisture_0_to_1cm) into the summary the recommender consumes."""

    def values(key: str) -> list[float]:
        return [r[key] for r in rows if r.get(key) is not None]

    temps = values("temperature_2m")
    rh = values("relative_humidity_2m")
    precip = values("precipitation")
    soil = values("soil_moisture_0_to_1cm")
    return WeatherWindow(
        hours=hours,
        n_points=len(rows),
        precipitation_mm=round(sum(precip), 2) if precip else None,
        mean_temp_c=_mean(temps),
        min_temp_c=min(temps) if temps else None,
        max_temp_c=max(temps) if temps else None,
        mean_rh_pct=_mean(rh),
        hours_rh_ge_90=sum(1 for v in rh if v >= 90) if rh else None,
        mean_soil_moisture=_mean(soil),
    )
