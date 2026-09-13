from __future__ import annotations

from dataclasses import replace
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field

from btc_core.ai.multi_agent.models import ConsensusDecision, FrozenConfigSnapshot, FrozenSnapshotEnvelope, HesitationSnapshot
from btc_core.ai.multi_agent.repository import RiskResultStatus
from btc_core.risk.engine import RiskPolicy
from btc_core.strategy.risk import FullRiskContext, evaluate_full_risk


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


def _full_context_is_incomplete(context: FullRiskContext) -> bool:
    numeric = (context.balance, context.equity)
    return (
        context.event_blocked is None
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(value)
            or value <= 0
            for value in numeric
        )
    )


def _full_risk_reason(code: str) -> str:
    return f"FULL_RISK_{code.upper()}"


def evaluate_multi_agent_risk(
    *,
    consensus: ConsensusDecision,
    hesitation: HesitationSnapshot,
    snapshot_envelope: FrozenSnapshotEnvelope,
    policy: MultiAgentRiskPolicy,
    full_risk_context: FullRiskContext | None = None,
    full_risk_policy: RiskPolicy | None = None,
) -> MultiAgentRiskDecision:
    """Evaluate multi-agent evidence without weakening the existing full risk gate.

    Multi-agent thresholds are deterministic prechecks only. An APPROVED result
    requires a complete account/portfolio context and a pass from the existing
    full deterministic risk evaluator. Missing account/event context is PENDING,
    never approval.
    """
    reasons: list[str] = []
    if not consensus.actionable:
        reasons.append("CONSENSUS_NOT_ACTIONABLE")
    if consensus.consensus_confidence < policy.min_consensus_confidence:
        reasons.append("CONSENSUS_CONFIDENCE_BELOW_MINIMUM")
    if hesitation.total > policy.max_hesitation:
        reasons.append("HESITATION_ABOVE_MAXIMUM")
    if snapshot_envelope.snapshot.opportunity_score < policy.min_opportunity_score:
        reasons.append("OPPORTUNITY_SCORE_BELOW_MINIMUM")

    if reasons:
        return MultiAgentRiskDecision(
            status=RiskResultStatus.REJECTED,
            approved=False,
            reason_codes=tuple(reasons),
            risk_policy_version=policy.risk_policy_version,
        )

    if full_risk_context is None or _full_context_is_incomplete(full_risk_context):
        return MultiAgentRiskDecision(
            status=RiskResultStatus.PENDING,
            approved=False,
            reason_codes=("FULL_RISK_CONTEXT_PENDING",),
            risk_policy_version=policy.risk_policy_version,
        )

    effective_context = replace(
        full_risk_context,
        confidence=consensus.consensus_confidence,
        opportunity_score=snapshot_envelope.snapshot.opportunity_score,
    )
    decision = evaluate_full_risk(
        effective_context,
        full_risk_policy or RiskPolicy(),
        readiness_sensitive=True,
    )
    if not decision.approved:
        return MultiAgentRiskDecision(
            status=RiskResultStatus.REJECTED,
            approved=False,
            reason_codes=tuple(_full_risk_reason(reason) for reason in decision.reasons),
            risk_policy_version=policy.risk_policy_version,
        )

    return MultiAgentRiskDecision(
        status=RiskResultStatus.APPROVED,
        approved=True,
        reason_codes=(),
        risk_policy_version=policy.risk_policy_version,
    )