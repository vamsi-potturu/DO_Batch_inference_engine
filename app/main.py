from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded

from app.database import init_db
from app.limiter import limiter
from app.error_handlers import (
    batch_already_processing_handler,
    batch_not_found_handler,
    invalid_input_handler,
    rate_limit_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.exceptions import (
    BatchAlreadyProcessingError,
    BatchNotFoundError,
    InvalidInputError,
)
from app.logger import setup_logging
from app.middleware import RequestLoggingMiddleware
from app.mock_api import router as mock_router
from app.routers.batches import router as batches_router
from app.routers.system import router as system_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    setup_logging()
    await init_db()
    app.state.http_client = httpx.AsyncClient()

    yield

    # Shutdown — close HTTP client gracefully
    await app.state.http_client.aclose()


app = FastAPI(
    title="Batch Inference Engine",
    description="Concurrent batch AI prompt processing with rate-limit handling",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter

# Middleware
app.add_middleware(RequestLoggingMiddleware)

# Exception handlers
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_exception_handler(BatchNotFoundError, batch_not_found_handler)
app.add_exception_handler(BatchAlreadyProcessingError, batch_already_processing_handler)
app.add_exception_handler(InvalidInputError, invalid_input_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

# Routers
app.include_router(batches_router)
app.include_router(system_router)
app.include_router(mock_router)
