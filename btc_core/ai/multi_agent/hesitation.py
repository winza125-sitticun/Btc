from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from statistics import pstdev

from btc_core.ai.models import Direction
from btc_core.ai.multi_agent.models import (
    AgentAttempt,
    AttemptStatus,
    ConsensusDecision,
    FrozenSnapshotEnvelope,
    HesitationSnapshot,
)

_QUANT = Decimal("0.000001")


def _q(value: float) -> float:
    return float(Decimal(str(value)).quantize(_QUANT, rounding=ROUND_HALF_UP))


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _pair_conflict(left: Direction, right: Direction) -> float:
    directional = {Direction.LONG, Direction.SHORT}
    if left in directional and right in directional:
        return 0.0 if left is right else 1.0
    if left is right:
        return 0.0
    return 0.5


def calculate_hesitation(
    attempts: tuple[AgentAttempt, ...] | list[AgentAttempt],
    consensus: ConsensusDecision,
    snapshot_envelope: FrozenSnapshotEnvelope,
) -> HesitationSnapshot:
    if "NO_DIRECTIONAL_EVIDENCE" in consensus.reason_codes:
        disagreement = 1.0
    else:
        disagreement = _clamp(1.0 - consensus.winning_agreement)
    disagreement = _q(disagreement)

    confidences = [float(item.confidence) for item in attempts if item.status is AttemptStatus.SUCCESS and item.confidence is not None]
    if len(confidences) < 2:
        confidence_dispersion = 0.0
    else:
        confidence_dispersion = _clamp(pstdev(confidences) / 50.0)
    confidence_dispersion = _q(confidence_dispersion)

    technical = snapshot_envelope.snapshot.technical_by_timeframe
    required = ("4h", "1h", "15m")
    missing = [timeframe for timeframe in required if timeframe not in technical]
    if missing:
        raise ValueError(f"missing technical timeframe(s): {', '.join(missing)}")
    pairs = (("4h", "1h"), ("4h", "15m"), ("1h", "15m"))
    timeframe_conflict = _q(sum(_pair_conflict(technical[left].direction, technical[right].direction) for left, right in pairs) / len(pairs))

    components = snapshot_envelope.snapshot.components
    quality_mean = (
        components.technical
        + components.momentum
        + components.volume
        + components.order_flow
        + components.open_interest
        + components.liquidity
    ) / 6.0
    market_uncertainty = _q(_clamp(1.0 - quality_mean / 100.0))

    disagreement_contribution = _q(100.0 * 0.40 * disagreement)
    confidence_dispersion_contribution = _q(100.0 * 0.20 * confidence_dispersion)
    timeframe_conflict_contribution = _q(100.0 * 0.25 * timeframe_conflict)
    market_uncertainty_contribution = _q(100.0 * 0.15 * market_uncertainty)
    total = _q(
        disagreement_contribution
        + confidence_dispersion_contribution
        + timeframe_conflict_contribution
        + market_uncertainty_contribution
    )

    return HesitationSnapshot(
        total=total,
        disagreement=disagreement,
        confidence_dispersion=confidence_dispersion,
        timeframe_conflict=timeframe_conflict,
        market_uncertainty=market_uncertainty,
        disagreement_contribution=disagreement_contribution,
        confidence_dispersion_contribution=confidence_dispersion_contribution,
        timeframe_conflict_contribution=timeframe_conflict_contribution,
        market_uncertainty_contribution=market_uncertainty_contribution,
        hesitation_algorithm_version="hesitation-v1",
    )
