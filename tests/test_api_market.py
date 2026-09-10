import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from services.api.app.main import app, get_ai_reader, get_market_reader


class FakeMarketReader:
    async def latest_candidates(self, timeframe: str, limit: int):
        assert timeframe == "15m"
        assert limit == 5
        return [
            {
                "rank": 1,
                "symbol": "SOLUSDT",
                "timeframe": "15m",
                "direction": "LONG",
                "opportunity_score": 86.4,
                "last_price": 150.25,
                "quote_volume_24h": 500000000,
                "funding_rate": 0.0001,
                "open_interest_change_percent": 2.5,
                "long_short_ratio": 1.08,
                "spread_percent": 0.01,
                "created_at": "2026-09-08T03:00:00+00:00",
            }
        ]

    async def live_states(self, symbols: list[str]):
        assert symbols == ["BTCUSDT", "SOLUSDT"]
        return [{"symbol": "BTCUSDT", "mark_price": 62000, "updated_at": "2026-09-08T03:00:01+00:00"}]


class FakeAIReader:
    async def latest(self, timeframe: str, limit: int):
        assert timeframe == "15m"
        assert limit == 5
        return [
            {
                "scanner_candidate_id": 901,
                "run_id": "11111111-1111-1111-1111-111111111111",
                "symbol": "SOLUSDT",
                "timeframe": "15m",
                "provider": "GEMINI",
                "model": "gemini-test",
                "scanner_direction": "LONG",
                "ai_direction": "LONG",
                "confidence": 84,
                "entry_min": 149,
                "entry_max": 150,
                "stop_loss": 145,
                "take_profits": [155, 160],
                "risk_reward": 2.4,
                "reason_summary": "Trend alignment.",
                "status": "SUCCESS",
                "risk_precheck_status": "FULL_RISK_CONTEXT_PENDING",
                "risk_precheck_reasons": [],
                "latency_ms": 250,
                "attempt_count": 1,
                "error_code": None,
                "created_at": "2026-09-10T05:00:00+00:00",
                "completed_at": "2026-09-10T05:00:01+00:00",
            }
        ]

    async def operational_health(self, timeframe: str, window: int):
        assert timeframe == "15m"
        assert window == 20
        return {
            "attempts": 20,
            "successes": 19,
            "failures": 1,
            "success_rate": 95.0,
            "invalid_response_rate": 0.0,
            "median_latency_ms": 2200,
            "p95_latency_ms": 2200,
            "scanner_failure_rate": 0.0,
            "status": "HEALTHY",
            "can_expand": True,
            "reasons": [],
        }


client = TestClient(app)


def test_latest_scanner_candidates_endpoint_uses_repository():
    app.dependency_overrides[get_market_reader] = lambda: FakeMarketReader()
    try:
        response = client.get("/api/v1/scanner/latest?timeframe=15m&limit=5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["symbol"] == "SOLUSDT"
    assert payload[0]["opportunity_score"] == 86.4


def test_market_live_endpoint_normalizes_symbol_list():
    app.dependency_overrides[get_market_reader] = lambda: FakeMarketReader()
    try:
        response = client.get("/api/v1/market/live?symbols=btcusdt, solusdt")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()[0]["symbol"] == "BTCUSDT"


def test_latest_ai_analysis_endpoint_normalizes_timeframe_and_uses_safe_reader():
    app.dependency_overrides[get_ai_reader] = lambda: FakeAIReader()
    try:
        response = client.get("/api/v1/ai/latest?timeframe=%2015m%20&limit=5")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["symbol"] == "SOLUSDT"
    assert payload[0]["risk_precheck_status"] == "FULL_RISK_CONTEXT_PENDING"
    assert "input_snapshot" not in payload[0]
    assert "error_message" not in payload[0]


def test_performance_health_endpoint_uses_bounded_read_only_ai_reader():
    app.dependency_overrides[get_ai_reader] = lambda: FakeAIReader()
    try:
        response = client.get("/api/v1/performance/health?timeframe=%2015m%20&window=20")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "HEALTHY"
    assert payload["can_expand"] is True
    assert "input_snapshot" not in payload
    assert "error_message" not in payload


def test_performance_health_endpoint_rejects_windows_outside_canary_bounds():
    app.dependency_overrides[get_ai_reader] = lambda: FakeAIReader()
    try:
        response = client.get("/api/v1/performance/health?window=19")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_market_reader_does_not_fallback_to_service_role_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")

    dependency = get_market_reader()
    with pytest.raises(HTTPException) as exc_info:
        await anext(dependency)

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_ai_reader_does_not_fallback_to_service_role_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")

    dependency = get_ai_reader()
    with pytest.raises(HTTPException) as exc_info:
        await anext(dependency)

    assert exc_info.value.status_code == 503
