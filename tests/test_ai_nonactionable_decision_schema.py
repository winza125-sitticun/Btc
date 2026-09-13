import pytest
from pydantic import ValidationError

from btc_core.ai.analysis import precheck_ai_decision
from btc_core.ai.models import AIDecision, AIProvider, Direction
from btc_core.risk.engine import RiskPolicy


def _base(**updates):
    data = {
        "provider": AIProvider.GEMINI,
        "model": "gemini-3.5-flash-lite",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "direction": Direction.WAIT,
        "confidence": 55,
        "reason_summary": "No actionable setup.",
    }
    data.update(updates)
    return data


def test_wait_accepts_omitted_trade_geometry_and_precheck_stays_fail_closed():
    decision = AIDecision(**_base())

    assert decision.entry_min is None
    assert decision.entry_max is None
    assert decision.stop_loss is None
    assert decision.take_profits == []
    assert decision.risk_reward is None

    result = precheck_ai_decision(
        decision,
        opportunity_score=90,
        policy=RiskPolicy(),
    )

    assert result.actionable is False
    assert result.status == "PRECHECK_FAILED"
    assert "wait_direction" in result.reasons


def test_wait_normalizes_zero_trade_geometry_to_empty_non_actionable_geometry():
    decision = AIDecision(
        **_base(
            entry_min=0,
            entry_max=0,
            stop_loss=0,
            take_profits=[],
            risk_reward=0,
        )
    )

    assert decision.entry_min is None
    assert decision.entry_max is None
    assert decision.stop_loss is None
    assert decision.take_profits == []
    assert decision.risk_reward is None


def test_long_still_rejects_missing_trade_geometry():
    with pytest.raises(ValidationError):
        AIDecision(**_base(direction=Direction.LONG, confidence=85))
