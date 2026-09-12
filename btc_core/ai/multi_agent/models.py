from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from btc_core.ai.analysis import AIAnalysisSnapshot
from btc_core.ai.models import AIProvider, Direction


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentRole(StrEnum):
    TECHNICAL = "TECHNICAL"
    MOMENTUM = "MOMENTUM"
    ORDER_FLOW = "ORDER_FLOW"
    NEWS = "NEWS"
    CONTRARIAN = "CONTRARIAN"
    RISK_REVIEW = "RISK_REVIEW"


class RolloutMode(StrEnum):
    OFF = "OFF"
    SHADOW = "SHADOW"
    PRIMARY = "PRIMARY"


class AttemptStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    SKIPPED = "SKIPPED"


class RolePrompt(_FrozenModel):
    role: AgentRole
    version: str = Field(min_length=1, max_length=40)
    instruction: str = Field(min_length=1, max_length=4000)
    required_focus: tuple[str, ...] = Field(min_length=1)
    safety_constraints: tuple[str, ...] = Field(min_length=1)
    digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class RoleAssignment(_FrozenModel):
    role: AgentRole
    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    base_weight: float = Field(default=1.0, gt=0, le=10)
    prompt_version: str = Field(default="v1", min_length=1, max_length=40)

    @field_validator("model", "prompt_version")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class FrozenRoleAssignment(_FrozenModel):
    role: AgentRole
    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    base_weight: float = Field(gt=0, le=10)
    prompt_version: str = Field(min_length=1, max_length=40)
    prompt_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    prompt_text: str = Field(min_length=1, max_length=4000)


class FrozenConfigSnapshot(_FrozenModel):
    config_version: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    mode: RolloutMode = RolloutMode.OFF
    assignments: tuple[FrozenRoleAssignment, ...] = ()
    min_valid_roles: int = Field(default=4, ge=1, le=6)
    min_coverage: float = Field(default=0.67, ge=0, le=1)
    min_agreement: float = Field(default=0.60, ge=0, le=1)
    min_signed_score: float = Field(default=0.25, ge=0, le=1)
    risk_min_consensus_confidence: float = Field(default=75.0, ge=0, le=100)
    risk_max_hesitation: float = Field(default=50.0, ge=0, le=100)
    risk_min_opportunity_score: float = Field(default=75.0, ge=0, le=100)
    risk_policy_version: str = Field(default="multi-agent-risk-v1", min_length=1, max_length=100)
    decision_contract_version: str = "aid-v1"
    consensus_version: str = "consensus-v1"
    hesitation_version: str = "hesitation-v1"
    performance_version: str = "performance-v1"
    market_context_mapping_version: str = "vortex-input-v1"


class FrozenSnapshotEnvelope(_FrozenModel):
    snapshot_ref: str = Field(min_length=1, max_length=200)
    observed_at: datetime
    snapshot: AIAnalysisSnapshot


class AgentRequest(_FrozenModel):
    role: AgentRole
    prompt: RolePrompt
    snapshot_envelope: FrozenSnapshotEnvelope


class AgentAttempt(_FrozenModel):
    attempt_id: str = Field(min_length=1, max_length=200)
    role: AgentRole
    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    status: AttemptStatus
    direction: Direction | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def validate_success_payload(self):
        if self.status is AttemptStatus.SUCCESS and (self.direction is None or self.confidence is None):
            raise ValueError("successful attempts require direction and confidence")
        return self


class RoleContribution(_FrozenModel):
    role: AgentRole
    provider: AIProvider
    model: str = Field(min_length=1, max_length=120)
    direction: Direction | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    base_weight: float = Field(gt=0)
    historical_multiplier: float = Field(ge=0)
    effective_weight: float = Field(ge=0)
    unsigned_strength: float = Field(ge=0)
    signed_contribution: float
    participated: bool
    attempt_id: str | None = None


class ConsensusDecision(_FrozenModel):
    direction: Direction
    consensus_confidence: float = Field(ge=0, le=100)
    winning_agreement: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)
    signed_score: float = Field(ge=-1, le=1)
    actionable: bool
    supporting_roles: tuple[AgentRole, ...] = ()
    opposing_roles: tuple[AgentRole, ...] = ()
    reason_codes: tuple[str, ...] = ()
    role_contributions: tuple[RoleContribution, ...] = ()
    config_version: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    consensus_algorithm_version: str = "consensus-v1"


class HesitationSnapshot(_FrozenModel):
    total: float = Field(ge=0, le=100)
    disagreement: float = Field(ge=0, le=1)
    confidence_dispersion: float = Field(ge=0, le=1)
    timeframe_conflict: float = Field(ge=0, le=1)
    market_uncertainty: float = Field(ge=0, le=1)
    disagreement_contribution: float = Field(ge=0, le=100)
    confidence_dispersion_contribution: float = Field(ge=0, le=100)
    timeframe_conflict_contribution: float = Field(ge=0, le=100)
    market_uncertainty_contribution: float = Field(ge=0, le=100)
    hesitation_algorithm_version: str = "hesitation-v1"


class VortexInputs(_FrozenModel):
    trend_strength: float = Field(ge=0, le=1)
    volatility: float = Field(ge=0, le=1)
    momentum: float = Field(ge=-1, le=1)
    order_flow_imbalance: float = Field(ge=-1, le=1)
    liquidity: float = Field(ge=0, le=1)
    snapshot_ref: str = Field(min_length=1, max_length=200)
    observed_at: datetime
    mapping_version: str = "vortex-input-v1"
    predecision_regime: str = Field(default="UNKNOWN", pattern=r"^(BULL|BEAR|SIDEWAYS|UNKNOWN)$")
    consensus_direction: Direction | None = None
    winning_agreement: float | None = Field(default=None, ge=0, le=1)
    hesitation_total: float | None = Field(default=None, ge=0, le=100)


class MultiAgentConfig(_FrozenModel):
    mode: RolloutMode = RolloutMode.OFF
    assignments: tuple[RoleAssignment, ...] = ()
    min_valid_roles: int = Field(default=4, ge=1, le=6)
    min_coverage: float = Field(default=0.67, ge=0, le=1)
    min_agreement: float = Field(default=0.60, ge=0, le=1)
    min_signed_score: float = Field(default=0.25, ge=0, le=1)
    risk_min_consensus_confidence: float = Field(default=75.0, ge=0, le=100)
    risk_max_hesitation: float = Field(default=50.0, ge=0, le=100)
    risk_min_opportunity_score: float = Field(default=75.0, ge=0, le=100)
    risk_policy_version: str = Field(default="multi-agent-risk-v1", min_length=1, max_length=100)
    decision_contract_version: str = "aid-v1"
    consensus_version: str = "consensus-v1"
    hesitation_version: str = "hesitation-v1"
    performance_version: str = "performance-v1"
    market_context_mapping_version: str = "vortex-input-v1"
    diagnostics: tuple[str, ...] = ()

    def to_frozen_snapshot(self) -> FrozenConfigSnapshot:
        from btc_core.ai.multi_agent.config import freeze_multi_agent_config

        return freeze_multi_agent_config(self)
