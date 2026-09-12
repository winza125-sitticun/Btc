from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from btc_core.ai.analysis import AINewsContext, AIAnalysisSnapshot, TimeframeTechnicalContext
from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.models import AgentRole, FrozenConfigSnapshot, FrozenRoleAssignment, RolloutMode
from btc_core.ai.multi_agent.repository import RiskResultStatus
from btc_core.ai.multi_agent.scan_runner import MultiAgentScanRunner
from btc_core.market.scanner import MarketScanResult, MarketScannerCandidate
from btc_core.market.supabase_repo import PersistedCandidateRef, PersistedScanRef
from btc_core.scanner.scoring import OpportunityInputs

NOW = datetime(2026, 9, 12, 11, 0, tzinfo=timezone.utc)


def _candidate():
    return MarketScannerCandidate(
        rank=1, symbol="BTCUSDT", timeframe="15m", direction=Direction.LONG,
        opportunity_score=85, directional_signal=0.5,
        components=OpportunityInputs(
            technical=80, momentum=80, volume=80, order_flow=80, open_interest=80,
            funding=80, liquidity=80, news=80, macro=80, risk_reward=80,
        ),
        last_price=100, quote_volume_24h=1_000_000, funding_rate=0.0001,
        open_interest_change_percent=1, long_short_ratio=1.2, spread_percent=0.05,
    )


def _snapshot(candidate):
    technical = {
        tf: TimeframeTechnicalContext(
            timeframe=tf, close=100, trend_percent=0.5, momentum_percent=0.5,
            recent_high=110, recent_low=90, recent_volume_ratio=1, direction=Direction.LONG,
        )
        for tf in ("4h", "1h", "15m")
    }
    return AIAnalysisSnapshot(
        symbol=candidate.symbol, timeframe="15m", scanner_direction=Direction.LONG,
        opportunity_score=85, components=candidate.components, last_price=100,
        funding_rate=0.0001, open_interest_change_percent=1, long_short_ratio=1.2,
        spread_percent=0.05, technical_by_timeframe=technical,
        news=AINewsContext(score=80, stories=()),
    )


def _config():
    return FrozenConfigSnapshot(
        config_version="f"*64, mode=RolloutMode.SHADOW, min_valid_roles=1,
        assignments=(FrozenRoleAssignment(
            role=AgentRole.TECHNICAL, provider=AIProvider.GEMINI, model="gemini-test",
            base_weight=1, prompt_version="v1", prompt_digest="a"*64,
            prompt_text="technical mandate",
        ),),
    )


class RecordingOrchestrator:
    def __init__(self):
        self.calls = []
    async def orchestrate(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            risk=SimpleNamespace(status=RiskResultStatus.APPROVED, approved=True)
        )


class PerformanceService:
    def __init__(self, fail=False, refresh_fail=False):
        self.fail = fail
        self.refresh_fail = refresh_fail
        self.calls = []
        self.refresh_calls = []
        self.events = []
    async def evaluate_mature_outcomes(self, as_of):
        self.refresh_calls.append(as_of)
        self.events.append("refresh")
        if self.refresh_fail:
            raise RuntimeError("outcome refresh unavailable")
        return ()
    async def historical_weight_for(self, role, provider, model, as_of):
        self.calls.append((role, provider, model, as_of))
        self.events.append("weight")
        if self.fail:
            raise RuntimeError("history unavailable")
        return 1.2


async def _run(performance):
    candidate = _candidate()
    result = MarketScanResult(timeframe="15m", universe_size=1, candidates=[candidate], failures=[])
    persisted = PersistedScanRef(
        run_id="22222222-2222-4222-8222-222222222222",
        candidates=(PersistedCandidateRef(id=101, rank=1, symbol="BTCUSDT"),),
    )
    orchestrator = RecordingOrchestrator()

    async def snapshot_builder(item):
        return _snapshot(item)

    runner = MultiAgentScanRunner(
        orchestrator=orchestrator, config=_config(), snapshot_builder=snapshot_builder,
        performance_service=performance, now=lambda: NOW,
    )
    summary = await runner.analyze_scan(result, persisted)
    return summary, orchestrator


@pytest.mark.asyncio
async def test_scan_runner_refreshes_mature_outcomes_before_point_in_time_weight():
    performance = PerformanceService()
    summary, orchestrator = await _run(performance)
    assert summary.approved == 1
    assert performance.refresh_calls == [NOW]
    assert performance.events == ["refresh", "weight"]
    assert performance.calls == [(
        AgentRole.TECHNICAL, AIProvider.GEMINI, "gemini-test", NOW,
    )]
    assert orchestrator.calls[0]["historical_weights"] == {AgentRole.TECHNICAL: 1.2}


@pytest.mark.asyncio
async def test_historical_weight_failure_falls_back_to_one_without_failing_candidate():
    summary, orchestrator = await _run(PerformanceService(fail=True))
    assert summary.approved == 1 and summary.failed == 0
    assert orchestrator.calls[0]["historical_weights"] == {AgentRole.TECHNICAL: 1.0}


@pytest.mark.asyncio
async def test_outcome_refresh_failure_is_isolated_from_current_candidate():
    performance = PerformanceService(refresh_fail=True)
    summary, orchestrator = await _run(performance)
    assert summary.approved == 1 and summary.failed == 0
    assert performance.events == ["refresh", "weight"]
    assert orchestrator.calls[0]["historical_weights"] == {AgentRole.TECHNICAL: 1.2}