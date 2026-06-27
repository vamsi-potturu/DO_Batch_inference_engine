from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.config import settings


# ── Requests ──────────────────────────────────────────────────────────────────

class BatchRequest(BaseModel):
    prompts: list[str] = Field(
        min_length=1,
        max_length=settings.MAX_PROMPTS,
        description="List of prompts to process (1 – MAX_PROMPTS)",
    )


# ── Responses ─────────────────────────────────────────────────────────────────

class BatchAccepted(BaseModel):
    batch_id: str
    status: str
    total: int


class BatchStatus(BaseModel):
    model_config = {"populate_by_name": True}

    batch_id: str = Field(validation_alias="id")
    status: str
    total: int
    completed: int
    failed: int
    created_at: str
    finished_at: Optional[str] = None


class PromptResult(BaseModel):
    prompt_index: int
    prompt: str
    result: Optional[Any] = None
    status: str
    retries: int
    error: Optional[str] = None


class BatchResults(BaseModel):
    batch_id: str
    total: int
    items: list[PromptResult]
