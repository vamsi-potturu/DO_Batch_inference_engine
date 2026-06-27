import logging
import sys
from contextvars import ContextVar

import structlog

from app.config import Settings

# Bound per HTTP request by middleware in main.py.
# Engine binds batch_id instead for background tasks.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def _add_request_id(logger: object, method: str, event_dict: dict) -> dict:
    event_dict["request_id"] = request_id_var.get()
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Configure structlog JSON logging once at startup.

    All log lines — including uvicorn and httpx — are emitted as JSON to stdout.
    """
    level = logging.getLevelName(settings.LOG_LEVEL)

    processors = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib loggers (uvicorn, httpx) through the same JSON format
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str = __name__) -> structlog.BoundLogger:
    """Return a structlog logger bound to the calling module name."""
    return structlog.get_logger().bind(logger=name)
