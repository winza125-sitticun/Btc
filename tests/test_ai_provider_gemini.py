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


@pytest.mark.asyncio
async def test_gemini_uses_configured_model_and_structured_json_output():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert request.url.path.endswith("/models/gemini-test:generateContent")
        assert request.headers["x-goog-api-key"] == "gemini-secret"
        generation = body["generationConfig"]
        assert "responseMimeType" not in generation
        assert "responseJsonSchema" not in generation

        response_format = generation["responseFormat"]
        assert set(response_format) == {"text"}
        assert response_format["text"]["mimeType"] == "application/json"
        schema = response_format["text"]["schema"]
        assert schema["type"] == "object"
        assert "direction" in schema["properties"]

        encoded_schema = json.dumps(schema)
        assert '"exclusiveMinimum"' not in encoded_schema
        assert '"exclusiveMaximum"' not in encoded_schema
        assert '"minLength"' not in encoded_schema
        assert '"maxLength"' not in encoded_schema
        assert schema["properties"]["entry_min"]["minimum"] == 0
        assert schema["properties"]["take_profits"]["minItems"] == 1
        assert schema["properties"]["take_profits"]["maxItems"] == 5

        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "provider": "GEMINI",
                                            "model": "gemini-test",
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
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    async with GeminiProviderClient(config(), transport=httpx.MockTransport(handler)) as client:
        decision = await client.analyze(make_snapshot())

    assert len(requests) == 1
    assert decision.provider is AIProvider.GEMINI
    assert decision.direction is Direction.LONG
