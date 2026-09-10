from btc_core.ai.analysis import precheck_ai_decision, validate_price_geometry
from btc_core.ai.models import AIDecision, AIProvider, Direction
from btc_core.risk.engine import RiskPolicy


def make_long(**updates):
    data = dict(
        provider=AIProvider.GEMINI,
        model="test-model",
        symbol="BTCUSDT",
        timeframe="15m",
        direction=Direction.LONG,
        confidence=82,
        entry_min=100,
        entry_max=101,
        stop_loss=97,
        take_profits=[104, 108],
        risk_reward=2.4,
        reason_summary="Structured test decision.",
    )
    data.update(updates)
    return AIDecision(**data)


def test_long_geometry_requires_sl_below_full_entry_range_and_all_tps_above():
    assert validate_price_geometry(make_long()).valid is True
    invalid = make_long(stop_loss=100.5)
    assert validate_price_geometry(invalid).valid is False


def test_short_geometry_requires_all_tps_below_entry_and_sl_above():
    decision = make_long(
        direction=Direction.SHORT,
        entry_min=100,
        entry_max=101,
        stop_loss=104,
        take_profits=[98, 95],
    )
    assert validate_price_geometry(decision).valid is True


def test_wait_is_never_actionable():
    result = precheck_ai_decision(
        make_long(direction=Direction.WAIT),
        opportunity_score=90,
        policy=RiskPolicy(),
    )
    assert result.actionable is False
    assert "wait_direction" in result.reasons


def test_structurally_valid_signal_still_requires_full_risk_context():
    result = precheck_ai_decision(
        make_long(), opportunity_score=84, policy=RiskPolicy()
    )
    assert result.status == "FULL_RISK_CONTEXT_PENDING"
