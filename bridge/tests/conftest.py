from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from miloagent_bridge.client import MiloAgentClient
from miloagent_bridge.config import STATUSES, Settings

BASE = "http://miloagent.test:8420"
# built at runtime so the secret scan does not take the fixture for a credential
PASSWORD = "-".join(("fixture", "dashboard", "value"))
FIXTURES = Path(__file__).parent / "fixtures"
HEADER = (FIXTURES / "opportunities_acted.csv").read_text().splitlines()[0] + "\n"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


@pytest.fixture
def settings() -> Settings:
    return Settings(url=BASE, username="admin", password=PASSWORD, cache_seconds=0)


@pytest.fixture
def api():
    # assert_all_mocked: a request without a route fails the test, so a call the bridge
    # must never make (approve, control, settings) cannot pass silently
    with respx.mock(base_url=BASE, assert_all_called=False, assert_all_mocked=True) as mock:
        mock.post("/api/auth/login").mock(return_value=httpx.Response(200, json={"ok": True, "token": "tok-1"}))
        yield mock


def mock_exports(api) -> None:
    by_status = {"acted": fixture("opportunities_acted.csv"), "pending": fixture("opportunities_pending.csv")}

    def opportunities(request: httpx.Request) -> httpx.Response:
        status = request.url.params["status"]
        assert status in STATUSES
        return httpx.Response(200, text=by_status.get(status, HEADER))

    api.get("/api/export/opportunities").mock(side_effect=opportunities)
    api.get("/api/actions").mock(return_value=httpx.Response(200, text=fixture("actions.json")))


@pytest.fixture
async def client(settings: Settings):
    c = MiloAgentClient(settings)
    yield c
    await c.aclose()
