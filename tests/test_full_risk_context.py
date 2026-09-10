import math
import pytest

from btc_core.risk.engine import RiskDecision, RiskPolicy
from btc_core.strategy.risk import FullRiskContext, PositionSize, evaluate_full_risk, size_position


def context(**overrides):
    values = dict(
        confidence=82.0,
        opportunity_score=84.0,
        risk_reward=2.5,
        requested_leverage=3.0,
        daily_realized_loss_percent=0.5,
        open_positions=1,
        event_blocked=False,
        balance=10_000.0,
        equity=10_000.0,
        market_data_quality_ok=True,
    )
    values.update(overrides)
    return FullRiskContext(**values)


def test_full_risk_approves_valid_context_and_uses_default_half_percent_target():
    decision = evaluate_full_risk(context(), RiskPolicy())
    assert decision.approved is True
    sized = size_position(context(), RiskPolicy(), entry_price=100.0, stop_loss=95.0)
    assert sized.risk_amount == pytest.approx(50.0)
    assert sized.quantity == pytest.approx(10.0)


@pytest.mark.parametrize("field", ["confidence", "opportunity_score", "risk_reward"])
def test_full_risk_rejects_below_hard_signal_thresholds(field):
    assert evaluate_full_risk(context(**{field: 0}), RiskPolicy()).approved is False


def test_full_risk_rejects_leverage_daily_loss_positions_and_event():
    result = evaluate_full_risk(context(requested_leverage=6, daily_realized_loss_percent=3, open_positions=3, event_blocked=True), RiskPolicy())
    assert set(result.reasons) >= {"leverage_above_maximum", "daily_loss_limit_reached", "max_open_positions_reached", "high_impact_event_guard"}


@pytest.mark.parametrize("field,value", [
    ("confidence", math.nan), ("opportunity_score", math.inf),
    ("risk_reward", -math.inf), ("requested_leverage", "5"),
    ("daily_realized_loss_percent", math.nan), ("balance", math.inf),
    ("equity", "10000"), ("open_positions", 1.5),
])
def test_full_risk_rejects_non_finite_or_non_numeric_context(field, value):
    result = evaluate_full_risk(context(**{field: value}), RiskPolicy())
    assert result.approved is False
    assert result.reasons == ("risk_context_invalid",)


def test_full_risk_requires_event_context_for_readiness_sensitive_evaluation():
    result = evaluate_full_risk(context(event_blocked=None), RiskPolicy(), readiness_sensitive=True)
    assert result.approved is False
    assert "event_context_missing" in result.reasons


def test_size_position_caps_risk_at_one_percent_and_notional_at_five_x():
    sized = size_position(context(), RiskPolicy(), entry_price=100.0, stop_loss=99.99, target_risk_percent=2.0)
    assert isinstance(sized, PositionSize)
    assert sized.risk_amount == pytest.approx(100.0)
    assert sized.quantity == pytest.approx(500.0)


@pytest.mark.parametrize("kwargs", [dict(balance=0), dict(equity=0), dict(balance=-1), dict(equity=-1)])
def test_size_position_rejects_invalid_account(kwargs):
    with pytest.raises(ValueError):
        size_position(context(**kwargs), RiskPolicy(), entry_price=100, stop_loss=90)


def test_size_position_rejects_zero_or_invalid_stop_distance():
    with pytest.raises(ValueError):
        size_position(context(), RiskPolicy(), entry_price=100, stop_loss=100)
    with pytest.raises(ValueError):
        size_position(context(), RiskPolicy(), entry_price=100, stop_loss=0)
