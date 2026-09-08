import pytest
from pydantic import ValidationError

from btc_core.ai.models import AIDecision, AIProvider, Direction


def test_ai_decision_accepts_structured_long_signal():
    decision = AIDecision(
        provider=AIProvider.GEMINI,
        model="gemini-example",
        symbol="SOLUSDT",
        timeframe="15m",
        direction=Direction.LONG,
        confidence=82,
        entry_min=100,
        entry_max=101,
        stop_loss=97,
        take_profits=[104, 108],
        risk_reward=2.4,
        reason_summary="Trend and order flow agree.",
    )
    assert decision.direction is Direction.LONG
    assert decision.confidence == 82


def test_ai_decision_rejects_confidence_outside_0_100():
    with pytest.raises(ValidationError):
        AIDecision(
            provider=AIProvider.CLAUDE,
            model="claude-example",
            symbol="BTCUSDT",
            timeframe="1h",
            direction=Direction.SHORT,
            confidence=101,
            entry_min=100,
            entry_max=100,
            stop_loss=103,
            take_profits=[95],
            risk_reward=2.0,
            reason_summary="Invalid confidence should fail.",
        )
