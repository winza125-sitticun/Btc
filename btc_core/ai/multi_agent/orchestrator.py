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
    DashboardEventRecord,
    HesitationRecord,
    MultiAgentRepository,
    MultiAgentRunRecord,
    RiskResultRecord,
    RiskResultStatus,
    RunStatus,
)
from btc_core.ai.multi_agent.risk_gate import (
    MultiAgentRiskDecision,
    MultiAgentRiskPolicy,
    evaluate_multi_agent_risk,
)
from btc_core.ai.providers.base import AIProviderError
from btc_core.risk.engine import RiskPolicy
from btc_core.strategy.risk import FullRiskContext


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
    risk: MultiAgentRiskDecision


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

    async def _event(
        self,
        *,
        run_id: str,
        sequence: int,
        event_type: str,
        status: str,
        message: str,
        role=None,
        metadata_safe: dict | None = None,
    ) -> int:
        await self._repository.append_event(
            DashboardEventRecord(
                multi_agent_run_id=run_id,
                sequence=sequence,
                event_type=event_type,
                role=role,
                status=status,
                message=message,
                metadata_safe=metadata_safe or {},
                created_at=_utcnow(),
            )
        )
        return sequence + 1

    async def orchestrate(
        self,
        *,
        run: MultiAgentRunRecord,
        config: FrozenConfigSnapshot,
        snapshot_envelope: FrozenSnapshotEnvelope,
        historical_weights: Mapping[object, float],
        full_risk_context: FullRiskContext | None = None,
        full_risk_policy: RiskPolicy | None = None,
    ) -> MultiAgentOrchestrationResult:
        if run.config_version != config.config_version:
            raise ValueError("run config_version must match frozen config")
        if run.snapshot_ref != snapshot_envelope.snapshot_ref:
            raise ValueError("run snapshot_ref must match frozen snapshot")
        if run.enabled_role_count != len(config.assignments):
            raise ValueError("run enabled_role_count must match frozen assignments")

        await self._repository.ensure_config_snapshot(config)
        run_id = await self._repository.create_run(run)
        sequence = await self._event(
            run_id=run_id,
            sequence=1,
            event_type="RUN_STARTED",
            status=RunStatus.RUNNING.value,
            message="Multi-agent run started",
            metadata_safe={
                "symbol": run.symbol,
                "timeframe": run.timeframe,
                "enabled_role_count": run.enabled_role_count,
                "rollout_mode": run.rollout_mode.value,
                "config_version": run.config_version,
                "snapshot_ref": run.snapshot_ref,
            },
        )

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
        for attempt in attempts:
            sequence = await self._event(
                run_id=run_id,
                sequence=sequence,
                event_type="AGENT_ATTEMPT",
                status=attempt.status.value,
                message=f"{attempt.role.value} attempt {attempt.status.value.lower()}",
                role=attempt.role,
                metadata_safe={
                    "attempt_id": attempt.attempt_id,
                    "provider": attempt.provider.value,
                    "model": attempt.model,
                    "direction": attempt.direction.value if attempt.direction else None,
                    "confidence": attempt.confidence,
                },
            )

        consensus = build_consensus(attempts, config, historical_weights)
        consensus_id = await self._repository.append_consensus(
            ConsensusRecord(
                multi_agent_run_id=run_id,
                decision=consensus,
                created_at=_utcnow(),
            )
        )
        sequence = await self._event(
            run_id=run_id,
            sequence=sequence,
            event_type="CONSENSUS",
            status="ACTIONABLE" if consensus.actionable else "WAIT",
            message=f"Consensus {consensus.direction.value}",
            metadata_safe={
                "consensus_id": consensus_id,
                "direction": consensus.direction.value,
                "consensus_confidence": consensus.consensus_confidence,
                "winning_agreement": consensus.winning_agreement,
                "coverage": consensus.coverage,
                "actionable": consensus.actionable,
                "reason_codes": list(consensus.reason_codes),
            },
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
        sequence = await self._event(
            run_id=run_id,
            sequence=sequence,
            event_type="HESITATION",
            status="RECORDED",
            message="Hesitation factors recorded",
            metadata_safe={
                "total": hesitation.total,
                "disagreement": hesitation.disagreement,
                "confidence_dispersion": hesitation.confidence_dispersion,
                "timeframe_conflict": hesitation.timeframe_conflict,
                "market_uncertainty": hesitation.market_uncertainty,
            },
        )

        risk = evaluate_multi_agent_risk(
            consensus=consensus,
            hesitation=hesitation,
            snapshot_envelope=snapshot_envelope,
            policy=MultiAgentRiskPolicy.from_config(config),
            full_risk_context=full_risk_context,
            full_risk_policy=full_risk_policy,
        )
        await self._repository.append_risk_result(
            RiskResultRecord(
                multi_agent_run_id=run_id,
                consensus_id=consensus_id,
                status=risk.status,
                approved=risk.approved,
                reason_codes=risk.reason_codes,
                risk_policy_version=risk.risk_policy_version,
                created_at=_utcnow(),
            )
        )
        risk_event_type = {
            RiskResultStatus.APPROVED: "RISK_APPROVED",
            RiskResultStatus.REJECTED: "RISK_REJECTED",
            RiskResultStatus.PENDING: "RISK_PENDING",
        }[risk.status]
        sequence = await self._event(
            run_id=run_id,
            sequence=sequence,
            event_type=risk_event_type,
            status=risk.status.value,
            message=f"Deterministic risk {risk.status.value.lower()}",
            metadata_safe={
                "approved": risk.approved,
                "reason_codes": list(risk.reason_codes),
                "risk_policy_version": risk.risk_policy_version,
            },
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
        await self._event(
            run_id=run_id,
            sequence=sequence,
            event_type="RUN_FINALIZED",
            status=status.value,
            message=f"Multi-agent run finalized as {status.value}",
            metadata_safe={
                "valid_role_count": valid_role_count,
                "enabled_role_count": len(config.assignments),
                "risk_status": risk.status.value,
            },
        )
        return MultiAgentOrchestrationResult(
            run_id=run_id,
            status=status,
            valid_role_count=valid_role_count,
            attempts=attempts,
            consensus=consensus,
            hesitation=hesitation,
            risk=risk,
        )