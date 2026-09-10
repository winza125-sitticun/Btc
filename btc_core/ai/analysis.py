from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from btc_core.ai.models import AIDecision, Direction
from btc_core.risk.engine import RiskPolicy
from btc_core.scanner.scoring import OpportunityInputs


class _FrozenAIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeframeTechnicalContext(_FrozenAIModel):
    timeframe: str = Field(min_length=1, max_length=10)
    close: float = Field(gt=0)
    trend_percent: float
    momentum_percent: float
    recent_high: float = Field(gt=0)
    recent_low: float = Field(gt=0)
    recent_volume_ratio: float = Field(ge=0)
    direction: Direction


class AINewsContext(_FrozenAIModel):
    score: float = Field(ge=0, le=100)
    stories: tuple[dict[str, object], ...] = ()


class AIAnalysisSnapshot(_FrozenAIModel):
    symbol: str = Field(min_length=3, max_length=30)
    timeframe: str = Field(min_length=1, max_length=10)
    scanner_direction: Direction
    opportunity_score: float = Field(ge=0, le=100)
    components: OpportunityInputs
    last_price: float = Field(gt=0)
    funding_rate: float
    open_interest_change_percent: float
    long_short_ratio: float = Field(gt=0)
    spread_percent: float = Field(ge=0)
    technical_by_timeframe: dict[str, TimeframeTechnicalContext]
    news: AINewsContext


class PriceGeometryResult(_FrozenAIModel):
    valid: bool
    reasons: tuple[str, ...] = ()


class AIAnalysisPrecheck(_FrozenAIModel):
    actionable: bool = False
    status: str
    reasons: tuple[str, ...] = ()


def validate_price_geometry(decision: AIDecision) -> PriceGeometryResult:
    if decision.direction is Direction.LONG:
        valid = (
            decision.stop_loss < decision.entry_min <= decision.entry_max
            and all(tp > decision.entry_max for tp in decision.take_profits)
        )
    elif decision.direction is Direction.SHORT:
        valid = (
            all(tp < decision.entry_min for tp in decision.take_profits)
            and decision.entry_min <= decision.entry_max < decision.stop_loss
        )
    elif decision.direction is Direction.WAIT:
        return PriceGeometryResult(valid=True)
    else:
        return PriceGeometryResult(valid=False, reasons=("exit_not_allowed",))

    return PriceGeometryResult(
        valid=valid,
        reasons=() if valid else ("invalid_price_structure",),
    )


def precheck_ai_decision(
    decision: AIDecision,
    *,
    opportunity_score: float,
    policy: RiskPolicy,
) -> AIAnalysisPrecheck:
    reasons: list[str] = []

    geometry = validate_price_geometry(decision)
    reasons.extend(geometry.reasons)

    if decision.direction is Direction.WAIT:
        reasons.append("wait_direction")
    elif decision.direction is Direction.EXIT and "exit_not_allowed" not in reasons:
        reasons.append("exit_not_allowed")

    if decision.confidence < policy.min_confidence:
        reasons.append("confidence_below_minimum")
    if opportunity_score < policy.min_opportunity_score:
        reasons.append("opportunity_score_below_minimum")
    if decision.risk_reward < policy.min_risk_reward:
        reasons.append("risk_reward_below_minimum")

    if reasons:
        return AIAnalysisPrecheck(
            actionable=False,
            status="PRECHECK_FAILED",
            reasons=tuple(reasons),
        )

    return AIAnalysisPrecheck(
        actionable=False,
        status="FULL_RISK_CONTEXT_PENDING",
        reasons=(),
    )
