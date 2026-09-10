from datetime import datetime, timezone

import httpx
import pytest

from btc_core.ai.models import Direction
from btc_core.market.realtime import LiveMarketState
from btc_core.market.scanner import MarketScanResult, MarketScannerCandidate
from btc_core.market.supabase_repo import PersistedScanRef, SupabaseMarketRepository
from btc_core.scanner.scoring import OpportunityInputs


@pytest.mark.asyncio
async def test_persist_scan_creates_system_run_and_candidates():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/market_scanner_runs"):
            return httpx.Response(201, json=[{"id": "11111111-1111-1111-1111-111111111111"}])
        if request.url.path.endswith("/market_scanner_candidates"):
            return httpx.Response(201, json=[{"id": 77, "rank": 1, "symbol": "BTCUSDT"}])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    repo = SupabaseMarketRepository(
        supabase_url="https://demo.supabase.co",
        api_key="service-key",
        transport=transport,
    )
    candidate = MarketScannerCandidate(
        rank=1,
        symbol="BTCUSDT",
        timeframe="15m",
        direction=Direction.LONG,
        opportunity_score=82,
        directional_signal=0.6,
        components=OpportunityInputs(
            technical=80, momentum=75, volume=90, order_flow=70,
            open_interest=65, funding=88, liquidity=95, news=50, macro=50, risk_reward=50,
        ),
        last_price=62000,
        quote_volume_24h=1_000_000_000,
        funding_rate=0.0001,
        open_interest_change_percent=2.1,
        long_short_ratio=1.1,
        spread_percent=0.01,
    )
    result = MarketScanResult(timeframe="15m", universe_size=30, candidates=[candidate], failures=[])

    persisted = await repo.persist_scan(result)
    await repo.aclose()

    assert isinstance(persisted, PersistedScanRef)
    assert persisted.run_id == "11111111-1111-1111-1111-111111111111"
    assert persisted.candidates[0].id == 77
    assert requests[0].headers["authorization"] == "Bearer service-key"
    assert requests[0].url.path.endswith("/rest/v1/market_scanner_runs")
    assert requests[1].url.path.endswith("/rest/v1/market_scanner_candidates")
    assert requests[1].headers["prefer"] == "return=representation"
    assert b'"symbol":"BTCUSDT"' in requests[1].content


@pytest.mark.asyncio
async def test_upsert_live_states_uses_symbol_conflict_key():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=[])

    repo = SupabaseMarketRepository(
        supabase_url="https://demo.supabase.co",
        api_key="service-key",
        transport=httpx.MockTransport(handler),
    )
    state = LiveMarketState(
        symbol="SOLUSDT",
        mark_price=150,
        index_price=149.9,
        funding_rate=0.0002,
        best_bid=149.9,
        best_ask=150.1,
        spread_percent=0.133333,
        candle_timeframe="15m",
        candle_open=148,
        candle_high=151,
        candle_low=147,
        candle_close=150,
        candle_volume=1234,
        event_time=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    await repo.upsert_live_states([state])
    await repo.aclose()

    request = requests[0]
    assert request.url.path.endswith("/rest/v1/market_live_state")
    assert request.url.params["on_conflict"] == "symbol"
    assert "resolution=merge-duplicates" in request.headers["prefer"]


@pytest.mark.asyncio
async def test_upsert_live_states_refreshes_updated_at():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=[])

    repo = SupabaseMarketRepository(
        supabase_url="https://demo.supabase.co",
        api_key="service-key",
        transport=httpx.MockTransport(handler),
    )
    state = LiveMarketState(
        symbol="BTCUSDT",
        mark_price=62000,
        index_price=61990,
        funding_rate=0.0001,
        best_bid=61999,
        best_ask=62001,
        spread_percent=0.003226,
        event_time=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    await repo.upsert_live_states([state])
    await repo.aclose()

    payload = __import__("json").loads(requests[0].content)
    assert payload[0]["updated_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_upsert_candle_preserves_full_taker_volume_and_close_time():
    from btc_core.market.models import Candle

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=[])

    repo = SupabaseMarketRepository(
        supabase_url="https://demo.supabase.co",
        api_key="service-key",
        transport=httpx.MockTransport(handler),
    )
    candle = Candle(
        symbol="BTCUSDT",
        timeframe="15m",
        open_time=datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc),
        close_time=datetime(2026, 9, 8, 2, 14, 59, tzinfo=timezone.utc),
        open=62000,
        high=62100,
        low=61900,
        close=62050,
        volume=100,
        quote_volume=6_205_000,
        trade_count=1234,
        taker_buy_base_volume=55,
        taker_buy_quote_volume=3_412_750,
    )

    await repo.upsert_candle(candle)
    await repo.aclose()

    payload = __import__("json").loads(requests[0].content)
    assert payload["taker_buy_base_volume"] == 55
    assert payload["taker_buy_quote_volume"] == 3_412_750
    assert payload["close_time"] == "2026-09-08T02:14:59Z"
