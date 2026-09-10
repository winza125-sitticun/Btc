import json

import httpx
import pytest

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.supabase_repo import MarketAIAnalysisRecord, SupabaseAIAnalysisRepository


@pytest.mark.asyncio
async def test_ai_persist_sanitizes_secret_like_snapshot_fields_and_bounds_error_text():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=[])

    record = MarketAIAnalysisRecord(
        scanner_candidate_id=901,
        run_id="7f165e32-357b-431a-82f0-4a8ab25cbf76",
        symbol="BTCUSDT",
        timeframe="15m",
        provider=AIProvider.GEMINI,
        model="gemini-test",
        scanner_direction=Direction.LONG,
        ai_direction=None,
        status="FAILED",
        input_snapshot={
            "symbol": "BTCUSDT",
            "authorization": "Bearer known-secret-value",
            "nested": {"api_key": "known-secret-value", "safe": 1},
        },
        attempt_count=1,
        error_code="AUTH",
        error_message="x" * 900,
    )

    async with SupabaseAIAnalysisRepository(
        supabase_url="https://project.supabase.co",
        api_key="service-role",
        transport=httpx.MockTransport(handler),
    ) as repo:
        await repo.persist(record)

    assert len(requests) == 1
    request = requests[0]
    assert request.url.path.endswith("/market_ai_analyses")
    assert request.url.params["on_conflict"] == "scanner_candidate_id,provider,model"
    assert "resolution=merge-duplicates" in request.headers["prefer"]
    payload = json.loads(request.content)
    serialized = json.dumps(payload).lower()
    assert "known-secret-value" not in serialized
    assert "authorization" not in serialized
    assert "api_key" not in serialized
    assert payload["input_snapshot"]["nested"]["safe"] == 1
    assert len(payload["error_message"]) == 500


@pytest.mark.asyncio
async def test_ai_latest_selects_explicit_safe_columns_only():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    async with SupabaseAIAnalysisRepository(
        supabase_url="https://project.supabase.co",
        api_key="anon-key",
        transport=httpx.MockTransport(handler),
    ) as repo:
        rows = await repo.latest("15m", 10)

    assert rows == []
    params = requests[0].url.params
    assert params["timeframe"] == "eq.15m"
    assert params["limit"] == "10"
    assert params["select"] != "*"
    assert "input_snapshot" not in params["select"]
    assert "error_message" not in params["select"]
    assert "scanner_candidate_id" in params["select"]
    assert "risk_precheck_status" in params["select"]
