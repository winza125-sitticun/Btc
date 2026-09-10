import json

import httpx
import pytest

from btc_core.ai.analysis import AIAnalysisSnapshot, AINewsContext, TimeframeTechnicalContext
from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.providers.base import AIProviderError, AIProviderRuntimeConfig
from btc_core.ai.providers.openai_compatible import OpenAICompatibleProviderClient
from btc_core.scanner.scoring import OpportunityInputs


def make_snapshot() -> AIAnalysisSnapshot:
    contexts = {
        timeframe: TimeframeTechnicalContext(
            timeframe=timeframe,
            close=100,
            trend_percent=1.0,
            momentum_percent=0.5,
            recent_high=102,
            recent_low=98,
            recent_volume_ratio=1.2,
            direction=Direction.LONG,
        )
        for timeframe in ("4h", "1h", "15m")
    }
    return AIAnalysisSnapshot(
        symbol="BTCUSDT",
        timeframe="15m",
        scanner_direction=Direction.LONG,
        opportunity_score=82,
        components=OpportunityInputs(
            technical=80,
            momentum=80,
            volume=80,
            order_flow=80,
            open_interest=80,
            funding=80,
            liquidity=80,
            news=58,
            macro=50,
            risk_reward=50,
        ),
        last_price=100,
        funding_rate=0.0001,
        open_interest_change_percent=2,
        long_short_ratio=1.1,
        spread_percent=0.01,
        technical_by_timeframe=contexts,
        news=AINewsContext(score=58),
    )


def valid_content() -> str:
    return json.dumps(
        {
            "provider": "DEEPSEEK",
            "model": "deepseek-test",
            "symbol": "BTCUSDT",
            "timeframe": "15m",
            "direction": "LONG",
            "confidence": 83,
            "entry_min": 99,
            "entry_max": 100,
            "stop_loss": 96,
            "take_profits": [104, 108],
            "risk_reward": 2.5,
            "reason_summary": "Trend, momentum and order flow agree.",
        }
    )


def config(**updates) -> AIProviderRuntimeConfig:
    data = dict(
        provider=AIProvider.DEEPSEEK,
        model="deepseek-test",
        api_key="super-secret-key",
        base_url="https://api.example.test/v1",
        timeout_seconds=20,
        max_retries=1,
    )
    data.update(updates)
    return AIProviderRuntimeConfig(**data)


@pytest.mark.asyncio
async def test_openai_compatible_parses_valid_json_and_sends_json_mode():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer super-secret-key"
        assert body["model"] == "deepseek-test"
        assert body["response_format"] == {"type": "json_object"}
        assert "json" in body["messages"][0]["content"].lower()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": valid_content()}}]},
        )

    async with OpenAICompatibleProviderClient(
        config(), transport=httpx.MockTransport(handler)
    ) as client:
        decision = await client.analyze(make_snapshot())

    assert len(requests) == 1
    assert decision.provider is AIProvider.DEEPSEEK
    assert decision.model == "deepseek-test"
    assert decision.symbol == "BTCUSDT"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}), "INVALID_JSON"),
        (
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps({"direction": "LONG"})}}]},
            ),
            "INVALID_SCHEMA",
        ),
    ],
)
async def test_openai_compatible_invalid_output_is_not_retried(response, expected_code):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return response

    async with OpenAICompatibleProviderClient(
        config(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AIProviderError) as exc_info:
            await client.analyze(make_snapshot())

    assert exc_info.value.code == expected_code
    assert attempts == 1
    assert "super-secret-key" not in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(("status_code", "expected_code"), [(429, "RATE_LIMIT"), (500, "UPSTREAM_5XX")])
async def test_openai_compatible_transient_http_failures_retry_once(status_code, expected_code):
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(status_code, json={"error": "temporary"})
        return httpx.Response(200, json={"choices": [{"message": {"content": valid_content()}}]})

    async with OpenAICompatibleProviderClient(
        config(), transport=httpx.MockTransport(handler)
    ) as client:
        decision = await client.analyze(make_snapshot())

    assert attempts == 2
    assert decision.direction is Direction.LONG


@pytest.mark.asyncio
async def test_openai_compatible_timeout_retries_once_then_succeeds():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": valid_content()}}]})

    async with OpenAICompatibleProviderClient(
        config(), transport=httpx.MockTransport(handler)
    ) as client:
        decision = await client.analyze(make_snapshot())

    assert attempts == 2
    assert decision.confidence == 83


@pytest.mark.asyncio
async def test_openai_compatible_auth_error_is_not_retried_or_leaked():
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"error": "bad key super-secret-key"})

    async with OpenAICompatibleProviderClient(
        config(), transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(AIProviderError) as exc_info:
            await client.analyze(make_snapshot())

    assert attempts == 1
    assert exc_info.value.code == "AUTH"
    assert "super-secret-key" not in str(exc_info.value)
