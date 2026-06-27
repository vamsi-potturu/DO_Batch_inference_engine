import httpx
import pytest
import respx

from app.exceptions import InferenceMaxRetriesError
from app.worker import call_inference

INFER_URL = "http://localhost:8000/mock/infer"


@respx.mock
async def test_success_on_first_attempt(fast_backoff):
    respx.post(INFER_URL).mock(
        return_value=httpx.Response(200, json={"output": "hello"})
    )
    async with httpx.AsyncClient() as client:
        result, retries = await call_inference(client, "prompt", prompt_index=0)

    assert result == {"output": "hello"}
    assert retries == 0


@respx.mock
async def test_success_after_429_retries(fast_backoff):
    # First two calls return 429, third returns 200
    respx.post(INFER_URL).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(429),
            httpx.Response(200, json={"output": "done"}),
        ]
    )
    async with httpx.AsyncClient() as client:
        result, retries = await call_inference(client, "prompt", prompt_index=0)

    assert result == {"output": "done"}
    assert retries == 2


@respx.mock
async def test_max_retries_exceeded_raises(fast_backoff):
    respx.post(INFER_URL).mock(return_value=httpx.Response(429))

    with pytest.raises(InferenceMaxRetriesError) as exc_info:
        async with httpx.AsyncClient() as client:
            await call_inference(client, "prompt", prompt_index=7)

    assert exc_info.value.prompt_index == 7


@respx.mock
async def test_timeout_retries_then_succeeds(fast_backoff):
    respx.post(INFER_URL).mock(
        side_effect=[
            httpx.TimeoutException("timed out"),
            httpx.Response(200, json={"output": "ok"}),
        ]
    )
    async with httpx.AsyncClient() as client:
        result, retries = await call_inference(client, "prompt", prompt_index=0)

    assert result == {"output": "ok"}
    assert retries == 1


@respx.mock
async def test_500_retries(fast_backoff):
    respx.post(INFER_URL).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json={"output": "recovered"}),
        ]
    )
    async with httpx.AsyncClient() as client:
        result, retries = await call_inference(client, "prompt", prompt_index=0)

    assert result == {"output": "recovered"}
    assert retries == 1
