from datetime import datetime, timezone
import httpx
import pytest

from btc_core.strategy.outcomes import SignalOutcome
from btc_core.strategy.repository import PublicBinanceKlinesFetcher, SupabaseStrategyRepository


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
        await repo.candles("btcusdt", "1m", start, start, public_binance_klines=PublicBinanceKlinesFetcher(fallback))
    assert requests[0].url.params["symbol"] == "eq.BTCUSDT"
    assert requests[0].url.params["timeframe"] == "eq.1m"
    assert called == [("BTCUSDT", "1m", 1500)]

@pytest.mark.asyncio
async def test_partial_persisted_coverage_uses_fallback_and_discovery_scopes_success():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("market_candles"):
            return httpx.Response(200, json=[{"open_time":"2026-01-01T00:00:00+00:00","close_time":"2026-01-01T00:01:00+00:00","open":1,"high":2,"low":1,"close":2}])
        return httpx.Response(200, json=[{"id":1,"market_ai_signal_outcomes":[{"horizon":"1H"}]}])
    async def fallback(*args): return []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(handler)) as repo:
        await repo.candles("BTCUSDT", "1m", start, start + __import__('datetime').timedelta(hours=1), public_binance_klines=PublicBinanceKlinesFetcher(fallback))
        await repo.analyses_missing_outcomes()
    assert requests[0].url.path.endswith("market_candles") and len(requests) == 2
    assert requests[-1].url.params["status"] == "eq.SUCCESS"

@pytest.mark.asyncio
async def test_untrusted_fallback_callback_is_rejected():
    async def private_fetch(*args): return []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))) as repo:
        with pytest.raises(ValueError, match="public_binance"):
            await repo.candles("BTCUSDT", "1m", start, start, fallback=private_fetch)
