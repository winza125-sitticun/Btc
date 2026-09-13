import json

import httpx
import pytest

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.providers.base import AIProviderRuntimeConfig
from btc_core.ai.providers.gemini import GeminiProviderClient
from tests.test_ai_provider_openai_compatible import make_snapshot


def _config(*, max_retries: int) -> AIProviderRuntimeConfig:
    return AIProviderRuntimeConfig(
        provider=AIProvider.GEMINI,
        model="gemini-3.5-flash-lite",
        api_key="gemini-secret",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds=20,
        max_retries=max_retries,
    )


def _interaction(decision: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "int_test",
            "status": "completed",
            "steps": [
                {
                    "type": "model_output",
                    "status": "done",
                    "content": [{"type": "text", "text": json.dumps(decision)}],
                }
            ],
            "object": "interaction",
            "model": "gemini-3.5-flash-lite",
        },
    )


@pytest.mark.asyncio
async def test_gemini_interaction_retries_one_schema_invalid_output_when_retry_budget_allows():
    requests: list[httpx.Request] = []
    invalid = {
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "direction": "SHORT",
        "confidence": 78,
        "entry_min": 100,
        "entry_max": 101,
        "stop_loss": 104,
        "take_profits": [96, 92],
        # risk_reward intentionally missing to reproduce schema validation failure.
        "reason_summary": "Risk review output missing one required field.",
    }
    valid = {
        **invalid,
        "risk_reward": 2.0,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _interaction(invalid if len(requests) == 1 else valid)

    async with GeminiProviderClient(
        _config(max_retries=1), transport=httpx.MockTransport(handler)
    ) as client:
        result = await client.analyze(make_snapshot())

    assert len(requests) == 2
    assert result.provider is AIProvider.GEMINI
    assert result.model == "gemini-3.5-flash-lite"
    assert result.direction is Direction.SHORT
    assert result.risk_reward == 2.0
