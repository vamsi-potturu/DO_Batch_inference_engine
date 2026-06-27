import json
from unittest.mock import AsyncMock, patch

import pytest
from app import config


# ── POST /batches ─────────────────────────────────────────────────────────────

async def test_post_batches_json(client):
    with patch("app.routers.batches.process_batch", new=AsyncMock()):
        resp = await client.post("/batches", json={"prompts": ["hello", "world"]})

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "accepted"
    assert body["total"] == 2
    assert "batch_id" in body


async def test_post_batches_file_upload(client, tmp_path):
    prompts_file = tmp_path / "prompts.json"
    prompts_file.write_text(json.dumps(["prompt one", "prompt two"]))

    with patch("app.routers.batches.process_batch", new=AsyncMock()):
        with open(prompts_file, "rb") as f:
            resp = await client.post("/batches", files={"file": ("prompts.json", f, "application/json")})

    assert resp.status_code == 202
    assert resp.json()["total"] == 2


async def test_post_batches_empty_prompts_returns_422(client):
    resp = await client.post("/batches", json={"prompts": []})
    assert resp.status_code == 422
    assert "error" in resp.json()


async def test_post_batches_too_many_prompts_returns_422(client):
    resp = await client.post("/batches", json={"prompts": ["x"] * 1001})
    assert resp.status_code == 422


async def test_post_batches_missing_key_returns_422(client):
    resp = await client.post("/batches", json={"wrong_key": ["a"]})
    assert resp.status_code == 422


# ── GET /batches/{id} ─────────────────────────────────────────────────────────

async def test_get_batch_status(client):
    with patch("app.routers.batches.process_batch", new=AsyncMock()):
        post = await client.post("/batches", json={"prompts": ["a", "b"]})
    batch_id = post.json()["batch_id"]

    resp = await client.get(f"/batches/{batch_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["batch_id"] == batch_id
    assert body["total"] == 2
    assert body["status"] in ("accepted", "processing", "completed")


async def test_get_batch_not_found(client):
    resp = await client.get("/batches/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"] == "not_found"


# ── GET /batches/{id}/results ─────────────────────────────────────────────────

async def test_get_results_returns_items(client):
    with patch("app.routers.batches.process_batch", new=AsyncMock()):
        post = await client.post("/batches", json={"prompts": ["p1", "p2"]})
    batch_id = post.json()["batch_id"]

    resp = await client.get(f"/batches/{batch_id}/results")
    assert resp.status_code == 200
    body = resp.json()
    assert body["batch_id"] == batch_id
    assert body["total"] == 2
    assert len(body["items"]) == 2


async def test_get_results_not_found(client):
    resp = await client.get("/batches/ghost-id/results")
    assert resp.status_code == 404


async def test_get_results_pagination(client):
    with patch("app.routers.batches.process_batch", new=AsyncMock()):
        post = await client.post("/batches", json={"prompts": [f"p{i}" for i in range(10)]})
    batch_id = post.json()["batch_id"]

    resp = await client.get(f"/batches/{batch_id}/results?limit=3&offset=0")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 3


# ── Rate limiting ─────────────────────────────────────────────────────────────

async def test_rate_limit_triggers_429(monkeypatch, client):
    """Exceeding the batch creation rate limit must return 429 with our error envelope."""
    monkeypatch.setattr(config.settings, "RATE_LIMIT", "2/minute")
    # Re-apply so slowapi picks up the new string for this test.
    from app.limiter import limiter
    from slowapi.util import get_remote_address

    with patch("app.routers.batches.process_batch", new=AsyncMock()):
        for _ in range(2):
            r = await client.post("/batches", json={"prompts": ["x"]})
            assert r.status_code == 202

        # 3rd call must be rate-limited
        r = await client.post("/batches", json={"prompts": ["x"]})

    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limit_exceeded"


# ── GET /health ───────────────────────────────────────────────────────────────

async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.json()["db"] == "ok"
