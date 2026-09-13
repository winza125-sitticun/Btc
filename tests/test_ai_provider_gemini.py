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


def success_body() -> dict:
    return {
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
    }


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

        entry_schema = schema["properties"]["entry_min"]
        numeric_entry_schema = next(
            option for option in entry_schema["anyOf"] if option.get("type") == "number"
        )
        assert numeric_entry_schema["minimum"] == 0
        assert "entry_min" not in schema["required"]
        assert "entry_max" not in schema["required"]
        assert "stop_loss" not in schema["required"]
        assert "risk_reward" not in schema["required"]
        assert "take_profits" not in schema["required"]
        assert "minItems" not in schema["properties"]["take_profits"]
        assert schema["properties"]["take_profits"]["maxItems"] == 5

        return httpx.Response(200, json=success_body())

    async with GeminiProviderClient(config(), transport=httpx.MockTransport(handler)) as client:
        decision = await client.analyze(make_snapshot())

    assert len(requests) == 1
    assert decision.provider is AIProvider.GEMINI
    assert decision.direction is Direction.LONG


@pytest.mark.asyncio
async def test_gemini_falls_back_to_json_mime_when_structured_schema_is_rejected():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        response_text = body["generationConfig"]["responseFormat"]["text"]
        if len(requests) == 1:
            assert "schema" in response_text
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})

        assert response_text == {"mimeType": "application/json"}
        return httpx.Response(200, json=success_body())

    async with GeminiProviderClient(config(), transport=httpx.MockTransport(handler)) as client:
        decision = await client.analyze(make_snapshot())

    assert len(requests) == 2
    assert decision.provider is AIProvider.GEMINI
    assert decision.direction is Direction.LONG


@pytest.mark.asyncio
async def test_gemini_falls_back_to_plain_generate_content_when_response_format_is_rejected():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        if len(requests) == 1:
            assert "schema" in body["generationConfig"]["responseFormat"]["text"]
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})
        if len(requests) == 2:
            assert body["generationConfig"]["responseFormat"]["text"] == {
                "mimeType": "application/json"
            }
            return httpx.Response(400, json={"error": {"status": "INVALID_ARGUMENT"}})

        assert "generationConfig" not in body
        assert "Return exactly one JSON object" in body["contents"][0]["parts"][0]["text"]
        return httpx.Response(200, json=success_body())

    async with GeminiProviderClient(config(), transport=httpx.MockTransport(handler)) as client:
        decision = await client.analyze(make_snapshot())

    assert len(requests) == 3
    assert decision.provider is AIProvider.GEMINI
    assert decision.direction is Direction.LONG
