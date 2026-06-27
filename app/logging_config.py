import logging
import sys
from contextvars import ContextVar

import structlog

from app.config import Settings

# Set per HTTP request by middleware. Background tasks bind batch_id instead.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def _add_request_id(logger: object, method: str, event_dict: dict) -> dict:
    event_dict["request_id"] = request_id_var.get()
    return event_dict


# Shared pre-processors applied to every log line regardless of origin.
_PRE_PROCESSORS = [
    structlog.contextvars.merge_contextvars,
    _add_request_id,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
]


def configure_logging(settings: Settings) -> None:
    """Configure JSON logging once at startup.

    All log lines — app code, uvicorn, httpx — are emitted as JSON to stdout.
    """
    level = logging.getLevelName(settings.LOG_LEVEL)

    # structlog chain: used by app code via get_logger()
    structlog.configure(
        processors=[*_PRE_PROCESSORS, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # stdlib chain: routes uvicorn/httpx logs through the same JSON format
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_PRE_PROCESSORS,
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
