import asyncio
import logging
import random

import httpx

from app.config import settings
from app.exceptions import InferenceMaxRetriesError

logger = logging.getLogger(__name__)


async def call_inference(
    client: httpx.AsyncClient,
    prompt: str,
    prompt_index: int,
) -> tuple[dict, int]:
    """Call the inference endpoint with exponential backoff on 429 or timeout.

    Returns (result_dict, retries_used) on success.
    Raises InferenceMaxRetriesError after MAX_RETRIES exhausted.
    """
    url = settings.MOCK_INFERENCE_URL

    for attempt in range(settings.MAX_RETRIES):
        try:
            response = await client.post(
                url,
                json={"prompt": prompt},
                timeout=10.0,
            )

            if response.status_code == 200:
                logger.info(
                    "worker ok prompt_index=%d attempt=%d", prompt_index, attempt
                )
                return response.json(), attempt

            if response.status_code == 429:
                wait = settings.BASE_BACKOFF * (2 ** attempt) + random.uniform(0, 0.5)
                logger.warning(
                    "worker rate_limited prompt_index=%d attempt=%d wait=%.2fs",
                    prompt_index, attempt, wait,
                )
                await asyncio.sleep(wait)
                continue

            # any other HTTP error (5xx etc.) — log and retry
            logger.warning(
                "worker http_error prompt_index=%d attempt=%d status=%d",
                prompt_index, attempt, response.status_code,
            )

        except httpx.TimeoutException:
            logger.warning(
                "worker timeout prompt_index=%d attempt=%d", prompt_index, attempt
            )

    raise InferenceMaxRetriesError(prompt_index=prompt_index, attempts=settings.MAX_RETRIES)
