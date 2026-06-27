import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app import config
from app.database import init_db
from app.main import app


@pytest.fixture
async def db_path(tmp_path):
    """Patch settings to use a fresh temp DB for each test."""
    path = str(tmp_path / "test.db")
    original = config.settings.DB_PATH
    config.settings.DB_PATH = path
    await init_db(path)
    yield path
    config.settings.DB_PATH = original


@pytest.fixture
async def client(db_path):
    """AsyncClient wired to the FastAPI app with a real httpx client on app.state."""
    app.state.http_client = httpx.AsyncClient()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await app.state.http_client.aclose()


@pytest.fixture
def fast_backoff(monkeypatch):
    """Set BASE_BACKOFF to near-zero so retry tests don't actually sleep."""
    monkeypatch.setattr(config.settings, "BASE_BACKOFF", 0.001)
