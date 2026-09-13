from pydantic import ValidationError
import pytest

from btc_core.ai.models import AIProvider
from btc_core.ai.multi_agent.models import AgentRole, RoleAssignment, RolloutMode


def test_agent_roles_are_stable_and_complete():
    assert [role.value for role in AgentRole] == [
        "TECHNICAL",
        "MOMENTUM",
        "ORDER_FLOW",
        "NEWS",
        "CONTRARIAN",
        "RISK_REVIEW",
    ]


def test_role_assignment_rejects_non_positive_weight():
    with pytest.raises(ValidationError):
        RoleAssignment(
            role=AgentRole.TECHNICAL,
            provider=AIProvider.GEMINI,
            model="gemini-test",
            base_weight=0,
            prompt_version="v1",
        )


def test_rollout_mode_values_are_stable():
    assert [mode.value for mode in RolloutMode] == ["OFF", "SHADOW", "PRIMARY"]
