from datetime import datetime, timezone

import pytest

from btc_core.ai.analysis import AINewsContext, AIAnalysisSnapshot, TimeframeTechnicalContext
from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.hesitation import calculate_hesitation
from btc_core.ai.multi_agent.models import (
    AgentAttempt,
    AgentRole,
    AttemptStatus,
    ConsensusDecision,
    FrozenSnapshotEnvelope,
)
from btc_core.scanner.scoring import OpportunityInputs


def _attempt(role: AgentRole, direction: Direction, confidence: float) -> AgentAttempt:
    return AgentAttempt(
        attempt_id=role.value.lower(), role=role, provider=AIProvider.GEMINI,
        model="model-test", status=AttemptStatus.SUCCESS,
        direction=direction, confidence=confidence,
    )


def _envelope() -> FrozenSnapshotEnvelope:
    technical = {
        "4h": TimeframeTechnicalContext(timeframe="4h", close=100, trend_percent=0.5, momentum_percent=1.0, recent_high=110, recent_low=90, recent_volume_ratio=1.2, direction=Direction.LONG),
        "1h": TimeframeTechnicalContext(timeframe="1h", close=100, trend_percent=-0.4, momentum_percent=-0.8, recent_high=105, recent_low=95, recent_volume_ratio=1.0, direction=Direction.SHORT),
        "15m": TimeframeTechnicalContext(timeframe="15m", close=100, trend_percent=0.0, momentum_percent=0.0, recent_high=102, recent_low=98, recent_volume_ratio=0.8, direction=Direction.WAIT),
    }
    snapshot = AIAnalysisSnapshot(
        symbol="BTCUSDT", timeframe="15m", scanner_direction=Direction.LONG,
        opportunity_score=70,
        components=OpportunityInputs(technical=80, momentum=70, volume=60, order_flow=50, open_interest=40, funding=50, liquidity=90, news=50, macro=50, risk_reward=50),
        last_price=100, funding_rate=0.0001, open_interest_change_percent=1.0,
        long_short_ratio=1.2, spread_percent=0.05,
        technical_by_timeframe=technical, news=AINewsContext(score=50, stories=()),
    )
    return FrozenSnapshotEnvelope(snapshot_ref="snap-1", observed_at=datetime(2026, 9, 12, tzinfo=timezone.utc), snapshot=snapshot)


def test_hesitation_uses_documented_four_factor_equation():
    attempts = (
        _attempt(AgentRole.TECHNICAL, Direction.LONG, 80),
        _attempt(AgentRole.MOMENTUM, Direction.LONG, 70),
        _attempt(AgentRole.ORDER_FLOW, Direction.SHORT, 60),
        _attempt(AgentRole.NEWS, Direction.WAIT, 50),
    )
    consensus = ConsensusDecision(
        direction=Direction.LONG,
        consensus_confidence=75,
        winning_agreement=0.714286,
        coverage=1,
        signed_score=0.428571,
        actionable=True,
        supporting_roles=(AgentRole.TECHNICAL, AgentRole.MOMENTUM),
        opposing_roles=(AgentRole.ORDER_FLOW, AgentRole.NEWS),
        reason_codes=("WAIT_PRESENT", "ACTIONABLE_LONG"),
        role_contributions=(),
        config_version="b" * 64,
        consensus_algorithm_version="consensus-v1",
    )

    result = calculate_hesitation(attempts, consensus, _envelope())

    assert result.disagreement == pytest.approx(0.285714)
    assert result.confidence_dispersion == pytest.approx(0.223607)
    assert result.timeframe_conflict == pytest.approx(0.666667)
    assert result.market_uncertainty == pytest.approx(0.35)
    assert result.disagreement_contribution == pytest.approx(11.42856)
    assert result.confidence_dispersion_contribution == pytest.approx(4.47214)
    assert result.timeframe_conflict_contribution == pytest.approx(16.666675)
    assert result.market_uncertainty_contribution == pytest.approx(5.25)
    assert result.total == pytest.approx(37.817375)


def test_no_directional_evidence_sets_disagreement_to_one():
    consensus = ConsensusDecision(
        direction=Direction.WAIT, consensus_confidence=0, winning_agreement=0,
        coverage=1, signed_score=0, actionable=False,
        supporting_roles=(), opposing_roles=(AgentRole.TECHNICAL,),
        reason_codes=("NO_DIRECTIONAL_EVIDENCE",), role_contributions=(),
        config_version="b" * 64, consensus_algorithm_version="consensus-v1",
    )
    result = calculate_hesitation(
        (_attempt(AgentRole.TECHNICAL, Direction.WAIT, 50),), consensus, _envelope()
    )
    assert result.disagreement == pytest.approx(1.0)
