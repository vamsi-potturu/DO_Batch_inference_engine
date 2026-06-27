import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Request, UploadFile
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import create_batch, get_batch, get_results
from app.exceptions import BatchNotFoundError, InvalidInputError
from app.schemas import BatchAccepted, BatchResults, BatchStatus, PromptResult
from app.services.engine import process_batch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/batches", tags=["batches"])


def _get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


# ── POST /batches ─────────────────────────────────────────────────────────────

@router.post("", status_code=202, response_model=BatchAccepted)
async def create_batch_endpoint(
    request: Request,
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = None,
) -> BatchAccepted:
    """Accept a batch of prompts via JSON body or file upload.

    Returns 202 immediately. Processing continues in the background.
    """
    prompts = await _parse_prompts(request, file)

    batch_id = await create_batch(prompts)
    client = _get_http_client(request)

    background_tasks.add_task(process_batch, batch_id, prompts, client)

    logger.info("batch accepted batch_id=%s total=%d", batch_id, len(prompts))
    return BatchAccepted(batch_id=batch_id, status="accepted", total=len(prompts))


async def _parse_prompts(request: Request, file: Optional[UploadFile]) -> list[str]:
    """Extract prompts from either a file upload or a JSON request body."""
    if file is not None:
        return await _read_prompts_from_file(file)
    return await _read_prompts_from_body(request)


async def _read_prompts_from_file(file: UploadFile) -> list[str]:
    max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    chunks: list[bytes] = []
    total = 0

    while chunk := await file.read(65536):  # 64KB chunks
        total += len(chunk)
        if total > max_bytes:
            raise InvalidInputError(
                f"File exceeds maximum allowed size of {settings.MAX_FILE_SIZE_MB}MB"
            )
        chunks.append(chunk)

    try:
        data = json.loads(b"".join(chunks))
    except json.JSONDecodeError as exc:
        raise InvalidInputError(f"Invalid JSON in uploaded file: {exc}") from exc

    return _validate_prompts(data)


async def _read_prompts_from_body(request: Request) -> list[str]:
    try:
        data = await request.json()
    except Exception as exc:
        raise InvalidInputError(f"Invalid JSON body: {exc}") from exc

    if not isinstance(data, dict) or "prompts" not in data:
        raise InvalidInputError("Request body must be a JSON object with a 'prompts' key")

    return _validate_prompts(data["prompts"])


def _validate_prompts(data: object) -> list[str]:
    if not isinstance(data, list):
        raise InvalidInputError("'prompts' must be a JSON array")
    if len(data) == 0:
        raise InvalidInputError("'prompts' array cannot be empty")
    if len(data) > settings.MAX_PROMPTS:
        raise InvalidInputError(
            f"Too many prompts: {len(data)} exceeds limit of {settings.MAX_PROMPTS}"
        )
    if not all(isinstance(p, str) and p.strip() for p in data):
        raise InvalidInputError("Each prompt must be a non-empty string")
    return [str(p) for p in data]


# ── GET /batches/{batch_id} ───────────────────────────────────────────────────

@router.get("/{batch_id}", response_model=BatchStatus)
async def get_batch_status(batch_id: str) -> BatchStatus:
    batch = await get_batch(batch_id)
    if batch is None:
        raise BatchNotFoundError(batch_id)
    return BatchStatus(**batch)


# ── GET /batches/{batch_id}/results ──────────────────────────────────────────

@router.get("/{batch_id}/results", response_model=BatchResults)
async def get_batch_results(
    batch_id: str,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> BatchResults:
    batch = await get_batch(batch_id)
    if batch is None:
        raise BatchNotFoundError(batch_id)

    rows = await get_results(batch_id, status_filter=status, limit=limit, offset=offset)
    items = [PromptResult(**row) for row in rows]

    return BatchResults(batch_id=batch_id, total=batch["total"], items=items)
