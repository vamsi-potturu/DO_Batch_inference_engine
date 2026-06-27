# Batch Inference Engine

A production-grade FastAPI service that accepts a batch of AI prompts, processes them concurrently against a mock rate-limited inference endpoint, and aggregates results in SQLite.

## Features

- Accepts up to 1000 prompts via JSON body or file upload
- Returns a `batch_id` immediately (HTTP 202) — processing continues in the background
- Concurrent processing via `asyncio.Semaphore` (configurable worker count)
- Automatic retry with exponential backoff + jitter on 429 and timeouts
- Results persisted to SQLite with WAL mode for concurrent writes
- Structured JSON logging on every request and worker event
- Full test suite: 28 tests across unit and integration layers

## Setup

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync --group dev

# Activate virtualenv (optional — uv run works without it)
source .venv/bin/activate
```

## Run

```bash
uv run uvicorn app.main:app --reload --port 8000
```

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/batches` | Submit a batch (JSON or file upload) |
| `GET` | `/batches/{id}` | Poll batch status and progress |
| `GET` | `/batches/{id}/results` | Fetch results (paginated, filterable) |
| `GET` | `/health` | Liveness check |
| `POST` | `/mock/infer` | Mock inference endpoint (built-in) |

### Submit via JSON

```bash
curl -X POST http://localhost:8000/batches \
  -H "Content-Type: application/json" \
  -d '{"prompts": ["What is Python?", "Explain async/await"]}'
```

### Submit via file

```bash
echo '["prompt one", "prompt two", "prompt three"]' > prompts.json

curl -X POST http://localhost:8000/batches \
  -F "file=@prompts.json"
```

### Poll status

```bash
curl http://localhost:8000/batches/<batch_id>
```

### Fetch results (paginated)

```bash
curl "http://localhost:8000/batches/<batch_id>/results?limit=100&offset=0"

# Filter by status
curl "http://localhost:8000/batches/<batch_id>/results?status=failed"
```

## Configuration

All settings can be overridden via environment variables or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_WORKERS` | `20` | Max concurrent inference calls |
| `MAX_RETRIES` | `5` | Retry attempts per prompt |
| `BASE_BACKOFF` | `1.0` | Base backoff in seconds (doubles each retry) |
| `MOCK_RATE_LIMIT_PCT` | `0.20` | Fraction of mock calls that return 429 |
| `DB_PATH` | `batches.db` | SQLite database file path |
| `LOG_LEVEL` | `INFO` | Logging level |
| `MAX_PROMPTS` | `1000` | Max prompts per batch |
| `MAX_FILE_SIZE_MB` | `10` | Max upload file size |

## Tests

```bash
# Run all tests
uv run pytest -v

# Run with coverage
uv run pytest --cov=app --cov-report=term-missing -v
```

## Architecture

```
POST /batches
    → validate input
    → insert batch + result rows (status=pending)
    → BackgroundTasks.add_task(process_batch)
    → return 202 + batch_id

process_batch (background)
    → asyncio.Semaphore(MAX_WORKERS)
    → asyncio.gather(worker for each prompt)
        → worker: retry loop with backoff on 429/timeout
        → save result or error to DB
    → mark batch completed / partial / failed
```
