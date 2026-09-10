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
        model="gemini-3.5-flash-lite",
        api_key="gemini-secret",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds=60,
        max_retries=0,
    )


@pytest.mark.asyncio
async def test_gemini_35_flash_lite_uses_interactions_with_minimal_thinking():
    requests: list[httpx.Request] = []
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

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/v1beta/interactions"
        body = json.loads(request.content)
        assert body["model"] == "gemini-3.5-flash-lite"
        assert body["store"] is False
        assert body["generation_config"] == {
            "thinking_level": "minimal",
            "max_output_tokens": 512,
        }
        return httpx.Response(
            200,
            json={
                "id": "int_lite",
                "status": "completed",
                "steps": [
                    {
                        "type": "model_output",
                        "status": "done",
                        "content": [
                            {"type": "text", "text": json.dumps(decision)}
                        ],
                    }
                ],
                "object": "interaction",
                "model": "gemini-3.5-flash-lite",
            },
        )

    async with GeminiProviderClient(config(), transport=httpx.MockTransport(handler)) as client:
        result = await client.analyze(make_snapshot())

    assert len(requests) == 1
    assert result.provider is AIProvider.GEMINI
    assert result.model == "gemini-3.5-flash-lite"
    assert result.direction is Direction.LONG
