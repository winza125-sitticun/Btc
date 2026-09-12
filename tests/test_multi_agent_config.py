from btc_core.ai.multi_agent.config import load_multi_agent_config, resolve_multi_agent_mode
from btc_core.ai.multi_agent.models import AgentRole, RolloutMode


def test_rollout_precedence_is_fail_closed():
    assert resolve_multi_agent_mode(None, "PRIMARY") is RolloutMode.OFF
    assert resolve_multi_agent_mode("false", "PRIMARY") is RolloutMode.OFF
    assert resolve_multi_agent_mode("true", "OFF") is RolloutMode.OFF
    assert resolve_multi_agent_mode("true", "SHADOW") is RolloutMode.SHADOW
    assert resolve_multi_agent_mode("true", "PRIMARY") is RolloutMode.PRIMARY
    assert resolve_multi_agent_mode("true", "") is RolloutMode.OFF
    assert resolve_multi_agent_mode("true", "BROKEN") is RolloutMode.OFF


def test_config_snapshot_contains_no_secrets_and_has_required_versions():
    cfg = load_multi_agent_config({
        "AI_MULTI_AGENT_ENABLED": "true",
        "AI_MULTI_AGENT_MODE": "SHADOW",
        "AI_ROLE_TECHNICAL_PROVIDER": "GEMINI",
        "AI_ROLE_TECHNICAL_MODEL": "gemini-test",
        "AI_ROLE_TECHNICAL_BASE_WEIGHT": "1.25",
        "GEMINI_API_KEY": "never-persist-me",
    })
    frozen = cfg.to_frozen_snapshot()
    body = frozen.model_dump_json()
    assert "never-persist-me" not in body
    assert frozen.mode is RolloutMode.SHADOW
    assert frozen.min_valid_roles == 4
    assert frozen.min_coverage == 0.67
    assert frozen.min_agreement == 0.60
    assert frozen.min_signed_score == 0.25
    assert frozen.decision_contract_version == "aid-v1"
    assert frozen.consensus_version == "consensus-v1"
    assert frozen.hesitation_version == "hesitation-v1"
    assert frozen.performance_version == "performance-v1"
    assert frozen.market_context_mapping_version == "vortex-input-v1"
    assignment = next(item for item in frozen.assignments if item.role is AgentRole.TECHNICAL)
    assert assignment.model == "gemini-test"
    assert assignment.base_weight == 1.25
    assert assignment.prompt_version == "v1"
    assert assignment.prompt_digest
    assert assignment.prompt_text


def test_config_version_ignores_secret_value_but_tracks_sanitized_config():
    base = {
        "AI_MULTI_AGENT_ENABLED": "true",
        "AI_MULTI_AGENT_MODE": "SHADOW",
        "AI_ROLE_TECHNICAL_PROVIDER": "GEMINI",
        "AI_ROLE_TECHNICAL_MODEL": "gemini-test",
    }
    first = load_multi_agent_config({**base, "GEMINI_API_KEY": "secret-a"}).to_frozen_snapshot()
    second = load_multi_agent_config({**base, "GEMINI_API_KEY": "secret-b"}).to_frozen_snapshot()
    changed = load_multi_agent_config({**base, "AI_ROLE_TECHNICAL_MODEL": "gemini-other", "GEMINI_API_KEY": "secret-a"}).to_frozen_snapshot()
    assert first.config_version == second.config_version
    assert first.config_version != changed.config_version
    assert len(first.config_version) == 64
