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


@pytest.mark.asyncio
async def test_operational_health_uses_bounded_sanitized_queries_only():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/market_ai_analyses"):
            return httpx.Response(
                200,
                json=[
                    {
                        "status": "SUCCESS",
                        "error_code": None,
                        "latency_ms": 2200,
                        "provider": "GEMINI",
                        "model": "gemini-test",
                        "timeframe": "15m",
                        "created_at": "2026-09-10T00:00:00+00:00",
                    }
                ] * 20,
            )
        if request.url.path.endswith("/market_scanner_runs"):
            return httpx.Response(200, json=[{"failure_count": 0}] * 20)
        raise AssertionError(f"unexpected path: {request.url.path}")

    async with SupabaseAIAnalysisRepository(
        supabase_url="https://project.supabase.co",
        api_key="anon-key",
        transport=httpx.MockTransport(handler),
    ) as repo:
        snapshot = await repo.operational_health("15m", 20)

    assert snapshot.attempts == 20
    assert snapshot.successes == 20
    assert snapshot.can_expand is True
    analysis_request, scanner_request = requests
    assert analysis_request.url.params["limit"] == "20"
    assert analysis_request.url.params["select"] == (
        "status,error_code,latency_ms,provider,model,timeframe,created_at"
    )
    assert "input_snapshot" not in analysis_request.url.params["select"]
    assert "error_message" not in analysis_request.url.params["select"]
    assert scanner_request.url.params["select"] == "failure_count"
    assert scanner_request.url.params["limit"] == "20"


@pytest.mark.asyncio
async def test_operational_health_rejects_an_unbounded_window():
    async with SupabaseAIAnalysisRepository(
        supabase_url="https://project.supabase.co",
        api_key="anon-key",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    ) as repo:
        with pytest.raises(ValueError, match="between 20 and 200"):
            await repo.operational_health("15m", 201)


@pytest.mark.asyncio
async def test_operational_health_degrades_from_newest_twenty_attempts_only():
    """Older successful rows must not mask a current rolling-canary failure."""
    newest_rows = [
        {
            "status": "FAILED",
            "error_code": "TIMEOUT",
            "latency_ms": 2000,
            "provider": "GEMINI",
            "model": "gemini-test",
            "timeframe": "15m",
            "created_at": "2026-09-10T00:20:00+00:00",
        }
    ] * 3 + [
        {
            "status": "SUCCESS",
            "error_code": None,
            "latency_ms": 2000,
            "provider": "GEMINI",
            "model": "gemini-test",
            "timeframe": "15m",
            "created_at": "2026-09-10T00:19:00+00:00",
        }
    ] * 17
    older_success_rows = [
        {
            "status": "SUCCESS",
            "error_code": None,
            "latency_ms": 2000,
            "provider": "GEMINI",
            "model": "gemini-test",
            "timeframe": "15m",
            "created_at": "2026-09-09T00:00:00+00:00",
        }
    ] * 180

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/market_ai_analyses"):
            return httpx.Response(200, json=newest_rows + older_success_rows)
        if request.url.path.endswith("/market_scanner_runs"):
            return httpx.Response(200, json=[{"failure_count": 0}] * 20)
        raise AssertionError(f"unexpected path: {request.url.path}")

    async with SupabaseAIAnalysisRepository(
        supabase_url="https://project.supabase.co",
        api_key="anon-key",
        transport=httpx.MockTransport(handler),
    ) as repo:
        snapshot = await repo.operational_health("15m", 200)

    assert snapshot.attempts == 20
    assert snapshot.successes == 17
    assert snapshot.status == "DEGRADED"
    assert snapshot.can_expand is False
