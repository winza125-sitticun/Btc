import pytest

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.consensus import build_consensus
from btc_core.ai.multi_agent.models import (
    AgentAttempt,
    AgentRole,
    AttemptStatus,
    FrozenConfigSnapshot,
    FrozenRoleAssignment,
)


def _assignment(role: AgentRole) -> FrozenRoleAssignment:
    return FrozenRoleAssignment(
        role=role,
        provider=AIProvider.GEMINI,
        model="model-test",
        base_weight=1.0,
        prompt_version="v1",
        prompt_digest="a" * 64,
        prompt_text="test prompt",
    )


def _config(*roles: AgentRole) -> FrozenConfigSnapshot:
    return FrozenConfigSnapshot(
        config_version="b" * 64,
        assignments=tuple(_assignment(role) for role in roles),
        min_valid_roles=4,
        min_coverage=0.67,
        min_agreement=0.60,
        min_signed_score=0.25,
    )


def _attempt(role: AgentRole, direction: Direction, confidence: float) -> AgentAttempt:
    return AgentAttempt(
        attempt_id=role.value.lower(),
        role=role,
        provider=AIProvider.GEMINI,
        model="model-test",
        status=AttemptStatus.SUCCESS,
        direction=direction,
        confidence=confidence,
    )


def test_consensus_uses_exact_weighted_equations_and_stable_reason_order():
    roles = (AgentRole.TECHNICAL, AgentRole.MOMENTUM, AgentRole.ORDER_FLOW, AgentRole.NEWS)
    result = build_consensus(
        (
            _attempt(AgentRole.TECHNICAL, Direction.LONG, 80),
            _attempt(AgentRole.MOMENTUM, Direction.LONG, 70),
            _attempt(AgentRole.ORDER_FLOW, Direction.SHORT, 60),
            _attempt(AgentRole.NEWS, Direction.WAIT, 50),
        ),
        _config(*roles),
        {role: 1.0 for role in roles},
    )

    assert result.direction is Direction.LONG
    assert result.coverage == pytest.approx(1.0)
    assert result.signed_score == pytest.approx(0.428571)
    assert result.winning_agreement == pytest.approx(0.714286)
    assert result.consensus_confidence == pytest.approx(75.0)
    assert result.actionable is True
    assert result.supporting_roles == (AgentRole.TECHNICAL, AgentRole.MOMENTUM)
    assert result.opposing_roles == (AgentRole.ORDER_FLOW, AgentRole.NEWS)
    assert result.reason_codes == ("WAIT_PRESENT", "ACTIONABLE_LONG")


def test_consensus_tie_is_wait_and_never_actionable():
    roles = (AgentRole.TECHNICAL, AgentRole.MOMENTUM, AgentRole.ORDER_FLOW, AgentRole.NEWS)
    result = build_consensus(
        (
            _attempt(AgentRole.TECHNICAL, Direction.LONG, 80),
            _attempt(AgentRole.MOMENTUM, Direction.SHORT, 80),
            _attempt(AgentRole.ORDER_FLOW, Direction.WAIT, 60),
            _attempt(AgentRole.NEWS, Direction.EXIT, 60),
        ),
        _config(*roles),
        {role: 1.0 for role in roles},
    )

    assert result.direction is Direction.WAIT
    assert result.winning_agreement == pytest.approx(0.5)
    assert result.consensus_confidence == pytest.approx(0.0)
    assert result.actionable is False
    assert result.supporting_roles == ()
    assert result.opposing_roles == roles
    assert result.reason_codes == ("DIRECTION_TIE", "WAIT_PRESENT", "EXIT_PRESENT")


def test_consensus_historical_multiplier_changes_exact_contribution():
    roles = (AgentRole.TECHNICAL, AgentRole.MOMENTUM, AgentRole.ORDER_FLOW, AgentRole.NEWS)
    result = build_consensus(
        tuple(_attempt(role, Direction.LONG, 50) for role in roles),
        _config(*roles),
        {AgentRole.TECHNICAL: 2.0},
    )

    technical = result.role_contributions[0]
    assert technical.role is AgentRole.TECHNICAL
    assert technical.historical_multiplier == pytest.approx(2.0)
    assert technical.effective_weight == pytest.approx(2.0)
    assert technical.unsigned_strength == pytest.approx(1.0)
    assert technical.signed_contribution == pytest.approx(1.0)
