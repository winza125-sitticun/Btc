from __future__ import annotations

from math import ceil
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field


MINIMUM_EXPANSION_SAMPLE = 20


class ProviderHealthSnapshot(BaseModel):
    """Immutable, provider-independent evidence for a canary rollout decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempts: int = Field(ge=0)
    successes: int = Field(ge=0)
    failures: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=100)
    invalid_response_rate: float = Field(ge=0, le=100)
    median_latency_ms: int | None = Field(default=None, ge=0)
    p95_latency_ms: int | None = Field(default=None, ge=0)
    scanner_failure_rate: float = Field(ge=0, le=100)
    status: Literal["INSUFFICIENT_SAMPLE", "HEALTHY", "DEGRADED"]
    can_expand: bool
    reasons: tuple[str, ...] = ()


def _median(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) // 2


def _p95(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[ceil(len(ordered) * 0.95) - 1]


def compute_provider_health(
    attempts: int,
    successes: int,
    invalid_responses: int,
    latencies_ms: Sequence[int],
    scanner_failures: int,
    scanner_cycles: int,
) -> ProviderHealthSnapshot:
    """Compute deterministic canary evidence without provider calls or persistence."""
    counts = (attempts, successes, invalid_responses, scanner_failures, scanner_cycles)
    if any(value < 0 for value in counts):
        raise ValueError("health counts must not be negative")
    if successes > attempts or invalid_responses > attempts:
        raise ValueError("success and invalid-response counts cannot exceed attempts")
    if any(value < 0 for value in latencies_ms):
        raise ValueError("latencies must not be negative")

    success_rate = (successes / attempts * 100) if attempts else 0.0
    invalid_response_rate = (invalid_responses / attempts * 100) if attempts else 0.0
    scanner_failure_rate = (scanner_failures / scanner_cycles * 100) if scanner_cycles else 0.0
    median_latency_ms = _median(latencies_ms)
    p95_latency_ms = _p95(latencies_ms)
    reasons: list[str] = []

    if attempts < MINIMUM_EXPANSION_SAMPLE:
        status: Literal["INSUFFICIENT_SAMPLE", "HEALTHY", "DEGRADED"] = "INSUFFICIENT_SAMPLE"
        reasons.append("minimum of 20 attempts required")
    elif success_rate < 90 or (p95_latency_ms is not None and p95_latency_ms > 20_000):
        status = "DEGRADED"
    else:
        status = "HEALTHY"

    if success_rate < 95:
        reasons.append("success rate below 95%")
    if invalid_response_rate > 2:
        reasons.append("invalid response rate above 2%")
    if p95_latency_ms is None:
        reasons.append("no latency observations")
    elif p95_latency_ms > 10_000:
        reasons.append("p95 latency exceeds 10000 ms")
    if scanner_failure_rate != 0:
        reasons.append("scanner failures observed")

    can_expand = (
        attempts >= MINIMUM_EXPANSION_SAMPLE
        and success_rate >= 95
        and invalid_response_rate <= 2
        and p95_latency_ms is not None
        and p95_latency_ms <= 10_000
        and scanner_failure_rate == 0
    )
    return ProviderHealthSnapshot(
        attempts=attempts,
        successes=successes,
        failures=attempts - successes,
        success_rate=success_rate,
        invalid_response_rate=invalid_response_rate,
        median_latency_ms=median_latency_ms,
        p95_latency_ms=p95_latency_ms,
        scanner_failure_rate=scanner_failure_rate,
        status=status,
        can_expand=can_expand,
        reasons=tuple(reasons),
    )
