from datetime import datetime, timezone
import httpx
import pytest

from btc_core.strategy.outcomes import SignalOutcome
from btc_core.strategy.repository import SupabaseStrategyRepository


@pytest.mark.asyncio
async def test_upsert_is_idempotent_and_scoped_to_horizon_conflict():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(201, json=[])
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(handler)) as repo:
        await repo.upsert_outcome(analysis_id=1, scanner_candidate_id=2, symbol="btcusdt", timeframe="15m", direction="LONG", horizon="1H", signal_created_at=now, evaluation_due_at=now, outcome=SignalOutcome(outcome="NO_FILL", data_quality="FULL"))
    assert requests[0].url.params["on_conflict"] == "ai_analysis_id,horizon"
    assert requests[0].headers["prefer"].startswith("resolution=merge-duplicates")
    assert requests[0].content.decode().find("BTCUSDT") >= 0


@pytest.mark.asyncio
async def test_candles_query_is_exact_and_fallback_is_bounded_public_callback():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[])
    called = []
    async def fallback(symbol, timeframe, start, end, limit):
        called.append((symbol, timeframe, limit)); return []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(handler)) as repo:
        await repo.candles("btcusdt", "1m", start, start, fallback=fallback)
    assert requests[0].url.params["symbol"] == "eq.BTCUSDT"
    assert requests[0].url.params["timeframe"] == "eq.1m"
    assert called == [("BTCUSDT", "1m", 1500)]
