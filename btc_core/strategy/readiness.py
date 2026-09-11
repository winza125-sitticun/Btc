"""Deterministic, fail-closed production readiness evaluation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field

CheckStatus = Literal["PASS", "FAIL", "PENDING"]
ReadinessStatus = Literal["NOT_READY", "PAPER_READY", "LIVE_READY", "BLOCKED"]


class ReadinessCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: CheckStatus
    evidence: Any = None
    reason: str | None = None


class ReadinessEvidence(BaseModel):
    """Sanitized observations used by the evaluator; no secrets or config values."""
    model_config = ConfigDict(extra="forbid")
    provider_reachable: bool = False
    model_reachable: bool = True
    attempts: int = Field(default=0, ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=100)
    invalid_response_rate: float | None = Field(default=None, ge=0, le=100)
    p95_latency_ms: int | None = Field(default=None, ge=0)
    scanner_isolation_healthy: bool = False
    migrations_rls_healthy: bool = False
    simulation_account_healthy: bool = False
    full_risk_enabled: bool = False
    alert_persistence_healthy: bool = False
    critical_integrity_failures: int = Field(default=0, ge=0)
    validation_days: int = Field(default=0, ge=0)
    closed_full_quality_trades: int = Field(default=0, ge=0)
    net_expectancy: float | None = None
    profit_factor: float | None = Field(default=None, ge=0)
    max_drawdown_percent: float | None = Field(default=None, ge=0)
    reconciliation_errors: int = Field(default=0, ge=0)
    guards_verified: bool = False
    kill_switch_verified: bool = False
    consecutive_valid_dry_run_intents: int = Field(default=0, ge=0)
    dry_run_schema_risk_failures: int = Field(default=0, ge=0)
    exchange_eligibility_blocked: bool = True
    private_credentials_configured: bool = False


class ReadinessSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    overall_status: ReadinessStatus
    mandatory_checks: dict[str, ReadinessCheck]
    evidence_window: dict[str, Any] = Field(default_factory=dict)
    metrics_snapshot: dict[str, Any] = Field(default_factory=dict)
    blocking_reasons: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def status(self) -> ReadinessStatus:
        return self.overall_status

    @property
    def state(self) -> ReadinessStatus:
        return self.overall_status


def _check(ok: bool, evidence: Any, reason: str) -> ReadinessCheck:
    return ReadinessCheck(status="PASS" if ok else "FAIL", evidence=evidence, reason=None if ok else reason)


def evaluate_readiness(evidence: ReadinessEvidence | Mapping[str, Any] | None = None, **observations: Any) -> ReadinessSnapshot:
    """Evaluate readiness without network calls, AI calls, or configuration mutation."""
    if evidence is None:
        evidence = observations
    elif observations:
        raise TypeError("pass evidence or keyword observations, not both")
    if not isinstance(evidence, ReadinessEvidence):
        evidence = ReadinessEvidence.model_validate(dict(evidence))
    checks: dict[str, ReadinessCheck] = {
        "provider_model_reachable": _check(evidence.provider_reachable and evidence.model_reachable, evidence.provider_reachable and evidence.model_reachable, "provider_model_unreachable"),
        "ai_attempts": _check(evidence.attempts >= 20, evidence.attempts, "ai_attempts_below_20"),
        "ai_success_rate": _check(evidence.success_rate is not None and evidence.success_rate >= 95, evidence.success_rate, "ai_success_rate_below_95"),
        "ai_p95_latency": _check(evidence.p95_latency_ms is not None and evidence.p95_latency_ms <= 10_000, evidence.p95_latency_ms, "ai_p95_latency_above_10s"),
        "scanner_isolation": _check(evidence.scanner_isolation_healthy, evidence.scanner_isolation_healthy, "scanner_isolation_unhealthy"),
        "migrations_rls": _check(evidence.migrations_rls_healthy, evidence.migrations_rls_healthy, "migrations_or_rls_unhealthy"),
        "simulation_account": _check(evidence.simulation_account_healthy, evidence.simulation_account_healthy, "simulation_account_unhealthy"),
        "full_risk_enabled": _check(evidence.full_risk_enabled, evidence.full_risk_enabled, "full_risk_disabled"),
        "alert_persistence": _check(evidence.alert_persistence_healthy, evidence.alert_persistence_healthy, "alert_persistence_unhealthy"),
        "critical_integrity": _check(evidence.critical_integrity_failures == 0, evidence.critical_integrity_failures, "critical_integrity_failures"),
    }
    live = {
        "validation_days": _check(evidence.validation_days >= 7, evidence.validation_days, "validation_days_below_7"),
        "live_ai_attempts": _check(evidence.attempts >= 200, evidence.attempts, "live_ai_attempts_below_200"),
        "live_success_rate": _check(evidence.success_rate is not None and evidence.success_rate >= 98, evidence.success_rate, "live_success_rate_below_98"),
        "invalid_response_rate": _check(evidence.invalid_response_rate is not None and evidence.invalid_response_rate <= 1, evidence.invalid_response_rate, "invalid_response_rate_above_1"),
        "closed_full_quality_trades": _check(evidence.closed_full_quality_trades >= 100, evidence.closed_full_quality_trades, "closed_full_quality_trades_below_100"),
        "positive_net_expectancy": _check(evidence.net_expectancy is not None and evidence.net_expectancy > 0, evidence.net_expectancy, "net_expectancy_not_positive"),
        "profit_factor": _check(evidence.profit_factor is not None and evidence.profit_factor >= 1.20, evidence.profit_factor, "profit_factor_below_1_20"),
        "max_drawdown": _check(evidence.max_drawdown_percent is not None and evidence.max_drawdown_percent <= 10, evidence.max_drawdown_percent, "max_drawdown_above_10"),
        "reconciliation": _check(evidence.reconciliation_errors == 0, evidence.reconciliation_errors, "reconciliation_errors"),
        "guards_verified": _check(evidence.guards_verified, evidence.guards_verified, "guards_not_verified"),
        "kill_switch": _check(evidence.kill_switch_verified, evidence.kill_switch_verified, "kill_switch_not_verified"),
        "dry_run_intents": _check(evidence.consecutive_valid_dry_run_intents >= 50 and evidence.dry_run_schema_risk_failures == 0, {"consecutive": evidence.consecutive_valid_dry_run_intents, "failures": evidence.dry_run_schema_risk_failures}, "dry_run_intent_evidence_insufficient"),
        "exchange_eligibility": _check(not evidence.exchange_eligibility_blocked, not evidence.exchange_eligibility_blocked, "exchange_eligibility_blocked"),
        "private_credentials_configured": _check(evidence.private_credentials_configured, evidence.private_credentials_configured, "private_credentials_not_configured"),
    }
    paper_checks = dict(checks)
    paper_pass = all(check.status == "PASS" for check in paper_checks.values())
    reasons = tuple(check.reason or name for name, check in paper_checks.items() if check.status == "FAIL")
    if evidence.critical_integrity_failures:
        status: ReadinessStatus = "BLOCKED"
        checks = paper_checks
    elif not paper_pass:
        status = "NOT_READY"
        checks = paper_checks
    elif not all(check.status == "PASS" for check in live.values()):
        status = "PAPER_READY"
        checks = paper_checks
        reasons = tuple(check.reason or name for name, check in live.items() if check.status == "FAIL")
    else:
        status = "LIVE_READY"
        checks = {**paper_checks, **live}
    return ReadinessSnapshot(overall_status=status, mandatory_checks=checks, blocking_reasons=reasons, evidence_window={"attempts": evidence.attempts, "validation_days": evidence.validation_days}, metrics_snapshot=evidence.model_dump(exclude={"provider_reachable", "model_reachable"}))


compute_readiness = evaluate_readiness
ReadinessResult = ReadinessSnapshot
