import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions import (
    BatchAlreadyProcessingError,
    BatchNotFoundError,
    InvalidInputError,
)

logger = logging.getLogger(__name__)


async def batch_not_found_handler(request: Request, exc: BatchNotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": "not_found", "message": str(exc), "batch_id": exc.batch_id},
    )


async def batch_already_processing_handler(
    request: Request, exc: BatchAlreadyProcessingError
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error": "conflict", "message": str(exc), "batch_id": exc.batch_id},
    )


async def invalid_input_handler(request: Request, exc: InvalidInputError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "invalid_input", "message": str(exc), "batch_id": None},
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    fields = ", ".join(str(e["loc"][-1]) for e in errors)
    message = "; ".join(e["msg"] for e in errors)
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": f"Invalid fields [{fields}]: {message}",
            "batch_id": None,
        },
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "An unexpected error occurred.",
            "batch_id": None,
        },
    )
