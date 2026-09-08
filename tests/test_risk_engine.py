from btc_core.risk.engine import RiskInputs, RiskPolicy, evaluate_risk


def valid_inputs(**overrides):
    data = dict(
        confidence=82,
        opportunity_score=84,
        risk_reward=2.5,
        leverage=3,
        risk_percent=0.8,
        daily_loss_percent=0.5,
        open_positions=1,
        high_impact_event_blocked=False,
    )
    data.update(overrides)
    return RiskInputs(**data)


def test_risk_engine_approves_signal_meeting_all_policy_rules():
    result = evaluate_risk(valid_inputs(), RiskPolicy())
    assert result.approved is True
    assert result.reasons == ()


def test_risk_engine_rejects_event_guard_even_when_signal_is_strong():
    result = evaluate_risk(valid_inputs(high_impact_event_blocked=True), RiskPolicy())
    assert result.approved is False
    assert "high_impact_event_guard" in result.reasons


def test_risk_engine_reports_all_failed_limits():
    result = evaluate_risk(
        valid_inputs(
            confidence=60,
            opportunity_score=60,
            risk_reward=1.2,
            leverage=10,
            risk_percent=2,
            daily_loss_percent=4,
            open_positions=3,
        ),
        RiskPolicy(),
    )
    assert result.approved is False
    assert set(result.reasons) == {
        "confidence_below_minimum",
        "opportunity_score_below_minimum",
        "risk_reward_below_minimum",
        "leverage_above_maximum",
        "risk_per_trade_above_maximum",
        "daily_loss_limit_reached",
        "max_open_positions_reached",
    }
