import asyncio
import logging

import httpx

from app.config import settings
from app.database import (
    mark_batch_done,
    mark_batch_failed,
    mark_batch_processing,
    save_error,
    save_result,
)
from app.exceptions import InferenceMaxRetriesError
from app.worker import call_inference

logger = logging.getLogger(__name__)


async def process_batch(
    batch_id: str,
    prompts: list[str],
    client: httpx.AsyncClient,
    db_path: str | None = None,
) -> None:
    """Fan out all prompts concurrently, bounded by a semaphore.

    Each prompt is retried independently. One failing prompt never cancels
    the rest. The batch is marked done (completed/partial/failed) when all
    workers finish.
    """
    logger.info("engine started batch_id=%s total=%d", batch_id, len(prompts))

    try:
        await mark_batch_processing(batch_id, db_path)

        sem = asyncio.Semaphore(settings.MAX_WORKERS)

        async def run(index: int, prompt: str) -> None:
            async with sem:
                try:
                    result, retries = await call_inference(client, prompt, index)
                    await save_result(batch_id, index, result, retries, db_path)
                    logger.info(
                        "engine prompt_done batch_id=%s prompt_index=%d retries=%d",
                        batch_id, index, retries,
                    )
                except InferenceMaxRetriesError as exc:
                    await save_error(batch_id, index, str(exc), exc.attempts, db_path)
                    logger.error(
                        "engine prompt_failed batch_id=%s prompt_index=%d attempts=%d",
                        batch_id, index, exc.attempts,
                    )

        tasks = [run(i, p) for i, p in enumerate(prompts)]
        await asyncio.gather(*tasks, return_exceptions=True)
        await mark_batch_done(batch_id, db_path)

        logger.info("engine finished batch_id=%s", batch_id)

    except Exception as exc:
        # Guard against unexpected crashes — never leave a batch stuck in 'processing'
        logger.exception("engine crashed batch_id=%s error=%s", batch_id, exc)
        await mark_batch_failed(batch_id, db_path)
