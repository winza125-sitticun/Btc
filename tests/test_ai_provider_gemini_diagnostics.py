import json

import httpx
import pytest

from btc_core.ai.models import AIProvider
from btc_core.ai.providers.base import AIProviderError, AIProviderRuntimeConfig
from btc_core.ai.providers.gemini import GeminiProviderClient
from tests.test_ai_provider_openai_compatible import make_snapshot


def _config() -> AIProviderRuntimeConfig:
    return AIProviderRuntimeConfig(
        provider=AIProvider.GEMINI,
        model="gemini-3.5-flash-lite",
        api_key="test-key",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        max_retries=0,
    )


@pytest.mark.asyncio
async def test_invalid_actionable_geometry_has_safe_diagnostic_code():
    marker = "RAW_SENTINEL_123"
    invalid_decision = {
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "direction": "LONG",
        "confidence": 80,
        "reason_summary": marker,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "int_invalid_geometry",
                "status": "completed",
                "steps": [
                    {
                        "type": "model_output",
                        "status": "done",
                        "content": [
                            {"type": "text", "text": json.dumps(invalid_decision)}
                        ],
                    }
                ],
                "object": "interaction",
                "model": "gemini-3.5-flash-lite",
            },
        )

    async with GeminiProviderClient(_config(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AIProviderError) as captured:
            await client.analyze(make_snapshot())

    assert captured.value.code == "INVALID_SCHEMA_GEOMETRY"
    assert "geometry" in str(captured.value).lower()
    assert marker not in str(captured.value)
    assert "BTCUSDT" not in str(captured.value)
