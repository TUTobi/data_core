"""config.yaml: the single switchboard for what is mocked and what is real.

Only behaviour switches live here. Secrets, URLs and API keys stay in env vars (see config.py).
Every component must be listed explicitly; unknown keys are an error, so a typo can't silently
fall back to a default.

`mocked: false` means strictly real:
- the real implementation is used; if it isn't configured, startup fails (recommender) or the channel stays
  off (delivery without a URL),
- incoming mock data is rejected (422) and mock records already in the DB are ignored (sensors, caller_requests).
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

PACKAGE_ROOT = Path(__file__).resolve().parents[2]  # repo root when running from source (src/ layout)


class RuntimeConfigError(RuntimeError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MockFlag(_Strict):
    mocked: bool


class PlannerConfig(_Strict):
    strategy: str = "fetch_all"


class RuntimeConfig(_Strict):
    weather: MockFlag
    geocoding: MockFlag
    sensors: MockFlag
    caller_requests: MockFlag
    recommender: MockFlag
    delivery: MockFlag
    planner: PlannerConfig = PlannerConfig()

    def summary(self) -> dict[str, bool | str]:
        """Flat view for /health and the dashboard: component -> mocked?"""
        flags: dict[str, bool | str] = {
            name: getattr(self, name).mocked
            for name in ("weather", "geocoding", "sensors", "caller_requests", "recommender", "delivery")
        }
        flags["planner"] = self.planner.strategy
        return flags


def resolve_config_path(configured: str) -> Path:
    """Absolute path as given; a relative one is looked up in the working directory, then the repo root."""
    path = Path(configured)
    if path.is_absolute() or path.exists():
        return path
    return PACKAGE_ROOT / path


def load_runtime_config(configured: str) -> RuntimeConfig:
    path = resolve_config_path(configured)
    if not path.is_file():
        raise RuntimeConfigError(f"Mock configuration not found: {path} (set DATA_CORE_CONFIG or add config.yaml)")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return RuntimeConfig.model_validate(data)
    except (yaml.YAMLError, ValidationError) as exc:
        raise RuntimeConfigError(f"Invalid mock configuration in {path}:\n{exc}") from exc
