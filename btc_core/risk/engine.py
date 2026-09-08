from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    min_confidence: float = 75.0
    min_opportunity_score: float = 75.0
    min_risk_reward: float = 2.0
    max_leverage: float = 5.0
    max_risk_percent: float = 1.0
    max_daily_loss_percent: float = 3.0
    max_open_positions: int = 3


@dataclass(frozen=True, slots=True)
class RiskInputs:
    confidence: float
    opportunity_score: float
    risk_reward: float
    leverage: float
    risk_percent: float
    daily_loss_percent: float
    open_positions: int
    high_impact_event_blocked: bool


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...]


def evaluate_risk(inputs: RiskInputs, policy: RiskPolicy) -> RiskDecision:
    reasons: list[str] = []

    if inputs.confidence < policy.min_confidence:
        reasons.append("confidence_below_minimum")
    if inputs.opportunity_score < policy.min_opportunity_score:
        reasons.append("opportunity_score_below_minimum")
    if inputs.risk_reward < policy.min_risk_reward:
        reasons.append("risk_reward_below_minimum")
    if inputs.leverage > policy.max_leverage:
        reasons.append("leverage_above_maximum")
    if inputs.risk_percent > policy.max_risk_percent:
        reasons.append("risk_per_trade_above_maximum")
    if inputs.daily_loss_percent >= policy.max_daily_loss_percent:
        reasons.append("daily_loss_limit_reached")
    if inputs.open_positions >= policy.max_open_positions:
        reasons.append("max_open_positions_reached")
    if inputs.high_impact_event_blocked:
        reasons.append("high_impact_event_guard")

    return RiskDecision(approved=not reasons, reasons=tuple(reasons))
