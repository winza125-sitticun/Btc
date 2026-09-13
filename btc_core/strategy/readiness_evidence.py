"""Bounded, sanitized production evidence for the strategy-worker readiness stage."""
from __future__ import annotations

from typing import Any

from .readiness import ReadinessEvidence
from .repository import StrategyRepositoryError, SupabaseStrategyRepository


class ReadinessEvidenceRepository(SupabaseStrategyRepository):
    """Strategy-worker repository with conservative readiness evidence collection.

    Reads only bounded operational fields. Missing/unreadable evidence is converted
    to conservative defaults so readiness can persist NOT_READY instead of failing
    the whole stage. No secrets, raw prompts, provider bodies, or reason text are
    selected or persisted by this collector.
    """

    async def _read_rows(
        self,
        path: str,
        *,
        select: str,
        limit: int,
        **filters: str,
    ) -> tuple[list[dict[str, Any]], bool]:
        params = {"select": select, "limit": str(limit), **filters}
        try:
            response = await self._request("GET", path, params=params)
            payload = response.json()
        except (StrategyRepositoryError, ValueError, TypeError):
            return [], False
        if not isinstance(payload, list):
            return [], False
        return [row for row in payload if isinstance(row, dict)], True

    async def readiness_evidence(self) -> ReadinessEvidence:
        attempts, attempts_ok = await self._read_rows(
            "/ai_agent_attempts",
            select="status,error_code,latency_ms,created_at",
            limit=200,
            order="created_at.desc",
        )
        scanner_runs, scanner_ok = await self._read_rows(
            "/market_scanner_runs",
            select="failure_count,started_at,completed_at",
            limit=20,
            order="started_at.desc",
        )
        accounts, accounts_ok = await self._read_rows(
            "/market_simulation_accounts",
            select="name,starting_balance,balance,equity,updated_at",
            limit=1,
            name="eq.Production Canary",
        )
        alerts, alerts_ok = await self._read_rows(
            "/market_alert_events",
            select="id,created_at",
            limit=1,
            order="created_at.desc",
        )
        intents, intents_ok = await self._read_rows(
            "/market_order_intents",
            select="mode,exchange_submission_allowed,validation_status,created_at",
            limit=100,
            order="created_at.desc",
        )

        attempt_count = len(attempts)
        success_count = sum(1 for row in attempts if str(row.get("status") or "").upper() == "SUCCESS")
        invalid_count = sum(
            1
            for row in attempts
            if str(row.get("error_code") or "").upper().startswith("INVALID_SCHEMA")
        )
        latencies = sorted(
            int(value)
            for row in attempts
            for value in [row.get("latency_ms")]
            if isinstance(value, int) and value >= 0
        )
        p95_latency_ms = None
        if latencies:
            rank = max(0, min(len(latencies) - 1, ((95 * len(latencies) + 99) // 100) - 1))
            p95_latency_ms = latencies[rank]

        success_rate = None if attempt_count == 0 else (success_count / attempt_count) * 100
        invalid_response_rate = None if attempt_count == 0 else (invalid_count / attempt_count) * 100

        scanner_isolation_healthy = bool(scanner_runs) and scanner_ok and all(
            row.get("completed_at") is not None
            and isinstance(row.get("failure_count"), int)
            and row.get("failure_count") == 0
            for row in scanner_runs
        )

        simulation_account_healthy = False
        if accounts_ok and len(accounts) == 1 and accounts[0].get("name") == "Production Canary":
            try:
                simulation_account_healthy = all(
                    float(accounts[0].get(field)) > 0
                    for field in ("starting_balance", "balance", "equity")
                )
            except (TypeError, ValueError):
                simulation_account_healthy = False

        critical_integrity_failures = 0
        if intents_ok:
            critical_integrity_failures = sum(
                1
                for row in intents
                if str(row.get("mode") or "").upper() != "DRY_RUN"
                or row.get("exchange_submission_allowed") is not False
            )

        return ReadinessEvidence(
            provider_reachable=attempts_ok and attempt_count > 0,
            model_reachable=attempts_ok and success_count > 0,
            attempts=attempt_count,
            success_rate=success_rate,
            invalid_response_rate=invalid_response_rate,
            p95_latency_ms=p95_latency_ms,
            scanner_isolation_healthy=scanner_isolation_healthy,
            # A service-role REST read cannot prove RLS policy correctness.
            migrations_rls_healthy=False,
            simulation_account_healthy=simulation_account_healthy,
            # Presence of SHADOW risk evidence does not prove full account-context risk is enabled.
            full_risk_enabled=False,
            # A successful read alone does not prove alert write/delivery persistence.
            alert_persistence_healthy=alerts_ok and bool(alerts),
            critical_integrity_failures=critical_integrity_failures,
            exchange_eligibility_blocked=True,
            private_credentials_configured=False,
        )
