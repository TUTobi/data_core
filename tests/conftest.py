import pytest
import respx
from fastapi.testclient import TestClient

from data_core.config import Settings
from data_core.main import create_app

KEYS = {"pi": "pi-key", "input": "input-key", "dashboard": "dash-key", "internal": "internal-key"}
DASHBOARD_HOOK = "http://dashboard.test/hooks/case"
PHONE_HOOK = "http://phone.test/hooks/case"
WEBHOOK_SECRET = "s3cret"


def auth(role: str) -> dict[str, str]:
    return {"X-API-Key": KEYS[role]}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        pi_keys=KEYS["pi"],
        input_keys=KEYS["input"],
        dashboard_keys=KEYS["dashboard"],
        internal_keys=KEYS["internal"],
        weather_provider="mock",
        geocoding_enabled=False,
        recommender_mode="mock",
        dashboard_webhook_url=DASHBOARD_HOOK,
        phone_webhook_url=PHONE_HOOK,
        webhook_secret=WEBHOOK_SECRET,
    )


@pytest.fixture
def make_client(settings):
    clients = []

    def _make(**overrides) -> TestClient:
        app = create_app(settings.model_copy(update=overrides))
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def webhooks():
    """Mocks every outgoing HTTP call made by the app (webhooks, recommender)."""
    with respx.mock(assert_all_called=False) as router:
        router.post(DASHBOARD_HOOK, name="dashboard").respond(200)
        router.post(PHONE_HOOK, name="phone").respond(200)
        yield router
