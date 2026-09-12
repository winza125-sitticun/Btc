from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from btc_core.ai.multi_agent.models import ConsensusDecision, FrozenConfigSnapshot, FrozenSnapshotEnvelope, HesitationSnapshot
from btc_core.ai.multi_agent.repository import RiskResultStatus


class MultiAgentRiskPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    min_consensus_confidence: float = Field(default=75.0, ge=0, le=100)
    max_hesitation: float = Field(default=50.0, ge=0, le=100)
    min_opportunity_score: float = Field(default=75.0, ge=0, le=100)
    risk_policy_version: str = Field(default="multi-agent-risk-v1", min_length=1, max_length=100)

    @classmethod
    def from_config(cls, config: FrozenConfigSnapshot) -> "MultiAgentRiskPolicy":
        return cls(
            min_consensus_confidence=config.risk_min_consensus_confidence,
            max_hesitation=config.risk_max_hesitation,
            min_opportunity_score=config.risk_min_opportunity_score,
            risk_policy_version=config.risk_policy_version,
        )


class MultiAgentRiskDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: RiskResultStatus
    approved: bool
    reason_codes: tuple[str, ...] = ()
    risk_policy_version: str = Field(min_length=1, max_length=100)


def evaluate_multi_agent_risk(
    *,
    consensus: ConsensusDecision,
    hesitation: HesitationSnapshot,
    snapshot_envelope: FrozenSnapshotEnvelope,
    policy: MultiAgentRiskPolicy,
) -> MultiAgentRiskDecision:
    reasons: list[str] = []
    if not consensus.actionable:
        reasons.append("CONSENSUS_NOT_ACTIONABLE")
    if consensus.consensus_confidence < policy.min_consensus_confidence:
        reasons.append("CONSENSUS_CONFIDENCE_BELOW_MINIMUM")
    if hesitation.total > policy.max_hesitation:
        reasons.append("HESITATION_ABOVE_MAXIMUM")
    if snapshot_envelope.snapshot.opportunity_score < policy.min_opportunity_score:
        reasons.append("OPPORTUNITY_SCORE_BELOW_MINIMUM")

    approved = not reasons
    return MultiAgentRiskDecision(
        status=RiskResultStatus.APPROVED if approved else RiskResultStatus.REJECTED,
        approved=approved,
        reason_codes=tuple(reasons),
        risk_policy_version=policy.risk_policy_version,
    )
