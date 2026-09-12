from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Mapping, Protocol

from pydantic import BaseModel, ConfigDict

from btc_core.ai.models import AIDecision
from btc_core.ai.multi_agent.consensus import build_consensus
from btc_core.ai.multi_agent.hesitation import calculate_hesitation
from btc_core.ai.multi_agent.models import (
    AgentAttempt,
    AgentRequest,
    AttemptStatus,
    ConsensusDecision,
    FrozenConfigSnapshot,
    FrozenRoleAssignment,
    FrozenSnapshotEnvelope,
    HesitationSnapshot,
)
from btc_core.ai.multi_agent.prompts import role_prompt
from btc_core.ai.multi_agent.repository import (
    AgentAttemptRecord,
    AttemptPersistenceStatus,
    ConsensusRecord,
    HesitationRecord,
    MultiAgentRepository,
    MultiAgentRunRecord,
    RunStatus,
)
from btc_core.ai.providers.base import AIProviderError


class RoleAwareInvokerProtocol(Protocol):
    async def invoke(
        self,
        assignment: FrozenRoleAssignment,
        request: AgentRequest,
    ) -> AIDecision: ...


class MultiAgentOrchestrationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    status: RunStatus
    valid_role_count: int
    attempts: tuple[AgentAttempt, ...]
    consensus: ConsensusDecision
    hesitation: HesitationSnapshot


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _request_for(
    assignment: FrozenRoleAssignment,
    snapshot_envelope: FrozenSnapshotEnvelope,
) -> AgentRequest:
    prompt = role_prompt(assignment.role, assignment.prompt_version)
    if prompt.digest != assignment.prompt_digest or prompt.instruction != assignment.prompt_text:
        raise AIProviderError(
            "Frozen role prompt does not match the registered prompt bundle",
            code="PROMPT_INTEGRITY",
        )
    return AgentRequest(
        role=assignment.role,
        prompt=prompt,
        snapshot_envelope=snapshot_envelope,
    )


def _terminal_status(*, valid_role_count: int, enabled_role_count: int, min_valid_roles: int) -> RunStatus:
    if valid_role_count < min_valid_roles:
        return RunStatus.INSUFFICIENT_EVIDENCE
    if valid_role_count < enabled_role_count:
        return RunStatus.PARTIAL
    return RunStatus.COMPLETED


class MultiAgentOrchestrator:
    def __init__(
        self,
        *,
        repository: MultiAgentRepository,
        invoker: RoleAwareInvokerProtocol,
        max_concurrency: int = 3,
    ) -> None:
        if max_concurrency < 1 or max_concurrency > 6:
            raise ValueError("max_concurrency must be between 1 and 6")
        self._repository = repository
        self._invoker = invoker
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def _invoke_one(
        self,
        *,
        run_id: str,
        assignment: FrozenRoleAssignment,
        snapshot_envelope: FrozenSnapshotEnvelope,
    ) -> AgentAttempt:
        started = time.monotonic()
        request = _request_for(assignment, snapshot_envelope)
        decision: AIDecision | None = None
        persistence_status = AttemptPersistenceStatus.FAILED
        attempt_status = AttemptStatus.FAILED
        error_code: str | None = None
        error_message: str | None = None

        try:
            async with self._semaphore:
                decision = await self._invoker.invoke(assignment, request)
            snapshot = snapshot_envelope.snapshot
            if decision.provider is not assignment.provider or decision.model != assignment.model:
                raise AIProviderError(
                    "AI provider identity did not match the frozen role assignment",
                    code="INVALID_RESPONSE_IDENTITY",
                )
            if decision.symbol != snapshot.symbol or decision.timeframe != snapshot.timeframe:
                raise AIProviderError(
                    "AI decision did not match the frozen market snapshot",
                    code="INVALID_RESPONSE_SNAPSHOT",
                )
            persistence_status = AttemptPersistenceStatus.SUCCESS
            attempt_status = AttemptStatus.SUCCESS
        except AIProviderError as exc:
            decision = None
            error_code = exc.code
            error_message = str(exc)[:500]
            if exc.code.startswith("INVALID_") or exc.code == "PROMPT_INTEGRITY":
                persistence_status = AttemptPersistenceStatus.INVALID_RESPONSE
                attempt_status = AttemptStatus.INVALID_RESPONSE
        except Exception:
            decision = None
            error_code = "UNEXPECTED_PROVIDER_ERROR"
            error_message = "Provider invocation failed unexpectedly"

        latency_ms = max(0, int(round((time.monotonic() - started) * 1000)))
        record = AgentAttemptRecord(
            multi_agent_run_id=run_id,
            role=assignment.role,
            provider=assignment.provider,
            model=assignment.model,
            prompt_version=assignment.prompt_version,
            prompt_digest=assignment.prompt_digest,
            status=persistence_status,
            direction=decision.direction if decision else None,
            confidence=decision.confidence if decision else None,
            entry_min=decision.entry_min if decision else None,
            entry_max=decision.entry_max if decision else None,
            stop_loss=decision.stop_loss if decision else None,
            take_profits=tuple(decision.take_profits) if decision else (),
            risk_reward=decision.risk_reward if decision else None,
            reason_summary=decision.reason_summary if decision else None,
            latency_ms=latency_ms,
            error_code=error_code,
            error_message=error_message,
            snapshot_ref=snapshot_envelope.snapshot_ref,
            created_at=_utcnow(),
        )
        persisted_id = await self._repository.append_attempt(record)
        return AgentAttempt(
            attempt_id=str(persisted_id),
            role=assignment.role,
            provider=assignment.provider,
            model=assignment.model,
            status=attempt_status,
            direction=decision.direction if decision else None,
            confidence=decision.confidence if decision else None,
        )

    async def orchestrate(
        self,
        *,
        run: MultiAgentRunRecord,
        config: FrozenConfigSnapshot,
        snapshot_envelope: FrozenSnapshotEnvelope,
        historical_weights: Mapping[object, float],
    ) -> MultiAgentOrchestrationResult:
        if run.config_version != config.config_version:
            raise ValueError("run config_version must match frozen config")
        if run.snapshot_ref != snapshot_envelope.snapshot_ref:
            raise ValueError("run snapshot_ref must match frozen snapshot")
        if run.enabled_role_count != len(config.assignments):
            raise ValueError("run enabled_role_count must match frozen assignments")

        await self._repository.ensure_config_snapshot(config)
        run_id = await self._repository.create_run(run)

        attempts = tuple(
            await asyncio.gather(
                *(
                    self._invoke_one(
                        run_id=run_id,
                        assignment=assignment,
                        snapshot_envelope=snapshot_envelope,
                    )
                    for assignment in config.assignments
                )
            )
        )
        consensus = build_consensus(attempts, config, historical_weights)
        consensus_id = await self._repository.append_consensus(
            ConsensusRecord(
                multi_agent_run_id=run_id,
                decision=consensus,
                created_at=_utcnow(),
            )
        )
        hesitation = calculate_hesitation(attempts, consensus, snapshot_envelope)
        await self._repository.append_hesitation(
            HesitationRecord(
                multi_agent_run_id=run_id,
                consensus_id=consensus_id,
                snapshot=hesitation,
                created_at=_utcnow(),
            )
        )

        valid_role_count = sum(item.status is AttemptStatus.SUCCESS for item in attempts)
        status = _terminal_status(
            valid_role_count=valid_role_count,
            enabled_role_count=len(config.assignments),
            min_valid_roles=config.min_valid_roles,
        )
        await self._repository.finalize_run(
            run_id,
            status=status,
            completed_at=_utcnow(),
            valid_role_count=valid_role_count,
        )
        return MultiAgentOrchestrationResult(
            run_id=run_id,
            status=status,
            valid_role_count=valid_role_count,
            attempts=attempts,
            consensus=consensus,
            hesitation=hesitation,
        )
