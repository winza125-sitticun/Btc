import asyncio
from datetime import datetime, timezone

import pytest

from btc_core.ai.models import Direction
from btc_core.market.realtime import RealtimeMarketEvent
from btc_core.market.scanner import MarketScanResult, MarketScannerCandidate
from btc_core.market.supabase_repo import PersistedCandidateRef, PersistedScanRef
from btc_core.scanner.scoring import OpportunityInputs
from services.market_worker.app.main import _env_flag, run_realtime_cycle


def make_candidate(symbol: str, timeframe: str) -> MarketScannerCandidate:
    return MarketScannerCandidate(
        rank=1,
        symbol=symbol,
        timeframe=timeframe,
        direction=Direction.LONG,
        opportunity_score=80,
        directional_signal=0.5,
        components=OpportunityInputs(
            technical=80, momentum=80, volume=80, order_flow=80,
            open_interest=80, funding=80, liquidity=80, news=50, macro=50, risk_reward=50,
        ),
        last_price=0.004 if symbol == "PUMPUSDT" else 62000,
        quote_volume_24h=1_000_000,
        funding_rate=0.0001,
        open_interest_change_percent=1,
        long_short_ratio=1,
        spread_percent=0.01,
    )


class FakeScanner:
    def __init__(self, symbol: str = "PUMPUSDT"):
        self.symbol = symbol

    async def scan(self, *, timeframe: str, universe_limit: int, candidate_limit: int):
        return MarketScanResult(
            timeframe=timeframe,
            universe_size=2,
            candidates=[make_candidate(self.symbol, timeframe)],
            failures=[],
        )


class FakeRepo:
    def __init__(self):
        self.scans = []
        self.states = []
        self.candles = []

    async def persist_scan(self, result):
        self.scans.append(result)
        item = result.candidates[0]
        return PersistedScanRef(
            run_id="run-id",
            candidates=(PersistedCandidateRef(id=1, rank=item.rank, symbol=item.symbol),),
        )

    async def upsert_live_states(self, states):
        self.states.append(states)

    async def upsert_candle(self, candle):
        self.candles.append(candle)


class FakeRealtime:
    def __init__(self, expected_symbols):
        self.expected_symbols = expected_symbols

    async def events(self, symbols, timeframe, *, run_seconds):
        assert symbols == self.expected_symbols
        assert timeframe == "15m"
        yield RealtimeMarketEvent(
            kind="MARK_PRICE",
            symbol="BTCUSDT",
            event_time=datetime(2026, 9, 8, tzinfo=timezone.utc),
            mark_price=62100,
            index_price=62090,
            funding_rate=0.0001,
        )


def test_news_enrichment_feature_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("NEWS_ENRICHMENT_V1_ENABLED", raising=False)
    assert _env_flag("NEWS_ENRICHMENT_V1_ENABLED", False) is False

    for enabled_value in ("true", "1", "on", "yes", " TRUE "):
        monkeypatch.setenv("NEWS_ENRICHMENT_V1_ENABLED", enabled_value)
        assert _env_flag("NEWS_ENRICHMENT_V1_ENABLED", False) is True

    monkeypatch.setenv("NEWS_ENRICHMENT_V1_ENABLED", "false")
    assert _env_flag("NEWS_ENRICHMENT_V1_ENABLED", False) is False


def test_ai_analysis_feature_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("AI_ANALYSIS_V1_ENABLED", raising=False)
    assert _env_flag("AI_ANALYSIS_V1_ENABLED", False) is False


@pytest.mark.asyncio
async def test_run_realtime_cycle_tracks_core_symbols_beyond_scanner_quota():
    repo = FakeRepo()
    result = await run_realtime_cycle(
        scanner=FakeScanner("PUMPUSDT"),
        repo=repo,
        realtime=FakeRealtime(["PUMPUSDT", "BTCUSDT", "SOLUSDT", "XRPUSDT", "ETHUSDT"]),
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


@pytest.mark.asyncio
async def test_run_realtime_cycle_deduplicates_core_symbol_already_in_scanner():
    repo = FakeRepo()
    await run_realtime_cycle(
        scanner=FakeScanner("BTCUSDT"),
        repo=repo,
        realtime=FakeRealtime(["BTCUSDT", "SOLUSDT", "XRPUSDT", "ETHUSDT"]),
        timeframe="15m",
        universe_limit=30,
        candidate_limit=10,
        realtime_symbol_limit=5,
        realtime_seconds=10,
        flush_interval_seconds=2,
    )


@pytest.mark.asyncio
async def test_realtime_starts_without_waiting_for_ai_analysis():
    ai_started = asyncio.Event()
    allow_ai_finish = asyncio.Event()
    realtime_started = asyncio.Event()

    class SlowAIRunner:
        async def analyze_scan(self, result, persisted_scan):
            ai_started.set()
            await allow_ai_finish.wait()

    class ObservableRealtime:
        async def events(self, symbols, timeframe, *, run_seconds):
            realtime_started.set()
            if False:
                yield None

    task = asyncio.create_task(
        run_realtime_cycle(
            scanner=FakeScanner("BTCUSDT"),
            repo=FakeRepo(),
            realtime=ObservableRealtime(),
            timeframe="15m",
            universe_limit=30,
            candidate_limit=10,
            realtime_symbol_limit=5,
            realtime_seconds=10,
            flush_interval_seconds=2,
            ai_runner=SlowAIRunner(),
        )
    )
    await asyncio.wait_for(ai_started.wait(), timeout=0.2)
    await asyncio.wait_for(realtime_started.wait(), timeout=0.2)
    assert not task.done()
    allow_ai_finish.set()
    await task


@pytest.mark.asyncio
async def test_ai_runner_failure_does_not_fail_realtime_cycle():
    class FailingAIRunner:
        async def analyze_scan(self, result, persisted_scan):
            raise RuntimeError("AI failed")

    class EmptyRealtime:
        async def events(self, symbols, timeframe, *, run_seconds):
            if False:
                yield None

    result = await run_realtime_cycle(
        scanner=FakeScanner("BTCUSDT"),
        repo=FakeRepo(),
        realtime=EmptyRealtime(),
        timeframe="15m",
        universe_limit=30,
        candidate_limit=10,
        realtime_symbol_limit=5,
        realtime_seconds=10,
        flush_interval_seconds=2,
        ai_runner=FailingAIRunner(),
    )
    assert result.candidates[0].symbol == "BTCUSDT"
