from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Mapping

from btc_core.ai.models import Direction
from btc_core.ai.multi_agent.models import (
    AgentAttempt,
    AgentRole,
    AttemptStatus,
    ConsensusDecision,
    FrozenConfigSnapshot,
    RoleContribution,
)

_QUANT = Decimal("0.000001")
_ROLE_ORDER = {role: index for index, role in enumerate(AgentRole)}


def _q(value: float) -> float:
    return float(Decimal(str(value)).quantize(_QUANT, rounding=ROUND_HALF_UP))


def _historical_multiplier(weights: Mapping[object, float], role: AgentRole) -> float:
    raw = weights.get(role, weights.get(role.value, 1.0))
    return max(0.0, float(raw))


def build_consensus(
    attempts: tuple[AgentAttempt, ...] | list[AgentAttempt],
    config: FrozenConfigSnapshot,
    historical_weights: Mapping[object, float],
) -> ConsensusDecision:
    assignment_by_role = {item.role: item for item in config.assignments}
    enabled_roles = tuple(role for role in AgentRole if role in assignment_by_role)

    success_by_role: dict[AgentRole, AgentAttempt] = {}
    for attempt in attempts:
        if attempt.status is AttemptStatus.SUCCESS and attempt.role in assignment_by_role and attempt.role not in success_by_role:
            success_by_role[attempt.role] = attempt

    contributions: list[RoleContribution] = []
    for role in enabled_roles:
        assignment = assignment_by_role[role]
        attempt = success_by_role.get(role)
        multiplier = _q(_historical_multiplier(historical_weights, role))
        effective_weight = _q(assignment.base_weight * multiplier)
        unsigned_strength = 0.0
        signed_contribution = 0.0
        direction = attempt.direction if attempt else None
        confidence = attempt.confidence if attempt else None
        if attempt and direction in {Direction.LONG, Direction.SHORT} and confidence is not None:
            unsigned_strength = _q(effective_weight * confidence / 100.0)
            signed_contribution = unsigned_strength if direction is Direction.LONG else _q(-unsigned_strength)
        contributions.append(
            RoleContribution(
                role=role,
                provider=assignment.provider,
                model=assignment.model,
                direction=direction,
                confidence=confidence,
                base_weight=_q(assignment.base_weight),
                historical_multiplier=multiplier,
                effective_weight=effective_weight,
                unsigned_strength=unsigned_strength,
                signed_contribution=signed_contribution,
                participated=attempt is not None,
                attempt_id=attempt.attempt_id if attempt else None,
            )
        )

    valid_attempts = tuple(success_by_role[role] for role in enabled_roles if role in success_by_role)
    valid_role_count = len(valid_attempts)
    enabled_role_count = len(enabled_roles)
    coverage = _q(valid_role_count / enabled_role_count) if enabled_role_count else 0.0

    long_strength = _q(sum(item.unsigned_strength for item in contributions if item.direction is Direction.LONG))
    short_strength = _q(sum(item.unsigned_strength for item in contributions if item.direction is Direction.SHORT))
    total_directional_strength = _q(long_strength + short_strength)
    signed_score = _q((long_strength - short_strength) / total_directional_strength) if total_directional_strength > 0 else 0.0

    provisional: Direction | None = None
    if total_directional_strength <= 0:
        winning_agreement = 0.0
        consensus_confidence = 0.0
    elif long_strength == short_strength:
        winning_agreement = 0.5
        consensus_confidence = 0.0
    else:
        provisional = Direction.LONG if long_strength > short_strength else Direction.SHORT
        winning_strength = long_strength if provisional is Direction.LONG else short_strength
        winning_agreement = _q(winning_strength / total_directional_strength)
        winners = [item for item in contributions if item.participated and item.direction is provisional and item.confidence is not None]
        denominator = sum(item.effective_weight for item in winners)
        numerator = sum(item.effective_weight * float(item.confidence) for item in winners)
        consensus_confidence = _q(numerator / denominator) if denominator > 0 else 0.0

    valid_roles_in_order = tuple(role for role in AgentRole if role in success_by_role)
    if provisional is None:
        supporting_roles: tuple[AgentRole, ...] = ()
        opposing_roles = valid_roles_in_order
    else:
        supporting_roles = tuple(role for role in AgentRole if role in success_by_role and success_by_role[role].direction is provisional)
        opposite = Direction.SHORT if provisional is Direction.LONG else Direction.LONG
        opposing_roles = tuple(
            role
            for role in AgentRole
            if role in success_by_role and success_by_role[role].direction in {opposite, Direction.WAIT, Direction.EXIT}
        )

    enough_roles = valid_role_count >= config.min_valid_roles
    enough_coverage = coverage >= config.min_coverage
    enough_agreement = provisional is not None and winning_agreement >= config.min_agreement
    enough_signed_score = provisional is not None and abs(signed_score) >= config.min_signed_score
    actionable = bool(provisional is not None and enough_roles and enough_coverage and enough_agreement and enough_signed_score)

    reasons: list[str] = []
    if not enough_roles:
        reasons.append("INSUFFICIENT_VALID_ROLES")
    if not enough_coverage:
        reasons.append("INSUFFICIENT_COVERAGE")
    if total_directional_strength <= 0:
        reasons.append("NO_DIRECTIONAL_EVIDENCE")
    elif long_strength == short_strength:
        reasons.append("DIRECTION_TIE")
    if provisional is not None and not enough_agreement:
        reasons.append("LOW_AGREEMENT")
    if provisional is not None and not enough_signed_score:
        reasons.append("LOW_SIGNED_SCORE")
    if any(item.direction is Direction.WAIT for item in valid_attempts):
        reasons.append("WAIT_PRESENT")
    if any(item.direction is Direction.EXIT for item in valid_attempts):
        reasons.append("EXIT_PRESENT")
    if actionable and provisional is Direction.LONG:
        reasons.append("ACTIONABLE_LONG")
    if actionable and provisional is Direction.SHORT:
        reasons.append("ACTIONABLE_SHORT")

    return ConsensusDecision(
        direction=provisional if actionable and provisional is not None else Direction.WAIT,
        consensus_confidence=consensus_confidence,
        winning_agreement=winning_agreement,
        coverage=coverage,
        signed_score=signed_score,
        actionable=actionable,
        supporting_roles=supporting_roles,
        opposing_roles=opposing_roles,
        reason_codes=tuple(reasons),
        role_contributions=tuple(contributions),
        config_version=config.config_version,
        consensus_algorithm_version=config.consensus_version,
    )
