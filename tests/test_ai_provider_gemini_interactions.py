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
        timeout_seconds=60,
        max_retries=0,
    )


@pytest.mark.asyncio
async def test_gemini_38_uses_stateless_interactions_structured_output_with_low_thinking():
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
        assert request.headers["x-goog-api-key"] == "gemini-secret"

        body = json.loads(request.content)
        assert body["model"] == "gemini-3.8-flash"
        assert body["store"] is False
        assert body["generation_config"] == {"thinking_level": "low"}
        assert "Analyze this bounded crypto futures snapshot" in body["input"]

        response_format = body["response_format"]
        assert response_format["type"] == "text"
        assert response_format["mime_type"] == "application/json"
        schema = response_format["schema"]
        assert schema["type"] == "object"
        assert "provider" not in schema["properties"]
        assert "model" not in schema["properties"]
        assert "provider" not in schema.get("required", [])
        assert "model" not in schema.get("required", [])
        assert "direction" in schema["properties"]

        return httpx.Response(
            200,
            json={
                "id": "int_test",
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
                "model": "gemini-3.8-flash",
            },
        )

    async with GeminiProviderClient(config(), transport=httpx.MockTransport(handler)) as client:
        result = await client.analyze(make_snapshot())

    assert len(requests) == 1
    assert result.provider is AIProvider.GEMINI
    assert result.model == "gemini-3.8-flash"
    assert result.direction is Direction.LONG
    assert result.confidence == 84
