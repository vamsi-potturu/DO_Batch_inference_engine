import asyncio
import logging
import random

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mock", tags=["mock"])


class InferRequest(BaseModel):
    prompt: str


@router.post("/infer")
async def mock_infer(payload: InferRequest) -> Response:
    """Simulates a rate-limited AI inference endpoint.

    Returns 429 at MOCK_RATE_LIMIT_PCT frequency.
    Otherwise sleeps 50-150ms and returns a fake inference result.
    """
    if random.random() < settings.MOCK_RATE_LIMIT_PCT:
        logger.warning("mock rate limit triggered prompt_preview=%.30s", payload.prompt)
        return Response(status_code=429, content="rate limit exceeded")

    await asyncio.sleep(random.uniform(0.05, 0.15))

    word_count = len(payload.prompt.split())
    result = {
        "output": f"Inference result for: {payload.prompt[:50]}",
        "tokens_used": word_count * 3,
        "model": "mock-v1",
    }

    logger.info("mock infer ok prompt_preview=%.30s", payload.prompt)
    return Response(
        status_code=200,
        content=__import__("json").dumps(result),
        media_type="application/json",
    )
