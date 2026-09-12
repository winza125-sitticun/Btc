from datetime import datetime, timedelta, timezone

import pytest

from btc_core.ai.analysis import AINewsContext, AIAnalysisSnapshot, TimeframeTechnicalContext
from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.market_context import derive_market_context
from btc_core.ai.multi_agent.models import AgentRole, FrozenSnapshotEnvelope
from btc_core.ai.multi_agent.performance import (
    EvaluationHorizon,
    MarketOutcomeBar,
    MarketRegime,
    MultiAgentPerformanceService,
    OutcomeEvaluationCandidate,
)
from btc_core.scanner.scoring import OpportunityInputs

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _envelope(d4h=Direction.LONG, d1h=Direction.SHORT, d15m=Direction.LONG):
    directions = {"4h": d4h, "1h": d1h, "15m": d15m}
    technical = {
        tf: TimeframeTechnicalContext(
            timeframe=tf, close=100, trend_percent=0.2, momentum_percent=0.1,
            recent_high=102, recent_low=98, recent_volume_ratio=1.0, direction=direction,
        )
        for tf, direction in directions.items()
    }
    snapshot = AIAnalysisSnapshot(
        symbol="BTCUSDT", timeframe="15m", scanner_direction=Direction.LONG,
        opportunity_score=80,
        components=OpportunityInputs(
            technical=80, momentum=80, volume=80, order_flow=80, open_interest=80,
            funding=80, liquidity=80, news=80, macro=80, risk_reward=80,
        ),
        last_price=100, funding_rate=0.0001, open_interest_change_percent=1,
        long_short_ratio=1.2, spread_percent=0.01,
        technical_by_timeframe=technical, news=AINewsContext(score=80, stories=()),
    )
    return FrozenSnapshotEnvelope(snapshot_ref="snap-1", observed_at=START, snapshot=snapshot)


def test_market_context_freezes_predecision_regime_from_timeframe_directions():
    assert derive_market_context(_envelope()).predecision_regime == "BULL"
    assert derive_market_context(_envelope(Direction.SHORT, Direction.LONG, Direction.WAIT)).predecision_regime == "SIDEWAYS"
    assert derive_market_context(_envelope(Direction.SHORT, Direction.SHORT, Direction.LONG)).predecision_regime == "BEAR"


class FakeRepo:
    def __init__(self, candidate, bars):
        self.candidate = candidate
        self.bars = tuple(bars)
        self.outcomes = []

    async def list_outcome_evaluation_candidates(self, as_of):
        return (self.candidate,)

    async def load_market_outcome_bars(self, symbol, timeframe, start, end):
        return tuple(
            item for item in self.bars
            if item.symbol == symbol and item.timeframe == timeframe and start <= item.close_time < end
        )

    async def append_outcome(self, outcome):
        self.outcomes.append(outcome)
        return len(self.outcomes)


def _bar(tf, close_time, close=102, high=105, low=95):
    minutes = {"15m": 15, "1h": 60, "4h": 240}[tf]
    return MarketOutcomeBar(
        symbol="BTCUSDT", timeframe=tf,
        open_time=close_time-timedelta(minutes=minutes), close_time=close_time,
        high=high, low=low, close=close,
    )


@pytest.mark.asyncio
async def test_evaluate_mature_outcomes_skips_existing_and_future_horizons():
    candidate = OutcomeEvaluationCandidate(
        multi_agent_run_id="11111111-1111-4111-8111-111111111111",
        agent_attempt_id=7, role=AgentRole.TECHNICAL, provider=AIProvider.GEMINI,
        model="gemini-test", symbol="BTCUSDT", direction=Direction.LONG,
        started_at=START, reference_price=100, market_regime=MarketRegime.BULL,
        existing_horizons=(EvaluationHorizon.M15,),
    )
    bars = tuple(_bar("15m", START+timedelta(minutes=15*i)) for i in range(1, 7)) + (
        _bar("1h", START+timedelta(hours=1), close=103),
        _bar("4h", START+timedelta(hours=4), close=110),
    )
    repo = FakeRepo(candidate, bars)
    created = await MultiAgentPerformanceService(repo).evaluate_mature_outcomes(
        START+timedelta(hours=1, minutes=30)
    )
    assert tuple(item.horizon for item in created) == ("1H",)
    assert tuple(item.horizon for item in repo.outcomes) == ("1H",)
