import json

import httpx
import pytest

from btc_core.ai.models import AIProvider
from btc_core.ai.providers.base import AIProviderError, AIProviderRuntimeConfig
from btc_core.ai.providers.gemini import GeminiProviderClient
from btc_core.ai.validation_diagnostics import safe_provider_error_code
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
@pytest.mark.parametrize(
    ("invalid_decision", "expected_code"),
    [
        (
            {
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "direction": "LONG",
                "confidence": 80,
            },
            "INVALID_SCHEMA_GEOMETRY_MISSING",
        ),
        (
            {
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "direction": "LONG",
                "confidence": 80,
                "entry_min": 0,
                "entry_max": 100,
                "stop_loss": 95,
                "take_profits": [110],
                "risk_reward": 2,
            },
            "INVALID_SCHEMA_GEOMETRY_NON_POSITIVE",
        ),
        (
            {
                "symbol": "BTCUSDT",
                "timeframe": "15m",
                "direction": "LONG",
                "confidence": 80,
                "entry_min": 101,
                "entry_max": 100,
                "stop_loss": 95,
                "take_profits": [110],
                "risk_reward": 2,
            },
            "INVALID_SCHEMA_GEOMETRY_ENTRY_RANGE",
        ),
    ],
)
async def test_invalid_actionable_geometry_has_safe_specific_diagnostic_code(
    invalid_decision: dict[str, object], expected_code: str
):
    marker = "RAW_SENTINEL_123"
    invalid_decision = {**invalid_decision, "reason_summary": marker}

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

    assert captured.value.code == "INVALID_SCHEMA"
    assert safe_provider_error_code(captured.value) == expected_code
    assert marker not in str(captured.value)
    assert marker not in safe_provider_error_code(captured.value)
    assert "BTCUSDT" not in str(captured.value)
