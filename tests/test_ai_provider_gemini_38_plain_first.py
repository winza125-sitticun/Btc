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
        model="gemini-3.8-flash",
        api_key="gemini-secret",
        base_url="https://generativelanguage.googleapis.com/v1beta",
    )


@pytest.mark.asyncio
async def test_gemini_38_uses_plain_generate_content_first_and_validates_result():
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
        body = json.loads(request.content)
        assert request.url.path.endswith("/models/gemini-3.8-flash:generateContent")
        assert "generationConfig" not in body
        assert "Return exactly one JSON object" in body["contents"][0]["parts"][0]["text"]
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "```json\n" + json.dumps(decision) + "\n```"}
                            ]
                        }
                    }
                ]
            },
        )

    async with GeminiProviderClient(config(), transport=httpx.MockTransport(handler)) as client:
        result = await client.analyze(make_snapshot())

    assert len(requests) == 1
    assert result.provider is AIProvider.GEMINI
    assert result.model == "gemini-3.8-flash"
    assert result.direction is Direction.LONG
