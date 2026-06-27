import pytest

from app.database import (
    create_batch,
    get_batch,
    get_results,
    mark_batch_done,
    mark_batch_failed,
    mark_batch_processing,
    save_error,
    save_result,
)


async def test_create_and_get_batch(db_path):
    batch_id = await create_batch(["a", "b", "c"], db_path)
    batch = await get_batch(batch_id, db_path)

    assert batch is not None
    assert batch["id"] == batch_id
    assert batch["status"] == "accepted"
    assert batch["total"] == 3
    assert batch["completed"] == 0
    assert batch["failed"] == 0


async def test_get_batch_not_found(db_path):
    result = await get_batch("nonexistent-id", db_path)
    assert result is None


async def test_batch_status_transitions(db_path):
    batch_id = await create_batch(["x"], db_path)

    await mark_batch_processing(batch_id, db_path)
    batch = await get_batch(batch_id, db_path)
    assert batch["status"] == "processing"

    await mark_batch_done(batch_id, db_path)
    batch = await get_batch(batch_id, db_path)
    assert batch["status"] == "completed"
    assert batch["finished_at"] is not None


async def test_batch_partial_when_failures(db_path):
    batch_id = await create_batch(["a", "b"], db_path)
    await mark_batch_processing(batch_id, db_path)

    await save_result(batch_id, 0, {"output": "ok"}, retries=0, db_path=db_path)
    await save_error(batch_id, 1, "max retries", retries=5, db_path=db_path)
    await mark_batch_done(batch_id, db_path)

    batch = await get_batch(batch_id, db_path)
    assert batch["status"] == "partial"
    assert batch["completed"] == 1
    assert batch["failed"] == 1


async def test_batch_failed_on_engine_crash(db_path):
    batch_id = await create_batch(["x"], db_path)
    await mark_batch_failed(batch_id, db_path)
    batch = await get_batch(batch_id, db_path)
    assert batch["status"] == "failed"


async def test_save_result_updates_row(db_path):
    batch_id = await create_batch(["hello"], db_path)
    await save_result(batch_id, 0, {"output": "world"}, retries=2, db_path=db_path)

    rows = await get_results(batch_id, db_path=db_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "completed"
    assert rows[0]["retries"] == 2
    assert "world" in rows[0]["result"]


async def test_get_results_status_filter(db_path):
    batch_id = await create_batch(["a", "b", "c"], db_path)
    await save_result(batch_id, 0, {}, retries=0, db_path=db_path)
    await save_result(batch_id, 1, {}, retries=0, db_path=db_path)
    await save_error(batch_id, 2, "err", retries=5, db_path=db_path)

    completed = await get_results(batch_id, status_filter="completed", db_path=db_path)
    failed = await get_results(batch_id, status_filter="failed", db_path=db_path)

    assert len(completed) == 2
    assert len(failed) == 1


async def test_get_results_pagination(db_path):
    prompts = [f"p{i}" for i in range(10)]
    batch_id = await create_batch(prompts, db_path)

    page1 = await get_results(batch_id, limit=4, offset=0, db_path=db_path)
    page2 = await get_results(batch_id, limit=4, offset=4, db_path=db_path)

    assert len(page1) == 4
    assert len(page2) == 4
    assert page1[0]["prompt_index"] == 0
    assert page2[0]["prompt_index"] == 4
