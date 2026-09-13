from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from btc_core.ai.analysis import AINewsContext, AIAnalysisSnapshot, TimeframeTechnicalContext
from btc_core.ai.models import Direction
from btc_core.ai.multi_agent.models import FrozenConfigSnapshot, RolloutMode
from btc_core.ai.multi_agent.repository import RiskResultStatus
from btc_core.ai.multi_agent.scan_runner import MultiAgentScanRunner
from btc_core.market.scanner import MarketScanResult, MarketScannerCandidate
from btc_core.market.supabase_repo import PersistedCandidateRef, PersistedScanRef
from btc_core.scanner.scoring import OpportunityInputs


NOW = datetime(2026, 9, 12, 10, 30, tzinfo=timezone.utc)


def _candidate(rank: int, symbol: str, score: float) -> MarketScannerCandidate:
    return MarketScannerCandidate(
        rank=rank,
        symbol=symbol,
        timeframe="15m",
        direction=Direction.LONG,
        opportunity_score=score,
        directional_signal=0.5,
        components=OpportunityInputs(technical=80, momentum=80, volume=80, order_flow=80, open_interest=80, funding=80, liquidity=80, news=80, macro=80, risk_reward=80),
        last_price=100,
        quote_volume_24h=1_000_000,
        funding_rate=0.0001,
        open_interest_change_percent=1.0,
        long_short_ratio=1.2,
        spread_percent=0.05,
    )


def _snapshot(candidate: MarketScannerCandidate) -> AIAnalysisSnapshot:
    technical = {
        timeframe: TimeframeTechnicalContext(
            timeframe=timeframe, close=100, trend_percent=0.5, momentum_percent=0.5,
            recent_high=110, recent_low=90, recent_volume_ratio=1.0, direction=Direction.LONG,
        )
        for timeframe in ("4h", "1h", "15m")
    }
    return AIAnalysisSnapshot(
        symbol=candidate.symbol,
        timeframe=candidate.timeframe,
        scanner_direction=candidate.direction,
        opportunity_score=candidate.opportunity_score,
        components=candidate.components,
        last_price=candidate.last_price,
        funding_rate=candidate.funding_rate,
        open_interest_change_percent=candidate.open_interest_change_percent,
        long_short_ratio=candidate.long_short_ratio,
        spread_percent=candidate.spread_percent,
        technical_by_timeframe=technical,
        news=AINewsContext(score=80, stories=()),
    )


class RecordingOrchestrator:
    def __init__(self):
        self.calls = []

    async def orchestrate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["run"].symbol == "ETHUSDT":
            raise RuntimeError("one candidate failed")
        return SimpleNamespace(
            risk=SimpleNamespace(status=RiskResultStatus.APPROVED, approved=True)
        )


@pytest.mark.asyncio
async def test_scan_runner_filters_candidates_builds_frozen_runs_and_isolates_one_candidate_failure():
    candidates = [
        _candidate(1, "BTCUSDT", 85),
        _candidate(2, "ETHUSDT", 80),
        _candidate(3, "XRPUSDT", 60),
    ]
    result = MarketScanResult(timeframe="15m", universe_size=3, candidates=candidates, failures=[])
    persisted = PersistedScanRef(
        run_id="22222222-2222-4222-8222-222222222222",
        candidates=tuple(
            PersistedCandidateRef(id=100 + item.rank, rank=item.rank, symbol=item.symbol)
            for item in candidates
        ),
    )
    config = FrozenConfigSnapshot(
        config_version="f" * 64,
        mode=RolloutMode.SHADOW,
        assignments=(),
        min_valid_roles=1,
    )
    orchestrator = RecordingOrchestrator()
    built = []

    async def snapshot_builder(candidate):
        built.append(candidate.symbol)
        return _snapshot(candidate)

    runner = MultiAgentScanRunner(
        orchestrator=orchestrator,
        config=config,
        snapshot_builder=snapshot_builder,
        candidate_limit=2,
        min_opportunity_score=65,
        now=lambda: NOW,
    )
    summary = await runner.analyze_scan(result, persisted)

    assert built == ["BTCUSDT", "ETHUSDT"]
    assert len(orchestrator.calls) == 2
    assert summary.attempted == 2
    assert summary.approved == 1
    assert summary.rejected == 0
    assert summary.pending == 0
    assert summary.failed == 1
    assert summary.skipped == 1
    first = orchestrator.calls[0]
    assert first["run"].scanner_candidate_id == 101
    assert first["run"].scanner_run_id == persisted.run_id
    assert first["run"].snapshot_ref == first["snapshot_envelope"].snapshot_ref
    assert first["run"].market_context_summary.snapshot_ref == first["snapshot_envelope"].snapshot_ref
    assert first["snapshot_envelope"].snapshot is not None


@pytest.mark.asyncio
async def test_scan_runner_off_mode_is_fail_closed_and_never_builds_snapshots():
    result = MarketScanResult(
        timeframe="15m", universe_size=1, candidates=[_candidate(1, "BTCUSDT", 90)], failures=[]
    )
    persisted = PersistedScanRef(
        run_id="22222222-2222-4222-8222-222222222222",
        candidates=(PersistedCandidateRef(id=101, rank=1, symbol="BTCUSDT"),),
    )
    config = FrozenConfigSnapshot(config_version="f" * 64, mode=RolloutMode.OFF, assignments=(), min_valid_roles=1)

    async def forbidden_builder(candidate):
        raise AssertionError("OFF mode must not build a snapshot")

    runner = MultiAgentScanRunner(
        orchestrator=RecordingOrchestrator(),
        config=config,
        snapshot_builder=forbidden_builder,
        now=lambda: NOW,
    )
    summary = await runner.analyze_scan(result, persisted)

    assert summary.attempted == 0
    assert summary.skipped == 1