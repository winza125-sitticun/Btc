import asyncio

import pytest

from btc_core.strategy.readiness import ReadinessEvidence, evaluate_readiness
from services.strategy_worker.app.main import StrategyWorker


def paper_evidence(**overrides):
    values = dict(
        provider_reachable=True, attempts=20, success_rate=95.0, invalid_response_rate=0.0,
        p95_latency_ms=10_000, scanner_isolation_healthy=True, migrations_rls_healthy=True,
        simulation_account_healthy=True, full_risk_enabled=True, alert_persistence_healthy=True,
        critical_integrity_failures=0,
    )
    values.update(overrides)
    return ReadinessEvidence(**values)


def live_evidence(**overrides):
    values = dict(
        validation_days=7, attempts=200, success_rate=98.0, invalid_response_rate=1.0,
        closed_full_quality_trades=100, net_expectancy=0.01, profit_factor=1.20,
        max_drawdown_percent=10.0, reconciliation_errors=0, guards_verified=True,
        kill_switch_verified=True, consecutive_valid_dry_run_intents=50,
        dry_run_schema_risk_failures=0, exchange_eligibility_blocked=False,
        private_credentials_configured=True,
    )
    values.update(overrides)
    return paper_evidence(**values)


def test_paper_ready_requires_all_mandatory_checks():
    result = evaluate_readiness(paper_evidence())
    assert result.overall_status == "PAPER_READY"
    assert all(check.status == "PASS" for check in result.mandatory_checks.values())


def test_live_ready_requires_stricter_operational_and_performance_evidence():
    result = evaluate_readiness(live_evidence())
    assert result.overall_status == "LIVE_READY"
    assert "private_credentials_configured" in result.mandatory_checks


@pytest.mark.parametrize("field,value", [("attempts", 19), ("success_rate", 94.9), ("p95_latency_ms", 10_001), ("closed_full_quality_trades", 99)])
def test_insufficient_evidence_fails_closed(field, value):
    evidence = live_evidence(**{field: value})
    result = evaluate_readiness(evidence)
    assert result.overall_status in {"NOT_READY", "PAPER_READY"}
    assert result.overall_status != "LIVE_READY"
    assert result.blocking_reasons


def test_blocked_status_is_reserved_for_integrity_or_explicit_block():
    result = evaluate_readiness(paper_evidence(critical_integrity_failures=1))
    assert result.overall_status == "BLOCKED"
    assert "critical_integrity_failures" in result.blocking_reasons


def test_readiness_snapshots_are_immutable():
    result = evaluate_readiness(paper_evidence())
    with pytest.raises((TypeError, AttributeError, ValueError)):
        result.overall_status = "LIVE_READY"


def test_worker_runs_readiness_after_alerts_and_isolates_failure():
    events = []

    class Repository:
        async def refresh_metrics(self): events.append("refresh_metrics")
        async def derive_alerts(self): events.append("derive_alerts")
        async def evaluate_readiness(self): events.append("evaluate_readiness"); raise RuntimeError("readiness")

    worker = StrategyWorker(repository=Repository(), market_client=object(), enabled=True, alerts_enabled=True, readiness_enabled=True)
    result = asyncio.run(worker.run_cycle())
    assert events == ["refresh_metrics", "derive_alerts", "evaluate_readiness"]
    assert result.errors == (("evaluate_readiness", "RuntimeError"),)
