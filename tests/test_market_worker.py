from datetime import datetime, timezone

import pytest

from btc_core.ai.models import Direction
from btc_core.market.realtime import RealtimeMarketEvent
from btc_core.market.scanner import MarketScanResult, MarketScannerCandidate
from btc_core.scanner.scoring import OpportunityInputs
from services.market_worker.app.main import run_realtime_cycle


class FakeScanner:
    async def scan(self, *, timeframe: str, universe_limit: int, candidate_limit: int):
        return MarketScanResult(
            timeframe=timeframe,
            universe_size=2,
            candidates=[
                MarketScannerCandidate(
                    rank=1,
                    symbol="PUMPUSDT",
                    timeframe=timeframe,
                    direction=Direction.LONG,
                    opportunity_score=80,
                    directional_signal=0.5,
                    components=OpportunityInputs(
                        technical=80, momentum=80, volume=80, order_flow=80,
                        open_interest=80, funding=80, liquidity=80, news=50, macro=50, risk_reward=50,
                    ),
                    last_price=0.004,
                    quote_volume_24h=1_000_000,
                    funding_rate=0.0001,
                    open_interest_change_percent=1,
                    long_short_ratio=1,
                    spread_percent=0.01,
                )
            ],
            failures=[],
        )


class FakeRepo:
    def __init__(self):
        self.scans = []
        self.states = []
        self.candles = []

    async def persist_scan(self, result):
        self.scans.append(result)
        return "run-id"

    async def upsert_live_states(self, states):
        self.states.append(states)

    async def upsert_candle(self, candle):
        self.candles.append(candle)


class FakeRealtime:
    async def events(self, symbols, timeframe, *, run_seconds):
        assert symbols == ["PUMPUSDT", "BTCUSDT", "SOLUSDT", "XRPUSDT", "ETHUSDT"]
        assert timeframe == "15m"
        yield RealtimeMarketEvent(
            kind="MARK_PRICE",
            symbol="BTCUSDT",
            event_time=datetime(2026, 9, 8, tzinfo=timezone.utc),
            mark_price=62100,
            index_price=62090,
            funding_rate=0.0001,
        )


@pytest.mark.asyncio
async def test_run_realtime_cycle_tracks_core_symbols_beyond_scanner_quota():
    repo = FakeRepo()
    result = await run_realtime_cycle(
        scanner=FakeScanner(),
        repo=repo,
        realtime=FakeRealtime(),
        timeframe="15m",
        universe_limit=30,
        candidate_limit=10,
        realtime_symbol_limit=5,
        realtime_seconds=10,
        flush_interval_seconds=2,
    )

    assert result.candidates[0].symbol == "PUMPUSDT"
    assert len(repo.scans) == 1
    assert len(repo.states) == 1
    assert repo.states[0][0].symbol == "BTCUSDT"
    assert repo.states[0][0].mark_price == 62100
