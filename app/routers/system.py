import logging

import aiosqlite
from fastapi import APIRouter

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict:
    """Liveness check. Verifies the DB file is reachable."""
    try:
        async with aiosqlite.connect(settings.DB_PATH) as db:
            await db.execute("SELECT 1")
        db_status = "ok"
    except Exception as exc:
        logger.error("health check db error: %s", exc)
        db_status = "degraded"

    return {"status": "ok", "db": db_status}
