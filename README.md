# Batch Inference Engine

A production-grade FastAPI service that accepts a batch of AI prompts, processes them concurrently against a mock rate-limited inference endpoint, and aggregates results in SQLite.

---

## Architecture

```mermaid
flowchart TD
    Client(["Client"])

    subgraph API["FastAPI — app/main.py"]
        RL["Rate Limiter\n10 req/min per IP\n(slowapi)"]
        POST["POST /batches\n(HTTP 202 — immediate)"]
        GET_S["GET /batches/{id}\n(status + progress)"]
        GET_R["GET /batches/{id}/results\n(paginated, filterable)"]
        BG["BackgroundTasks.add_task\n(process_batch)"]
    end

    subgraph Engine["Batch Engine — app/services/engine.py"]
        SEM["asyncio.Semaphore\nMAX_WORKERS slots"]
        GATHER["asyncio.gather\n(fan-out all prompts)"]
    end

    subgraph Worker["Worker — app/worker.py"]
        direction TB
        W1["call_inference(prompt, index)"]
        RETRY{"attempt < MAX_RETRIES?"}
        HTTP["httpx.AsyncClient\nPOST /mock/infer"]
        OK{"HTTP 200?"}
        R429{"HTTP 429?"}
        BACKOFF["exponential backoff\n+ jitter\nBase × 2^attempt + rand(0, 0.5)"]
        FAIL["raise InferenceMaxRetriesError"]

        W1 --> RETRY
        RETRY -->|yes| HTTP
        RETRY -->|no| FAIL
        HTTP --> OK
        OK -->|yes| W1_DONE["return result, retries"]
        OK -->|no| R429
        R429 -->|yes| BACKOFF --> RETRY
        R429 -->|no| RETRY
    end

    subgraph Mock["Mock Endpoint — app/mock_api.py"]
        MOCK["POST /mock/infer\n20% chance → 429\nelse → inference result + 50-150 ms delay"]
    end

    subgraph DB["SQLite — WAL mode"]
        T_BATCH[("batches\nid, status, total,\ncompleted, failed")]
        T_RESULTS[("results\nbatch_id, prompt_index,\noutput, retries, error")]
    end

    Client -->|"POST /batches\n{prompts:[…]}"| RL
    RL -->|allowed| POST
    RL -->|exceeded| E429["429 rate_limit_exceeded"]
    POST -->|"create_batch()"| T_BATCH
    POST -->|"schedule"| BG
    POST -->|"202 + batch_id"| Client

    BG --> Engine
    SEM --> GATHER
    GATHER -->|"one task per prompt"| Worker

    W1_DONE -->|"save_result()"| T_RESULTS
    W1_DONE -->|"completed +1"| T_BATCH
    FAIL -->|"save_error()"| T_RESULTS
    FAIL -->|"failed +1"| T_BATCH

    Worker --> Mock

    GATHER -->|"all done"| AGG["Aggregation\nmark_batch_done()\nATOMIC:\nCASE WHEN failed > 0\n  THEN 'partial'\n  ELSE 'completed'"]
    AGG --> T_BATCH

    Client -->|"GET /batches/{id}"| GET_S
    GET_S --> T_BATCH
    Client -->|"GET /batches/{id}/results"| GET_R
    GET_R --> T_RESULTS
```

### Request lifecycle

| Phase | What happens |
|-------|-------------|
| **Accept** | Validate input → insert batch row (`status=accepted`) → schedule background task → return `202 + batch_id` immediately |
| **Fan-out** | `process_batch` acquires a semaphore slot per prompt and fans all tasks out with `asyncio.gather` |
| **Worker / retry loop** | Each worker calls the inference endpoint; on `429` it backs off with `BASE_BACKOFF × 2^attempt + jitter` and retries up to `MAX_RETRIES` times |
| **Persist** | Success → `results` row + `completed` counter incremented; exhausted retries → `results` error row + `failed` counter incremented |
| **Aggregate** | After `gather`, a single atomic SQL `CASE` statement sets the batch to `completed` or `partial` — no TOCTOU race |

---

## Features

- Accepts up to 1,000 prompts via JSON body or file upload
- Returns a `batch_id` immediately (HTTP 202) — processing runs in the background
- Bounded concurrency via `asyncio.Semaphore` (configurable worker count)
- Automatic retry with exponential backoff + jitter on `429` and timeouts
- Per-IP rate limiting on `POST /batches` (10 req/min, configurable)
- Results persisted to SQLite with WAL mode for concurrent writes
- Atomic final-status update to prevent race conditions
- Structured JSON logging on every request and worker event
- 29-test suite across unit and integration layers, with coverage reporting

---

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

Interactive docs are available at [http://localhost:8000/docs](http://localhost:8000/docs) once the server is running.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/batches` | Submit a batch (JSON or file upload) |
| `GET`  | `/batches/{id}` | Poll batch status and progress |
| `GET`  | `/batches/{id}/results` | Fetch results (paginated, filterable by status) |
| `GET`  | `/health` | Liveness + DB reachability check |
| `POST` | `/mock/infer` | Built-in mock inference endpoint |

### Submit via JSON

```bash
curl -X POST http://localhost:8000/batches \
  -H "Content-Type: application/json" \
  -d '{"prompts": ["What is Python?", "Explain async/await"]}'
```

```json
{
  "batch_id": "3fa85f64-...",
  "status": "accepted",
  "total": 2
}
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

```json
{
  "batch_id": "3fa85f64-...",
  "status": "processing",
  "total": 100,
  "completed": 57,
  "failed": 3,
  "created_at": "2026-06-27T10:00:00+00:00",
  "finished_at": null
}
```

Possible `status` values: `accepted` → `processing` → `completed` / `partial` / `failed`

### Fetch results (paginated)

```bash
# First page
curl "http://localhost:8000/batches/<batch_id>/results?limit=100&offset=0"

# Only failures
curl "http://localhost:8000/batches/<batch_id>/results?status=failed"
```

---

## Configuration

All settings can be overridden via environment variables or a `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAX_WORKERS` | `20` | Max concurrent inference calls |
| `MAX_RETRIES` | `5` | Retry attempts per prompt |
| `BASE_BACKOFF` | `1.0` | Base backoff in seconds (doubles each retry) |
| `MOCK_RATE_LIMIT_PCT` | `0.20` | Fraction of mock calls that return 429 |
| `MOCK_INFERENCE_URL` | `http://localhost:8000/mock/infer` | Inference endpoint URL |
| `DB_PATH` | `batches.db` | SQLite database file path |
| `LOG_LEVEL` | `INFO` | Logging level |
| `MAX_PROMPTS` | `1000` | Max prompts per batch |
| `MAX_FILE_SIZE_MB` | `10` | Max upload file size |
| `RATE_LIMIT` | `10/minute` | `POST /batches` rate limit per client IP |

---

## Tests

```bash
# Run all tests
uv run pytest -v

# Run with coverage
uv run pytest --cov=app --cov-report=term-missing -v
```

The test suite covers:
- Database CRUD and status transitions
- Worker retry logic (429, timeout, 500, max retries exceeded)
- Engine concurrency and semaphore bounding
- Route validation, pagination, and error handling
- Rate limit enforcement (429 response with correct error envelope)

---

## Project structure

```
app/
├── main.py              # FastAPI app wiring (lifespan, middleware, handlers)
├── config.py            # Pydantic-settings, reads from env / .env
├── limiter.py           # slowapi Limiter singleton (avoids circular imports)
├── logger.py            # JSON formatter + setup_logging()
├── exceptions.py        # Custom exception types
├── error_handlers.py    # FastAPI exception → JSON response mapping
├── middleware.py        # Request logging middleware (request_id, duration)
├── database.py          # aiosqlite CRUD, init_db, WAL mode
├── schemas.py           # Pydantic request / response models
├── mock_api.py          # Mock inference endpoint (429 injection)
├── worker.py            # Single-prompt retry loop
├── routers/
│   ├── batches.py       # POST /batches, GET /batches/{id}, GET /batches/{id}/results
│   └── system.py        # GET /health
└── services/
    └── engine.py        # Semaphore + asyncio.gather orchestration
tests/
├── conftest.py          # Fixtures: temp DB, async client, fast backoff
├── test_database.py     # DB layer unit tests
├── test_worker.py       # Worker + retry unit tests (respx mocks)
├── test_engine.py       # Engine integration tests
└── test_routes.py       # Route-level integration tests
```
