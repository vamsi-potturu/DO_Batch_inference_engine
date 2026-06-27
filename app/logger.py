import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log: dict = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log["exception"] = self.formatException(record.exc_info)
        return json.dumps(log)


def setup_logging() -> None:
    """Configure JSON logging once at startup.

    All log lines — app code, uvicorn, httpx — are emitted as JSON to stdout.
    Noisy uvicorn access logs are suppressed; request logging is handled by middleware.
    """
    from app.config import settings

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # suppress uvicorn access logs — middleware handles request logging
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
