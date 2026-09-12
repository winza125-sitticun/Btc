from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping

from btc_core.ai.models import AIProvider
from btc_core.ai.multi_agent.models import (
    AgentRole,
    FrozenConfigSnapshot,
    FrozenRoleAssignment,
    MultiAgentConfig,
    RoleAssignment,
    RolloutMode,
)
from btc_core.ai.multi_agent.prompts import role_prompt


logger = logging.getLogger(__name__)

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off", ""}


def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def resolve_multi_agent_mode(enabled_raw: str | None, mode_raw: str | None) -> RolloutMode:
    if not _parse_bool(enabled_raw, default=False):
        return RolloutMode.OFF
    normalized = (mode_raw or "").strip().upper()
    try:
        return RolloutMode(normalized)
    except ValueError:
        logger.warning("multi-agent rollout mode is missing or invalid; using OFF")
        return RolloutMode.OFF


def _float_value(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be numeric") from exc


def _int_value(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _assignment_from_env(env: Mapping[str, str], role: AgentRole) -> RoleAssignment | None:
    prefix = f"AI_ROLE_{role.value}_"
    provider_raw = (env.get(prefix + "PROVIDER") or "").strip().upper()
    model = (env.get(prefix + "MODEL") or "").strip()
    enabled_raw = env.get(prefix + "ENABLED")
    enabled = _parse_bool(enabled_raw, default=bool(provider_raw and model))
    if not enabled:
        return None
    if not provider_raw or not model:
        raise ValueError(f"{prefix}PROVIDER and {prefix}MODEL are required when the role is enabled")
    try:
        provider = AIProvider(provider_raw)
    except ValueError as exc:
        raise ValueError(f"unsupported provider for {role.value}") from exc
    prompt_version = (env.get(prefix + "PROMPT_VERSION") or "v1").strip()
    role_prompt(role, prompt_version)
    return RoleAssignment(
        role=role,
        provider=provider,
        model=model,
        base_weight=_float_value(env, prefix + "BASE_WEIGHT", 1.0),
        prompt_version=prompt_version,
    )


def load_multi_agent_config(env: Mapping[str, str]) -> MultiAgentConfig:
    mode = resolve_multi_agent_mode(env.get("AI_MULTI_AGENT_ENABLED"), env.get("AI_MULTI_AGENT_MODE"))
    assignments = tuple(
        assignment
        for role in AgentRole
        if (assignment := _assignment_from_env(env, role)) is not None
    )
    diagnostics: list[str] = []
    enabled_raw = env.get("AI_MULTI_AGENT_ENABLED")
    requested_mode = (env.get("AI_MULTI_AGENT_MODE") or "").strip().upper()
    if _parse_bool(enabled_raw, default=False) and requested_mode not in {item.value for item in RolloutMode}:
        diagnostics.append("INVALID_ROLLOUT_MODE_FAIL_CLOSED")
    return MultiAgentConfig(
        mode=mode,
        assignments=assignments,
        min_valid_roles=_int_value(env, "AI_MULTI_AGENT_MIN_VALID_ROLES", 4),
        min_coverage=_float_value(env, "AI_MULTI_AGENT_MIN_COVERAGE", 0.67),
        min_agreement=_float_value(env, "AI_MULTI_AGENT_MIN_AGREEMENT", 0.60),
        min_signed_score=_float_value(env, "AI_MULTI_AGENT_MIN_SIGNED_SCORE", 0.25),
        diagnostics=tuple(diagnostics),
    )


def _canonical_payload(config: MultiAgentConfig, assignments: tuple[FrozenRoleAssignment, ...]) -> dict[str, object]:
    return {
        "assignments": [item.model_dump(mode="json") for item in assignments],
        "min_valid_roles": config.min_valid_roles,
        "min_coverage": config.min_coverage,
        "min_agreement": config.min_agreement,
        "min_signed_score": config.min_signed_score,
        "decision_contract_version": config.decision_contract_version,
        "consensus_version": config.consensus_version,
        "hesitation_version": config.hesitation_version,
        "performance_version": config.performance_version,
        "market_context_mapping_version": config.market_context_mapping_version,
    }


def freeze_multi_agent_config(config: MultiAgentConfig) -> FrozenConfigSnapshot:
    frozen_assignments: list[FrozenRoleAssignment] = []
    by_role = {item.role: item for item in config.assignments}
    for role in AgentRole:
        assignment = by_role.get(role)
        if assignment is None:
            continue
        prompt = role_prompt(role, assignment.prompt_version)
        frozen_assignments.append(
            FrozenRoleAssignment(
                role=assignment.role,
                provider=assignment.provider,
                model=assignment.model,
                base_weight=assignment.base_weight,
                prompt_version=prompt.version,
                prompt_digest=prompt.digest,
                prompt_text=prompt.instruction,
            )
        )
    ordered = tuple(frozen_assignments)
    payload = _canonical_payload(config, ordered)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    version = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return FrozenConfigSnapshot(
        config_version=version,
        mode=config.mode,
        assignments=ordered,
        min_valid_roles=config.min_valid_roles,
        min_coverage=config.min_coverage,
        min_agreement=config.min_agreement,
        min_signed_score=config.min_signed_score,
        decision_contract_version=config.decision_contract_version,
        consensus_version=config.consensus_version,
        hesitation_version=config.hesitation_version,
        performance_version=config.performance_version,
        market_context_mapping_version=config.market_context_mapping_version,
    )
