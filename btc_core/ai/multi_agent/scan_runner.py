from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from btc_core.ai.analysis import AIAnalysisSnapshot
from btc_core.ai.multi_agent.market_context import derive_market_context
from btc_core.ai.multi_agent.models import AgentRole, FrozenConfigSnapshot, FrozenSnapshotEnvelope, RolloutMode
from btc_core.ai.multi_agent.orchestrator import MultiAgentOrchestrator
from btc_core.ai.multi_agent.repository import MultiAgentRunRecord, RiskResultStatus
from btc_core.market.scanner import MarketScanResult, MarketScannerCandidate
from btc_core.market.supabase_repo import PersistedScanRef


SnapshotBuilder = Callable[[MarketScannerCandidate], Awaitable[AIAnalysisSnapshot]]
Clock = Callable[[], datetime]


class PerformanceServiceProtocol(Protocol):
    async def evaluate_mature_outcomes(self, as_of: datetime): ...
    async def historical_weight_for(self, role, provider, model: str, as_of: datetime) -> float: ...


class MultiAgentScanSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempted: int = Field(default=0, ge=0)
    approved: int = Field(default=0, ge=0)
    rejected: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MultiAgentScanRunner:
    def __init__(
        self,
        *,
        orchestrator: MultiAgentOrchestrator,
        config: FrozenConfigSnapshot,
        snapshot_builder: SnapshotBuilder,
        performance_service: PerformanceServiceProtocol | None = None,
        candidate_limit: int = 3,
        min_opportunity_score: float = 65.0,
        now: Clock = _utcnow,
    ) -> None:
        if not 1 <= candidate_limit <= 50:
            raise ValueError("candidate_limit must be between 1 and 50")
        if not 0 <= min_opportunity_score <= 100:
            raise ValueError("min_opportunity_score must be between 0 and 100")
        self._orchestrator = orchestrator
        self._config = config
        self._snapshot_builder = snapshot_builder
        self._performance_service = performance_service
        self._candidate_limit = candidate_limit
        self._min_opportunity_score = min_opportunity_score
        self._now = now

    async def _refresh_mature_outcomes(self, as_of: datetime) -> None:
        if self._performance_service is None:
            return
        try:
            await self._performance_service.evaluate_mature_outcomes(as_of)
        except Exception:
            # Historical evaluation is advisory to future weighting and must not
            # invalidate the scanner candidate currently being analyzed.
            return

    async def _historical_weights(self, as_of: datetime) -> dict[AgentRole, float]:
        if self._performance_service is None:
            return {}
        weights: dict[AgentRole, float] = {}
        for assignment in self._config.assignments:
            try:
                multiplier = await self._performance_service.historical_weight_for(
                    assignment.role,
                    assignment.provider,
                    assignment.model,
                    as_of,
                )
                multiplier = float(multiplier)
                if not 0.75 <= multiplier <= 1.25:
                    raise ValueError("historical multiplier outside locked range")
            except Exception:
                multiplier = 1.0
            weights[assignment.role] = multiplier
        return weights

    async def analyze_scan(
        self,
        result: MarketScanResult,
        persisted_scan: PersistedScanRef,
    ) -> MultiAgentScanSummary:
        if self._config.mode is RolloutMode.OFF:
            return MultiAgentScanSummary(skipped=len(result.candidates))

        refs = {(item.rank, item.symbol): item for item in persisted_scan.candidates}
        selected: list[tuple[MarketScannerCandidate, object]] = []
        skipped = 0
        for candidate in result.candidates:
            persisted = refs.get((candidate.rank, candidate.symbol))
            if persisted is None:
                skipped += 1
                continue
            if candidate.opportunity_score < self._min_opportunity_score:
                skipped += 1
                continue
            if len(selected) >= self._candidate_limit:
                skipped += 1
                continue
            selected.append((candidate, persisted))

        approved = 0
        rejected = 0
        pending = 0
        failed = 0
        performance_refreshed = False
        for candidate, persisted in selected:
            try:
                snapshot = await self._snapshot_builder(candidate)
                observed_at = self._now()
                if observed_at.tzinfo is None:
                    raise ValueError("scan runner clock must return a timezone-aware timestamp")
                if not performance_refreshed:
                    await self._refresh_mature_outcomes(observed_at)
                    performance_refreshed = True
                snapshot_ref = (
                    f"scan:{persisted_scan.run_id}:candidate:{persisted.id}:"
                    f"{observed_at.astimezone(timezone.utc).isoformat()}"
                )
                envelope = FrozenSnapshotEnvelope(
                    snapshot_ref=snapshot_ref,
                    observed_at=observed_at,
                    snapshot=snapshot,
                )
                market_context = derive_market_context(envelope)
                run = MultiAgentRunRecord(
                    id=str(uuid4()),
                    scanner_candidate_id=persisted.id,
                    scanner_run_id=persisted_scan.run_id,
                    symbol=candidate.symbol,
                    timeframe=candidate.timeframe,
                    started_at=observed_at,
                    snapshot_ref=snapshot_ref,
                    snapshot_observed_at=observed_at,
                    config_version=self._config.config_version,
                    enabled_role_count=len(self._config.assignments),
                    rollout_mode=self._config.mode,
                    market_context_summary=market_context,
                )
                historical_weights = await self._historical_weights(observed_at)
                outcome = await self._orchestrator.orchestrate(
                    run=run,
                    config=self._config,
                    snapshot_envelope=envelope,
                    historical_weights=historical_weights,
                )
                if outcome.risk.status is RiskResultStatus.APPROVED:
                    approved += 1
                elif outcome.risk.status is RiskResultStatus.PENDING:
                    pending += 1
                else:
                    rejected += 1
            except Exception:
                failed += 1

        return MultiAgentScanSummary(
            attempted=len(selected),
            approved=approved,
            rejected=rejected,
            pending=pending,
            failed=failed,
            skipped=skipped,
        )