from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

from btc_core.ai.analysis import AIAnalysisSnapshot, precheck_ai_decision
from btc_core.ai.models import AIDecision, AIProvider
from btc_core.ai.providers.base import AIProviderClientProtocol, AIProviderError
from btc_core.ai.supabase_repo import MarketAIAnalysisRecord
from btc_core.market.scanner import MarketScanResult, MarketScannerCandidate
from btc_core.market.supabase_repo import PersistedCandidateRef, PersistedScanRef
from btc_core.risk.engine import RiskPolicy


SnapshotBuilder = Callable[[MarketScannerCandidate], Awaitable[AIAnalysisSnapshot]]


class AIAnalysisRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    success: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)


class AIAnalysisRunner:
    def __init__(
        self,
        *,
        provider_client: AIProviderClientProtocol,
        analysis_repo,
        snapshot_builder: SnapshotBuilder,
        provider: AIProvider,
        model: str,
        candidate_limit: int = 3,
        concurrency: int = 2,
        min_opportunity_score: float = 65.0,
        policy: RiskPolicy | None = None,
    ) -> None:
        if not 1 <= candidate_limit <= 50:
            raise ValueError("candidate_limit must be between 1 and 50")
        if not 1 <= concurrency <= 20:
            raise ValueError("concurrency must be between 1 and 20")
        if not 0 <= min_opportunity_score <= 100:
            raise ValueError("min_opportunity_score must be between 0 and 100")
        if not model.strip():
            raise ValueError("model must not be blank")

        self._provider_client = provider_client
        self._analysis_repo = analysis_repo
        self._snapshot_builder = snapshot_builder
        self._provider = provider
        self._model = model.strip()
        self._candidate_limit = candidate_limit
        self._semaphore = asyncio.Semaphore(concurrency)
        self._min_opportunity_score = min_opportunity_score
        self._policy = policy or RiskPolicy()

    async def _persist(self, record: MarketAIAnalysisRecord) -> bool:
        try:
            await self._analysis_repo.persist(record)
            return True
        except asyncio.CancelledError:
            raise
        except Exception:
            return False

    def _base_record(
        self,
        candidate: MarketScannerCandidate,
        persisted: PersistedCandidateRef,
        run_id: str,
        *,
        status: str,
        **updates,
    ) -> MarketAIAnalysisRecord:
        return MarketAIAnalysisRecord(
            scanner_candidate_id=persisted.id,
            run_id=run_id,
            symbol=candidate.symbol,
            timeframe=candidate.timeframe,
            provider=self._provider,
            model=self._model,
            scanner_direction=candidate.direction,
            status=status,
            **updates,
        )

    def _matches_identity(self, decision: AIDecision, candidate: MarketScannerCandidate) -> bool:
        return (
            decision.provider is self._provider
            and decision.model == self._model
            and decision.symbol == candidate.symbol
            and decision.timeframe == candidate.timeframe
        )

    async def _analyze_one(
        self,
        candidate: MarketScannerCandidate,
        persisted: PersistedCandidateRef,
        run_id: str,
    ) -> str:
        started = time.monotonic()
        snapshot: AIAnalysisSnapshot | None = None
        async with self._semaphore:
            try:
                snapshot = await self._snapshot_builder(candidate)
                decision = await self._provider_client.analyze(snapshot)
            except asyncio.CancelledError:
                raise
            except AIProviderError as exc:
                elapsed = max(0, int((time.monotonic() - started) * 1000))
                invalid = exc.code in {"INVALID_JSON", "INVALID_SCHEMA"}
                diagnostic = f", status={exc.status_code}" if exc.status_code is not None else ""
                record = self._base_record(
                    candidate,
                    persisted,
                    run_id,
                    status="INVALID_RESPONSE" if invalid else "FAILED",
                    input_snapshot=(snapshot.model_dump(mode="json") if snapshot is not None else {}),
                    latency_ms=elapsed,
                    attempt_count=1,
                    error_code=exc.code,
                    error_message=f"AI provider failure ({exc.code}{diagnostic})",
                )
                await self._persist(record)
                return "failed"
            except Exception as exc:
                elapsed = max(0, int((time.monotonic() - started) * 1000))
                record = self._base_record(
                    candidate,
                    persisted,
                    run_id,
                    status="FAILED",
                    input_snapshot=(snapshot.model_dump(mode="json") if snapshot is not None else {}),
                    latency_ms=elapsed,
                    attempt_count=1,
                    error_code="ANALYSIS_ERROR",
                    error_message=f"AI analysis failed ({type(exc).__name__})",
                )
                await self._persist(record)
                return "failed"

        elapsed = max(0, int((time.monotonic() - started) * 1000))
        if not self._matches_identity(decision, candidate):
            await self._persist(
                self._base_record(
                    candidate,
                    persisted,
                    run_id,
                    status="INVALID_RESPONSE",
                    input_snapshot=snapshot.model_dump(mode="json"),
                    latency_ms=elapsed,
                    attempt_count=1,
                    error_code="IDENTITY_MISMATCH",
                    error_message="AI response identity did not match the requested candidate",
                )
            )
            return "failed"

        precheck = precheck_ai_decision(
            decision,
            opportunity_score=candidate.opportunity_score,
            policy=self._policy,
        )
        await self._persist(
            self._base_record(
                candidate,
                persisted,
                run_id,
                status="SUCCESS",
                ai_direction=decision.direction,
                confidence=decision.confidence,
                entry_min=decision.entry_min,
                entry_max=decision.entry_max,
                stop_loss=decision.stop_loss,
                take_profits=tuple(decision.take_profits[:3]),
                risk_reward=decision.risk_reward,
                reason_summary=decision.reason_summary,
                input_snapshot=snapshot.model_dump(mode="json"),
                risk_precheck_status=precheck.status,
                risk_precheck_reasons=precheck.reasons,
                latency_ms=elapsed,
                attempt_count=1,
            )
        )
        return "success"

    async def analyze_scan(
        self,
        result: MarketScanResult,
        persisted_scan: PersistedScanRef,
    ) -> AIAnalysisRunSummary:
        refs_by_key = {
            (item.rank, item.symbol): item for item in persisted_scan.candidates
        }
        selected: list[tuple[MarketScannerCandidate, PersistedCandidateRef]] = []
        skipped = 0

        for candidate in result.candidates:
            persisted = refs_by_key.get((candidate.rank, candidate.symbol))
            if persisted is None:
                skipped += 1
                continue

            skip_code: str | None = None
            if candidate.opportunity_score < self._min_opportunity_score:
                skip_code = "BELOW_OPPORTUNITY_THRESHOLD"
            elif len(selected) >= self._candidate_limit:
                skip_code = "CANDIDATE_LIMIT"

            if skip_code is not None:
                skipped += 1
                await self._persist(
                    self._base_record(
                        candidate,
                        persisted,
                        persisted_scan.run_id,
                        status="SKIPPED",
                        attempt_count=0,
                        error_code=skip_code,
                        error_message="AI analysis skipped by deterministic candidate filter",
                    )
                )
                continue

            selected.append((candidate, persisted))

        outcomes = await asyncio.gather(
            *(
                self._analyze_one(candidate, persisted, persisted_scan.run_id)
                for candidate, persisted in selected
            )
        )
        return AIAnalysisRunSummary(
            success=sum(outcome == "success" for outcome in outcomes),
            failed=sum(outcome == "failed" for outcome in outcomes),
            skipped=skipped,
        )
