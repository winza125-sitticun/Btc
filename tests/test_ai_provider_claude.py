import json

import httpx
import pytest

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.providers.base import AIProviderRuntimeConfig
from btc_core.ai.providers.claude import ClaudeProviderClient
from tests.test_ai_provider_openai_compatible import make_snapshot


def config() -> AIProviderRuntimeConfig:
    return AIProviderRuntimeConfig(
        provider=AIProvider.CLAUDE,
        model="claude-test",
        api_key="claude-secret",
        base_url="https://api.anthropic.com",
    )


@pytest.mark.asyncio
async def test_claude_messages_uses_headers_model_and_structured_json():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "claude-secret"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert body["model"] == "claude-test"
        assert 1 <= body["max_tokens"] <= 2048
        output_format = body["output_config"]["format"]
        assert output_format["type"] == "json_schema"
        assert "direction" in output_format["schema"]["properties"]
        return httpx.Response(
            200,
            json={
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "provider": "CLAUDE",
                                "model": "claude-test",
                                "symbol": "BTCUSDT",
                                "timeframe": "15m",
                                "direction": "SHORT",
                                "confidence": 81,
                                "entry_min": 100,
                                "entry_max": 101,
                                "stop_loss": 104,
                                "take_profits": [98, 95],
                                "risk_reward": 2.2,
                                "reason_summary": "Bearish structure.",
                            }
                        ),
                    }
                ]
            },
        )

    async with ClaudeProviderClient(config(), transport=httpx.MockTransport(handler)) as client:
        decision = await client.analyze(make_snapshot())

    assert len(requests) == 1
    assert decision.provider is AIProvider.CLAUDE
    assert decision.direction is Direction.SHORT
