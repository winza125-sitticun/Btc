"""Pure, deterministic simulation risk evaluation and position sizing."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from btc_core.risk.engine import RiskDecision, RiskPolicy


@dataclass(frozen=True, slots=True)
class FullRiskContext:
    confidence: float
    opportunity_score: float
    risk_reward: float
    requested_leverage: float
    daily_realized_loss_percent: float
    open_positions: int
    event_blocked: bool | None
    balance: float
    equity: float
    market_data_quality_ok: bool = True


@dataclass(frozen=True, slots=True)
class PositionSize:
    quantity: float
    risk_amount: float
    risk_percent: float
    stop_distance: float
    max_notional: float


def _positive(value: float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be positive")


def _context_is_valid(context: FullRiskContext) -> bool:
    numeric = (
        context.confidence,
        context.opportunity_score,
        context.risk_reward,
        context.requested_leverage,
        context.daily_realized_loss_percent,
        context.balance,
        context.equity,
    )
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) for value in numeric):
        return False
    if not (0 <= context.confidence <= 100 and 0 <= context.opportunity_score <= 100):
        return False
    if context.risk_reward <= 0 or context.requested_leverage <= 0 or context.daily_realized_loss_percent < 0:
        return False
    if not isinstance(context.open_positions, int) or isinstance(context.open_positions, bool) or context.open_positions < 0:
        return False
    return context.balance > 0 and context.equity > 0


def evaluate_full_risk(
    context: FullRiskContext,
    policy: RiskPolicy,
    *,
    readiness_sensitive: bool = False,
) -> RiskDecision:
    """Evaluate all account, market, event, and policy guards in simulation."""
    reasons: list[str] = []
    if not _context_is_valid(context):
        return RiskDecision(approved=False, reasons=("risk_context_invalid",))
    if context.confidence < policy.min_confidence:
        reasons.append("confidence_below_minimum")
    if context.opportunity_score < policy.min_opportunity_score:
        reasons.append("opportunity_score_below_minimum")
    if context.risk_reward < policy.min_risk_reward:
        reasons.append("risk_reward_below_minimum")
    if context.requested_leverage > policy.max_leverage:
        reasons.append("leverage_above_maximum")
    if context.daily_realized_loss_percent >= policy.max_daily_loss_percent:
        reasons.append("daily_loss_limit_reached")
    if context.open_positions >= policy.max_open_positions:
        reasons.append("max_open_positions_reached")
    if context.event_blocked is True:
        reasons.append("high_impact_event_guard")
    elif context.event_blocked is None and readiness_sensitive:
        reasons.append("event_context_missing")
    if not context.market_data_quality_ok:
        reasons.append("market_data_quality_insufficient")
    try:
        _positive(context.balance, "balance")
        _positive(context.equity, "equity")
    except ValueError:
        reasons.append("account_context_missing")
    return RiskDecision(approved=not reasons, reasons=tuple(reasons))


def size_position(
    context: FullRiskContext,
    policy: RiskPolicy,
    entry_price: float,
    stop_loss: float,
    *,
    target_risk_percent: float = 0.5,
) -> PositionSize:
    """Calculate a policy-capped quantity; no caller/AI quantity is accepted."""
    _positive(context.balance, "balance")
    _positive(context.equity, "equity")
    _positive(entry_price, "entry_price")
    _positive(stop_loss, "stop_loss")
    _positive(target_risk_percent, "target_risk_percent")
    stop_distance = abs(entry_price - stop_loss)
    _positive(stop_distance, "stop_distance")
    risk_percent = min(target_risk_percent, policy.max_risk_percent)
    risk_amount = context.balance * risk_percent / 100
    max_notional = context.balance * policy.max_leverage
    raw_quantity = risk_amount / stop_distance
    quantity = min(raw_quantity, max_notional / entry_price)
    if not isfinite(quantity) or quantity <= 0:
        raise ValueError("position quantity is invalid")
    return PositionSize(
        quantity=quantity,
        risk_amount=risk_amount,
        risk_percent=risk_percent,
        stop_distance=stop_distance,
        max_notional=max_notional,
    )
