from datetime import datetime, timezone

from btc_core.ai.analysis import AINewsContext, AIAnalysisSnapshot, TimeframeTechnicalContext
from btc_core.ai.models import Direction
from btc_core.ai.multi_agent.models import ConsensusDecision, FrozenSnapshotEnvelope, HesitationSnapshot
from btc_core.ai.multi_agent.repository import RiskResultStatus
from btc_core.ai.multi_agent.risk_gate import MultiAgentRiskPolicy, evaluate_multi_agent_risk
from btc_core.scanner.scoring import OpportunityInputs


def _envelope(opportunity_score: float = 82) -> FrozenSnapshotEnvelope:
    technical = {
        "4h": TimeframeTechnicalContext(timeframe="4h", close=100, trend_percent=0.5, momentum_percent=1.0, recent_high=110, recent_low=90, recent_volume_ratio=1.2, direction=Direction.LONG),
        "1h": TimeframeTechnicalContext(timeframe="1h", close=100, trend_percent=0.4, momentum_percent=0.8, recent_high=105, recent_low=95, recent_volume_ratio=1.0, direction=Direction.LONG),
        "15m": TimeframeTechnicalContext(timeframe="15m", close=100, trend_percent=0.2, momentum_percent=0.3, recent_high=102, recent_low=98, recent_volume_ratio=0.8, direction=Direction.LONG),
    }
    snapshot = AIAnalysisSnapshot(
        symbol="BTCUSDT", timeframe="15m", scanner_direction=Direction.LONG,
        opportunity_score=opportunity_score,
        components=OpportunityInputs(technical=80, momentum=80, volume=80, order_flow=80, open_interest=80, funding=80, liquidity=80, news=80, macro=80, risk_reward=80),
        last_price=100, funding_rate=0.0001, open_interest_change_percent=1.0,
        long_short_ratio=1.2, spread_percent=0.05,
        technical_by_timeframe=technical, news=AINewsContext(score=80, stories=()),
    )
    return FrozenSnapshotEnvelope(
        snapshot_ref="risk-snapshot",
        observed_at=datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc),
        snapshot=snapshot,
    )


def _consensus(*, actionable: bool = True, confidence: float = 82) -> ConsensusDecision:
    return ConsensusDecision(
        direction=Direction.LONG if actionable else Direction.WAIT,
        consensus_confidence=confidence,
        winning_agreement=0.8,
        coverage=1.0,
        signed_score=0.6 if actionable else 0.0,
        actionable=actionable,
        reason_codes=() if actionable else ("LOW_AGREEMENT",),
        config_version="e" * 64,
    )


def _hesitation(total: float) -> HesitationSnapshot:
    return HesitationSnapshot(
        total=total,
        disagreement=0.2,
        confidence_dispersion=0.1,
        timeframe_conflict=0.1,
        market_uncertainty=0.2,
        disagreement_contribution=8,
        confidence_dispersion_contribution=2,
        timeframe_conflict_contribution=2.5,
        market_uncertainty_contribution=3,
    )


def test_deterministic_risk_gate_approves_only_when_all_thresholds_pass():
    result = evaluate_multi_agent_risk(
        consensus=_consensus(),
        hesitation=_hesitation(30),
        snapshot_envelope=_envelope(),
        policy=MultiAgentRiskPolicy(
            min_consensus_confidence=75,
            max_hesitation=50,
            min_opportunity_score=75,
        ),
    )

    assert result.status is RiskResultStatus.APPROVED
    assert result.approved is True
    assert result.reason_codes == ()
    assert result.risk_policy_version == "multi-agent-risk-v1"


def test_deterministic_risk_gate_rejects_each_failed_guard_with_stable_reason_codes():
    result = evaluate_multi_agent_risk(
        consensus=_consensus(actionable=False, confidence=60),
        hesitation=_hesitation(70),
        snapshot_envelope=_envelope(opportunity_score=60),
        policy=MultiAgentRiskPolicy(
            min_consensus_confidence=75,
            max_hesitation=50,
            min_opportunity_score=75,
        ),
    )

    assert result.status is RiskResultStatus.REJECTED
    assert result.approved is False
    assert result.reason_codes == (
        "CONSENSUS_NOT_ACTIONABLE",
        "CONSENSUS_CONFIDENCE_BELOW_MINIMUM",
        "HESITATION_ABOVE_MAXIMUM",
        "OPPORTUNITY_SCORE_BELOW_MINIMUM",
    )
