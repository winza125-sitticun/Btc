from btc_core.ai.multi_agent.models import AgentRole
from btc_core.ai.multi_agent.prompts import ROLE_INSTRUCTIONS_V1, role_prompt


def test_same_provider_different_roles_have_distinct_prompts():
    tech = role_prompt(AgentRole.TECHNICAL)
    news = role_prompt(AgentRole.NEWS)
    assert tech.version == "v1"
    assert news.version == "v1"
    assert tech.instruction != news.instruction
    assert tech.digest != news.digest


def test_all_roles_have_versioned_nonempty_prompt_and_sha256_digest():
    for role in AgentRole:
        prompt = role_prompt(role)
        assert prompt.role is role
        assert prompt.version == "v1"
        assert prompt.instruction == ROLE_INSTRUCTIONS_V1[role]
        assert prompt.required_focus
        assert prompt.safety_constraints
        assert len(prompt.digest) == 64
        int(prompt.digest, 16)


def test_risk_review_prompt_is_advisory_and_cannot_authorize_trade():
    instruction = role_prompt(AgentRole.RISK_REVIEW).instruction.lower()
    assert "advisory" in instruction
    assert "can never approve" in instruction
    assert "authorize" in instruction
