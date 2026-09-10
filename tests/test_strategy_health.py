import pytest

from btc_core.strategy.health import compute_provider_health


def test_provider_health_passes_canary_gate():
    """A 95% successful, fast, isolated 20-attempt canary may expand."""
    result = compute_provider_health(
        attempts=20,
        successes=19,
        invalid_responses=0,
        latencies_ms=[2200] * 19,
        scanner_failures=0,
        scanner_cycles=20,
    )

    assert result.success_rate == 95.0
    assert result.invalid_response_rate == 0.0
    assert result.p95_latency_ms == 2200
    assert result.can_expand is True
    assert result.status == "HEALTHY"


def test_provider_health_degrades_below_90_percent_success():
    """A rolling 20-attempt success rate below 90% is degraded."""
    result = compute_provider_health(
        attempts=20,
        successes=17,
        invalid_responses=0,
        latencies_ms=[2000] * 17,
        scanner_failures=0,
        scanner_cycles=20,
    )

    assert result.status == "DEGRADED"
    assert result.can_expand is False


def test_provider_health_uses_nearest_rank_p95_and_integer_median():
    """Changing percentile selection or even-sample median handling breaks the health contract."""
    result = compute_provider_health(
        attempts=20,
        successes=20,
        invalid_responses=0,
        latencies_ms=[100, 200, 300, 400],
        scanner_failures=0,
        scanner_cycles=20,
    )

    assert result.median_latency_ms == 250
    assert result.p95_latency_ms == 400


def test_provider_health_never_expands_an_insufficient_sample():
    """Dropping the 20-attempt floor must not permit an early rollout expansion."""
    result = compute_provider_health(
        attempts=19,
        successes=19,
        invalid_responses=0,
        latencies_ms=[100] * 19,
        scanner_failures=0,
        scanner_cycles=19,
    )

    assert result.status == "INSUFFICIENT_SAMPLE"
    assert result.can_expand is False


def test_provider_health_never_expands_without_scanner_cycle_evidence():
    """Treating an absent scanner sample as a perfect zero-failure rate is unsafe."""
    result = compute_provider_health(
        attempts=20,
        successes=20,
        invalid_responses=0,
        latencies_ms=[100] * 20,
        scanner_failures=0,
        scanner_cycles=0,
    )

    assert result.scanner_failure_rate is None
    assert result.can_expand is False
    assert "no completed scanner cycles observed" in result.reasons


@pytest.mark.parametrize("latencies_ms", ([20_001] * 20,))
def test_provider_health_degrades_when_p95_exceeds_twenty_seconds(latencies_ms):
    """A slow provider is degraded even when its success count is perfect."""
    result = compute_provider_health(
        attempts=20,
        successes=20,
        invalid_responses=0,
        latencies_ms=latencies_ms,
        scanner_failures=0,
        scanner_cycles=20,
    )

    assert result.status == "DEGRADED"
    assert result.can_expand is False
