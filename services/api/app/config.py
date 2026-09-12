from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TradingMode(StrEnum):
    SIMULATION = "SIMULATION"
    TESTNET = "TESTNET"
    LIVE = "LIVE"


class PublicConfig(BaseModel):
    trading_mode: TradingMode = TradingMode.SIMULATION
    direct_ai_order_enabled: bool = False
    min_confidence: float = 75.0
    min_opportunity_score: float = 75.0
    max_leverage: float = 5.0
    ai_analysis_enabled: bool = False
    ai_provider: str | None = None
    ai_model: str | None = None
    ai_api_key_configured: bool = False


class _PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleAssignmentSummary(_PublicModel):
    role: Literal["TECHNICAL", "MOMENTUM", "ORDER_FLOW", "NEWS", "CONTRARIAN", "RISK_REVIEW"]
    enabled: bool
    provider: str
    model: str
    base_weight: float = Field(gt=0)
    prompt_version: str
    prompt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    secret_configured: bool = False


class MultiAgentConfigSummary(_PublicModel):
    config_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    rollout_mode: Literal["OFF", "SHADOW", "PRIMARY"]
    min_valid_roles: int = Field(ge=1, le=6)
    min_coverage: float = Field(ge=0, le=1)
    min_agreement: float = Field(ge=0, le=1)
    min_signed_score: float = Field(ge=0, le=1)
    decision_contract_version: str
    consensus_algorithm_version: str
    hesitation_algorithm_version: str
    performance_algorithm_version: str
    roles: list[RoleAssignmentSummary]


class HesitationBreakdown(_PublicModel):
    total: float = Field(ge=0, le=100)
    disagreement: float = Field(ge=0, le=1)
    confidence_dispersion: float = Field(ge=0, le=1)
    timeframe_conflict: float = Field(ge=0, le=1)
    market_uncertainty: float = Field(ge=0, le=1)
    disagreement_contribution: float = Field(ge=0, le=100)
    confidence_dispersion_contribution: float = Field(ge=0, le=100)
    timeframe_conflict_contribution: float = Field(ge=0, le=100)
    market_uncertainty_contribution: float = Field(ge=0, le=100)
    algorithm_version: str


class RoleContributionSummary(_PublicModel):
    role: str
    provider: str
    model: str
    direction: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=100)
    base_weight: float = Field(gt=0)
    historical_multiplier: float = Field(ge=0)
    effective_weight: float = Field(ge=0)
    unsigned_strength: float = Field(ge=0)
    signed_contribution: float
    participated: bool
    attempt_id: int | None = None


class ConsensusDecisionSummary(_PublicModel):
    id: int
    direction: Literal["LONG", "SHORT", "WAIT", "EXIT"]
    consensus_confidence: float = Field(ge=0, le=100)
    winning_agreement: float = Field(ge=0, le=1)
    coverage: float = Field(ge=0, le=1)
    signed_score: float = Field(ge=-1, le=1)
    actionable: bool
    supporting_roles: list[str]
    opposing_roles: list[str]
    reason_codes: list[str]
    role_contributions: list[RoleContributionSummary]
    config_version: str
    algorithm_version: str
    hesitation: HesitationBreakdown
    created_at: datetime


class RiskResultSummary(_PublicModel):
    status: Literal["APPROVED", "REJECTED", "PENDING"]
    approved: bool
    reason_codes: list[str]
    risk_policy_version: str
    created_at: datetime


class VortexInputsSummary(_PublicModel):
    trend_strength: float = Field(ge=0, le=1)
    volatility: float = Field(ge=0, le=1)
    momentum: float = Field(ge=-1, le=1)
    order_flow_imbalance: float = Field(ge=-1, le=1)
    liquidity: float = Field(ge=0, le=1)
    consensus_direction: Literal["LONG", "SHORT", "WAIT", "EXIT"]
    winning_agreement: float = Field(ge=0, le=1)
    hesitation_total: float = Field(ge=0, le=100)
    observed_at: datetime
    snapshot_ref: str
    mapping_version: str


class AgentAttemptSummary(_PublicModel):
    id: int
    role: str
    provider: str
    model: str
    prompt_version: str
    prompt_digest: str
    status: Literal["SUCCESS", "FAILED", "INVALID_RESPONSE", "SKIPPED"]
    direction: str | None = None
    confidence: float | None = None
    entry_min: float | None = None
    entry_max: float | None = None
    stop_loss: float | None = None
    take_profits: list[float]
    risk_reward: float | None = None
    reason_summary: str | None = None
    latency_ms: int = Field(ge=0)
    error_code: str | None = None
    error_message: str | None = None
    snapshot_ref: str
    created_at: datetime


class MultiAgentRunSummary(_PublicModel):
    record_type: Literal["MULTI_AGENT"] = "MULTI_AGENT"
    id: str
    scanner_candidate_id: int
    symbol: str
    timeframe: str
    started_at: datetime
    completed_at: datetime | None = None
    status: Literal["RUNNING", "COMPLETED", "PARTIAL", "INSUFFICIENT_EVIDENCE", "FAILED"]
    config_version: str
    enabled_role_count: int
    valid_role_count: int
    rollout_mode: Literal["OFF", "SHADOW", "PRIMARY"]
    vortex_inputs: VortexInputsSummary
    consensus: ConsensusDecisionSummary | None = None
    risk: RiskResultSummary | None = None


class MultiAgentRunDetail(MultiAgentRunSummary):
    attempts: list[AgentAttemptSummary]


class DashboardEventSummary(_PublicModel):
    id: int | str
    run_id: str
    source: Literal["MULTI_AGENT", "ORDER_INTENT", "SIMULATION"]
    event_type: str
    role: str | None = None
    status: str
    message: str
    metadata_safe: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PerformanceSummaryResponse(_PublicModel):
    role: str
    provider: str
    model: str
    symbol: str | None = None
    direction: str | None = None
    market_regime: str | None = None
    horizon: Literal["15M", "1H", "4H"]
    sample_count: int = Field(ge=0)
    hit_rate: float = Field(ge=0, le=1)
    mean_signed_return_pct: float
    normalized_expectancy: float = Field(ge=0, le=1)
    quality_score: float = Field(ge=0, le=1)
    multiplier: float = Field(ge=0.75, le=1.25)
    as_of: datetime
    algorithm_version: str
