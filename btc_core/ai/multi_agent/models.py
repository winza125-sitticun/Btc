from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from btc_core.ai.analysis import AIAnalysisSnapshot
from btc_core.ai.models import AIProvider


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


class MultiAgentConfig(_FrozenModel):
    mode: RolloutMode = RolloutMode.OFF
    assignments: tuple[RoleAssignment, ...] = ()
    min_valid_roles: int = Field(default=4, ge=1, le=6)
    min_coverage: float = Field(default=0.67, ge=0, le=1)
    min_agreement: float = Field(default=0.60, ge=0, le=1)
    min_signed_score: float = Field(default=0.25, ge=0, le=1)
    decision_contract_version: str = "aid-v1"
    consensus_version: str = "consensus-v1"
    hesitation_version: str = "hesitation-v1"
    performance_version: str = "performance-v1"
    market_context_mapping_version: str = "vortex-input-v1"
    diagnostics: tuple[str, ...] = ()

    def to_frozen_snapshot(self) -> FrozenConfigSnapshot:
        from btc_core.ai.multi_agent.config import freeze_multi_agent_config

        return freeze_multi_agent_config(self)
