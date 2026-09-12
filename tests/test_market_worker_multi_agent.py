from datetime import datetime, timezone

import pytest

from btc_core.ai.models import Direction
from btc_core.market.scanner import MarketScanResult, MarketScannerCandidate
from btc_core.market.supabase_repo import PersistedCandidateRef, PersistedScanRef
from btc_core.scanner.scoring import OpportunityInputs
from services.market_worker.app.main import run_realtime_cycle


def _candidate() -> MarketScannerCandidate:
    return MarketScannerCandidate(
        rank=1, symbol="BTCUSDT", timeframe="15m", direction=Direction.LONG,
        opportunity_score=80, directional_signal=0.5,
        components=OpportunityInputs(technical=80, momentum=80, volume=80, order_flow=80, open_interest=80, funding=80, liquidity=80, news=80, macro=80, risk_reward=80),
        last_price=62000, quote_volume_24h=1_000_000, funding_rate=0.0001,
        open_interest_change_percent=1, long_short_ratio=1.2, spread_percent=0.01,
    )


class Scanner:
    async def scan(self, *, timeframe, universe_limit, candidate_limit):
        return MarketScanResult(timeframe=timeframe, universe_size=1, candidates=[_candidate()], failures=[])


class Repo:
    async def persist_scan(self, result):
        return PersistedScanRef(
            run_id="22222222-2222-4222-8222-222222222222",
            candidates=(PersistedCandidateRef(id=1, rank=1, symbol="BTCUSDT"),),
        )

    async def upsert_live_states(self, states):
        pass

    async def upsert_candle(self, candle):
        pass


class Realtime:
    async def events(self, symbols, timeframe, *, run_seconds):
        if False:
            yield None


class FailingMultiAgentRunner:
    def __init__(self):
        self.called = False

    async def analyze_scan(self, result, persisted_scan):
        self.called = True
        raise RuntimeError("multi-agent failed")


@pytest.mark.asyncio
async def test_multi_agent_runner_is_started_from_scanner_cycle_and_failure_is_isolated():
    runner = FailingMultiAgentRunner()
    result = await run_realtime_cycle(
        scanner=Scanner(), repo=Repo(), realtime=Realtime(), timeframe="15m",
        universe_limit=30, candidate_limit=10, realtime_symbol_limit=5,
        realtime_seconds=1, flush_interval_seconds=1,
        multi_agent_runner=runner,
    )

    assert runner.called is True
    assert result.candidates[0].symbol == "BTCUSDT"
