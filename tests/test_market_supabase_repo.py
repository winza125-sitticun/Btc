import json

import httpx
import pytest

from btc_core.ai.models import Direction
from btc_core.market.scanner import MarketScanResult, MarketScannerCandidate
from btc_core.market.supabase_repo import PersistedScanRef, SupabaseMarketRepository
from btc_core.scanner.scoring import OpportunityInputs


def candidate(symbol: str = "BTCUSDT") -> MarketScannerCandidate:
    return MarketScannerCandidate(
        rank=1,
        symbol=symbol,
        timeframe="15m",
        direction=Direction.LONG,
        opportunity_score=82,
        directional_signal=0.5,
        components=OpportunityInputs(
            technical=80, momentum=80, volume=80, order_flow=80,
            open_interest=80, funding=80, liquidity=80, news=58,
            macro=50, risk_reward=50,
        ),
        last_price=100,
        quote_volume_24h=1_000_000,
        funding_rate=0.0001,
        open_interest_change_percent=2,
        long_short_ratio=1.1,
        spread_percent=0.01,
        market_only=False,
    )


@pytest.mark.asyncio
async def test_persist_scan_returns_real_candidate_ids_from_postgrest():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/market_scanner_runs"):
            return httpx.Response(201, json=[{"id": "run-123"}])
        if request.url.path.endswith("/market_scanner_candidates"):
            assert request.headers["prefer"] == "return=representation"
            payload = json.loads(request.content)
            assert payload[0]["symbol"] == "BTCUSDT"
            return httpx.Response(201, json=[{"id": 901, "rank": 1, "symbol": "BTCUSDT"}])
        raise AssertionError(request.url)

    result = MarketScanResult(
        timeframe="15m", universe_size=1, candidates=[candidate()], failures=[]
    )
    async with SupabaseMarketRepository(
        supabase_url="https://project.supabase.co",
        api_key="server-key",
        transport=httpx.MockTransport(handler),
    ) as repo:
        persisted = await repo.persist_scan(result)

    assert isinstance(persisted, PersistedScanRef)
    assert persisted.run_id == "run-123"
    assert len(persisted.candidates) == 1
    assert persisted.candidates[0].id == 901
    assert persisted.candidates[0].rank == 1
    assert persisted.candidates[0].symbol == "BTCUSDT"
