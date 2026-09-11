import pytest

from btc_core.risk.engine import RiskPolicy
from btc_core.strategy.order_intents import generate_order_intent
from btc_core.strategy.risk import FullRiskContext


def approved_context():
    return FullRiskContext(90, 90, 3, 3, 0, 0, False, 1000, 1000)


def setup(**overrides):
    value = dict(analysis_id=42, symbol="BTCUSDT", side="LONG", timeframe="15m",
                 entry_min=100, entry_max=101, stop_loss=95, take_profits=(110, 120),
                 confidence=90, opportunity_score=90, risk_reward=3)
    value.update(overrides)
    return value


def test_only_approved_setup_produces_fixed_dry_run_intent():
    intent = generate_order_intent(setup(), approved_context(), RiskPolicy())
    assert intent is not None
    assert intent.symbol == "BTCUSDT"
    assert intent.side == "LONG"
    assert intent.quantity > 0
    assert intent.leverage == 3
    assert intent.entry == (100, 101)
    assert intent.stop_loss == 95
    assert intent.take_profits == (110, 120)
    assert intent.mode == "DRY_RUN"
    assert intent.exchange_submission_allowed is False
    assert intent.risk_evidence["approved"] is True


def test_intent_is_idempotent_and_rejects_unsafe_states():
    first = generate_order_intent(setup(), approved_context(), RiskPolicy())
    second = generate_order_intent(setup(), approved_context(), RiskPolicy())
    assert first.idempotency_key == second.idempotency_key
    for changes in ({"side": "WAIT"}, {"full_risk_approved": False}, {"readiness_status": "BLOCKED"}):
        data = setup(**changes)
        if "readiness_status" in changes:
            assert generate_order_intent(data, approved_context(), RiskPolicy(), readiness_status=changes["readiness_status"]) is None
        else:
            assert generate_order_intent(data, approved_context(), RiskPolicy()) is None


def test_missing_account_or_precheck_failure_is_rejected():
    assert generate_order_intent(setup(), None, RiskPolicy()) is None
    assert generate_order_intent(setup(precheck_status="PRECHECK_FAILED"), approved_context(), RiskPolicy()) is None
