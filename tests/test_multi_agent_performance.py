from datetime import datetime, timedelta, timezone

import pytest

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.models import AgentRole
from btc_core.ai.multi_agent.performance import (
    EvaluationHorizon,
    MarketRegime,
    MultiAgentPerformanceService,
    evaluate_outcome,
    summarize_performance,
)
from btc_core.ai.multi_agent.repository import (
    MarketOutcomeBar,
    OutcomeEvaluationCandidate,
    OutcomeState,
    PerformanceEvidence,
)

START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def candidate(direction=Direction.LONG, existing=()):
    return OutcomeEvaluationCandidate(
        multi_agent_run_id="11111111-1111-4111-8111-111111111111",
        agent_attempt_id=7,
        role=AgentRole.TECHNICAL,
        provider=AIProvider.GEMINI,
        model="gemini-test",
        symbol="BTCUSDT",
        direction=direction,
        started_at=START,
        reference_price=100,
        market_regime=MarketRegime.BULL,
        existing_horizons=tuple(existing),
    )


def bar(timeframe, close_time, *, high, low, close):
    duration = {"15m": timedelta(minutes=15), "1h": timedelta(hours=1), "4h": timedelta(hours=4)}[timeframe]
    return MarketOutcomeBar(
        symbol="BTCUSDT", timeframe=timeframe,
        open_time=close_time - duration, close_time=close_time,
        high=high, low=low, close=close,
    )


def mfe_bars(hours, *, high=110.0, low=95.0):
    return tuple(
        bar("15m", START + timedelta(minutes=15 * i), high=high, low=low, close=100)
        for i in range(1, hours * 4 + 1)
    )


def test_exact_horizon_close_and_long_signed_excursions():
    result = evaluate_outcome(
        candidate(), EvaluationHorizon.H1,
        horizon_bars=(
            bar("1h", START + timedelta(minutes=59), high=101, low=99, close=999),
            bar("1h", START + timedelta(hours=1), high=103, low=99, close=102),
            bar("1h", START + timedelta(hours=1, minutes=30), high=150, low=80, close=150),
        ),
        mfe_bars=mfe_bars(1),
        now=START + timedelta(hours=2),
    )
    assert result.matured_at == START + timedelta(hours=1)
    assert result.horizon_price == 102
    assert result.signed_return_pct == 2.0
    assert result.directional_hit is True
    assert result.mfe_pct == 10.0 and result.mae_pct == -5.0
    assert result.data_quality == "FULL"
    assert result.state is OutcomeState.EVALUATED


def test_short_return_flips_and_missing_data_fails_closed():
    short = evaluate_outcome(
        candidate(Direction.SHORT), EvaluationHorizon.H1,
        horizon_bars=(bar("1h", START + timedelta(hours=1), high=101, low=89, close=90),),
        mfe_bars=mfe_bars(1, high=105, low=90),
        now=START + timedelta(hours=2),
    )
    assert short.signed_return_pct == 10.0
    assert short.mfe_pct == 10.0 and short.mae_pct == -5.0

    invalid = evaluate_outcome(
        candidate(), EvaluationHorizon.H1,
        horizon_bars=(), mfe_bars=mfe_bars(1), now=START + timedelta(hours=2),
    )
    assert invalid.state is OutcomeState.INVALID_DATA
    assert invalid.data_quality == "MISSING"
    assert invalid.invalid_reason == "MISSING_HORIZON_CLOSE"

    partial = evaluate_outcome(
        candidate(), EvaluationHorizon.H4,
        horizon_bars=(bar("4h", START + timedelta(hours=4), high=110, low=90, close=104),),
        mfe_bars=mfe_bars(1), now=START + timedelta(hours=5),
    )
    assert partial.state is OutcomeState.EVALUATED
    assert partial.data_quality == "PARTIAL"


def evidence(i, *, matured_at, hit=True, signed=2.0, horizon="1H", quality="FULL", direction=Direction.LONG):
    return PerformanceEvidence(
        multi_agent_run_id=f"run-{i}", agent_attempt_id=i + 1,
        role=AgentRole.TECHNICAL, provider=AIProvider.GEMINI, model="gemini-test",
        symbol="BTCUSDT", direction=direction, market_regime=MarketRegime.BULL,
        horizon=horizon, state=OutcomeState.EVALUATED, data_quality=quality,
        matured_at=matured_at, directional_hit=hit, signed_return_pct=signed,
    )


def test_historical_weight_is_cold_start_and_anti_lookahead():
    as_of = START + timedelta(days=10)
    rows = [evidence(i, matured_at=as_of - timedelta(days=1)) for i in range(29)]
    rows += [
        evidence(100, matured_at=as_of + timedelta(seconds=1)),
        evidence(101, matured_at=as_of - timedelta(days=1), horizon="15M"),
        evidence(102, matured_at=as_of - timedelta(days=1), quality="PARTIAL"),
        evidence(103, matured_at=as_of - timedelta(days=1), direction=Direction.WAIT, hit=None, signed=None),
    ]
    summary = summarize_performance(
        rows, as_of=as_of, role=AgentRole.TECHNICAL,
        provider=AIProvider.GEMINI, model="gemini-test", horizon=EvaluationHorizon.H1,
    )
    assert summary.sample_count == 29
    assert summary.multiplier == 1.0


def test_locked_multiplier_formula_after_30_full_canonical_rows():
    as_of = START + timedelta(days=10)
    rows = [evidence(i, matured_at=as_of - timedelta(days=1)) for i in range(30)]
    summary = summarize_performance(
        rows, as_of=as_of, role=AgentRole.TECHNICAL,
        provider=AIProvider.GEMINI, model="gemini-test", horizon=EvaluationHorizon.H1,
    )
    assert summary.sample_count == 30
    assert summary.hit_rate == 1.0
    assert summary.mean_signed_return_pct == 2.0
    assert summary.normalized_expectancy == 1.0
    assert summary.quality_score == 1.0
    assert summary.multiplier == 1.25


class FakeRepo:
    def __init__(self, rows):
        self.rows = tuple(rows)
        self.snapshots = []

    async def list_performance_evidence(self, as_of):
        return tuple(row for row in self.rows if row.matured_at <= as_of)

    async def append_performance_snapshot(self, item):
        self.snapshots.append(item)
        return len(self.snapshots)


@pytest.mark.asyncio
async def test_historical_weight_persists_metric_inputs_before_return():
    as_of = START + timedelta(days=10)
    repo = FakeRepo(evidence(i, matured_at=as_of - timedelta(days=1)) for i in range(30))
    service = MultiAgentPerformanceService(repo)
    multiplier = await service.historical_weight_for(
        AgentRole.TECHNICAL, AIProvider.GEMINI, "gemini-test", as_of
    )
    assert multiplier == 1.25
    assert len(repo.snapshots) == 1
    assert repo.snapshots[0].sample_count == 30
    assert repo.snapshots[0].horizon == "1H"
    assert repo.snapshots[0].performance_algorithm_version == "performance-v1"
