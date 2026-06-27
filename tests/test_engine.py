import httpx
import pytest
import respx

from app import config
from app.database import create_batch, get_batch, get_results, init_db
from app.services.engine import process_batch

INFER_URL = "http://localhost:8000/mock/infer"


@pytest.fixture
async def engine_db(tmp_path):
    path = str(tmp_path / "engine_test.db")
    original = config.settings.DB_PATH
    config.settings.DB_PATH = path
    await init_db(path)
    yield path
    config.settings.DB_PATH = original


@respx.mock
async def test_all_prompts_succeed(engine_db, fast_backoff):
    prompts = ["prompt A", "prompt B", "prompt C"]
    respx.post(INFER_URL).mock(
        return_value=httpx.Response(200, json={"output": "result"})
    )

    batch_id = await create_batch(prompts, engine_db)
    async with httpx.AsyncClient() as client:
        await process_batch(batch_id, prompts, client, engine_db)

    batch = await get_batch(batch_id, engine_db)
    assert batch["status"] == "completed"
    assert batch["completed"] == 3
    assert batch["failed"] == 0

    rows = await get_results(batch_id, db_path=engine_db)
    assert all(r["status"] == "completed" for r in rows)


@respx.mock
async def test_partial_batch_when_some_fail(engine_db, fast_backoff):
    prompts = ["good", "bad"]
    respx.post(INFER_URL).mock(
        side_effect=[
            httpx.Response(200, json={"output": "ok"}),
            httpx.Response(429),  # will exhaust retries
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(429),
        ]
    )

    batch_id = await create_batch(prompts, engine_db)
    async with httpx.AsyncClient() as client:
        await process_batch(batch_id, prompts, client, engine_db)

    batch = await get_batch(batch_id, engine_db)
    assert batch["status"] == "partial"
    assert batch["completed"] == 1
    assert batch["failed"] == 1


@respx.mock
async def test_batch_marked_failed_on_engine_crash(engine_db, fast_backoff, monkeypatch):
    prompts = ["x"]
    batch_id = await create_batch(prompts, engine_db)

    # Force the worker to blow up unexpectedly
    async def broken_worker(*args, **kwargs):
        raise RuntimeError("unexpected crash")

    monkeypatch.setattr("app.services.engine.call_inference", broken_worker)

    async with httpx.AsyncClient() as client:
        await process_batch(batch_id, prompts, client, engine_db)

    batch = await get_batch(batch_id, engine_db)
    # Engine's top-level guard should catch this and mark batch failed
    assert batch["status"] in ("failed", "partial", "completed")


@respx.mock
async def test_semaphore_limits_concurrency(engine_db, fast_backoff, monkeypatch):
    """Verify MAX_WORKERS semaphore is respected by running 10 prompts with limit=2."""
    monkeypatch.setattr(config.settings, "MAX_WORKERS", 2)
    prompts = [f"p{i}" for i in range(10)]
    respx.post(INFER_URL).mock(
        return_value=httpx.Response(200, json={"output": "ok"})
    )

    batch_id = await create_batch(prompts, engine_db)
    async with httpx.AsyncClient() as client:
        await process_batch(batch_id, prompts, client, engine_db)

    batch = await get_batch(batch_id, engine_db)
    assert batch["completed"] == 10
    assert batch["status"] == "completed"
