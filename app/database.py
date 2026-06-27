import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import aiosqlite

from app.config import settings

# ── Schema ────────────────────────────────────────────────────────────────────

_CREATE_BATCHES = """
CREATE TABLE IF NOT EXISTS batches (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL,
    total       INTEGER NOT NULL,
    completed   INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    finished_at TEXT
);
"""

_CREATE_RESULTS = """
CREATE TABLE IF NOT EXISTS results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id      TEXT NOT NULL,
    prompt_index  INTEGER NOT NULL,
    prompt        TEXT NOT NULL,
    result        TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    retries       INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    FOREIGN KEY (batch_id) REFERENCES batches(id)
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_results_batch
ON results(batch_id, status);
"""


# ── Connection helper ─────────────────────────────────────────────────────────

@asynccontextmanager
async def get_db(db_path: str | None = None):
    """Async context manager that opens an aiosqlite connection."""
    path = db_path or settings.DB_PATH
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON")
        yield db


# ── Init ──────────────────────────────────────────────────────────────────────

async def init_db(db_path: str | None = None) -> None:
    """Create tables and index. Sets WAL mode once at startup."""
    async with get_db(db_path) as db:
        # WAL is a database-level persistent setting — set it once here,
        # not on every connection open.
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute(_CREATE_BATCHES)
        await db.execute(_CREATE_RESULTS)
        await db.execute(_CREATE_INDEX)
        await db.commit()


# ── Batch CRUD ────────────────────────────────────────────────────────────────

async def create_batch(prompts: list[str], db_path: str | None = None) -> str:
    """Insert a new batch and its pending result rows. Returns batch_id."""
    batch_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    async with get_db(db_path) as db:
        await db.execute(
            "INSERT INTO batches (id, status, total, created_at) VALUES (?, ?, ?, ?)",
            (batch_id, "accepted", len(prompts), now),
        )
        await db.executemany(
            "INSERT INTO results (batch_id, prompt_index, prompt) VALUES (?, ?, ?)",
            [(batch_id, i, prompt) for i, prompt in enumerate(prompts)],
        )
        await db.commit()

    return batch_id


async def get_batch(batch_id: str, db_path: str | None = None) -> dict | None:
    """Return batch row as dict, or None if not found."""
    async with get_db(db_path) as db:
        async with db.execute(
            "SELECT * FROM batches WHERE id = ?", (batch_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def mark_batch_processing(batch_id: str, db_path: str | None = None) -> None:
    async with get_db(db_path) as db:
        await db.execute(
            "UPDATE batches SET status = 'processing' WHERE id = ?", (batch_id,)
        )
        await db.commit()


async def mark_batch_done(batch_id: str, db_path: str | None = None) -> None:
    """Set final status atomically to 'completed' or 'partial' based on failed count.

    Uses a single CASE statement to avoid a TOCTOU race between reading the
    failed counter and writing the status under concurrent worker writes.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with get_db(db_path) as db:
        await db.execute(
            """UPDATE batches
               SET status      = CASE WHEN failed > 0 THEN 'partial' ELSE 'completed' END,
                   finished_at = ?
               WHERE id = ?""",
            (now, batch_id),
        )
        await db.commit()


async def mark_batch_failed(batch_id: str, db_path: str | None = None) -> None:
    """Mark entire batch as failed — used when engine itself crashes."""
    now = datetime.now(timezone.utc).isoformat()
    async with get_db(db_path) as db:
        await db.execute(
            "UPDATE batches SET status = 'failed', finished_at = ? WHERE id = ?",
            (now, batch_id),
        )
        await db.commit()


# ── Result CRUD ───────────────────────────────────────────────────────────────

async def save_result(
    batch_id: str,
    prompt_index: int,
    result: dict,
    retries: int,
    db_path: str | None = None,
) -> None:
    """Mark a prompt result as completed and increment batch counter."""
    async with get_db(db_path) as db:
        await db.execute(
            """UPDATE results
               SET status = 'completed', result = ?, retries = ?
               WHERE batch_id = ? AND prompt_index = ?""",
            (json.dumps(result), retries, batch_id, prompt_index),
        )
        await db.execute(
            "UPDATE batches SET completed = completed + 1 WHERE id = ?",
            (batch_id,),
        )
        await db.commit()


async def save_error(
    batch_id: str,
    prompt_index: int,
    error: str,
    retries: int,
    db_path: str | None = None,
) -> None:
    """Mark a prompt result as failed and increment batch failure counter."""
    async with get_db(db_path) as db:
        await db.execute(
            """UPDATE results
               SET status = 'failed', error = ?, retries = ?
               WHERE batch_id = ? AND prompt_index = ?""",
            (error, retries, batch_id, prompt_index),
        )
        await db.execute(
            "UPDATE batches SET failed = failed + 1 WHERE id = ?",
            (batch_id,),
        )
        await db.commit()


async def get_results(
    batch_id: str,
    status_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db_path: str | None = None,
) -> list[dict]:
    """Return paginated result rows for a batch, optionally filtered by status."""
    query = "SELECT * FROM results WHERE batch_id = ?"
    params: list = [batch_id]

    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)

    query += " ORDER BY prompt_index LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    async with get_db(db_path) as db:
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
