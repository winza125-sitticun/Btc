import json

import httpx
import pytest

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.providers.base import AIProviderRuntimeConfig
from btc_core.ai.providers.gemini import GeminiProviderClient
from tests.test_ai_provider_openai_compatible import make_snapshot


def config() -> AIProviderRuntimeConfig:
    return AIProviderRuntimeConfig(
        provider=AIProvider.GEMINI,
        model="gemini-test",
        api_key="gemini-secret",
        base_url="https://generativelanguage.googleapis.com/v1beta",
    )


def fenced_success_body() -> dict:
    decision = {
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "direction": "LONG",
        "confidence": 84,
        "entry_min": 99,
        "entry_max": 100,
        "stop_loss": 96,
        "take_profits": [104, 108],
        "risk_reward": 2.5,
        "reason_summary": "Trend alignment.",
    }
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "```json\n" + json.dumps(decision) + "\n```"}
                    ]
                }
            }
        ]
    }


@pytest.mark.asyncio
async def test_plain_gemini_fallback_accepts_one_json_code_fence_then_validates_strictly():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        body = json.loads(request.content)
        if calls <= 2:
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})
        assert "generationConfig" not in body
        return httpx.Response(200, json=fenced_success_body())

    async with GeminiProviderClient(config(), transport=httpx.MockTransport(handler)) as client:
        decision = await client.analyze(make_snapshot())

    assert calls == 3
    assert decision.provider is AIProvider.GEMINI
    assert decision.direction is Direction.LONG
    assert decision.confidence == 84
