import asyncio
from datetime import datetime, timezone

import pytest

from btc_core.ai.analysis import AINewsContext, AIAnalysisSnapshot, TimeframeTechnicalContext
from btc_core.ai.models import AIDecision, AIProvider, Direction
from btc_core.ai.multi_agent.models import (
    AgentRole,
    FrozenConfigSnapshot,
    FrozenRoleAssignment,
    FrozenSnapshotEnvelope,
    VortexInputs,
)
from btc_core.ai.multi_agent.orchestrator import MultiAgentOrchestrator
from btc_core.ai.multi_agent.prompts import role_prompt
from btc_core.ai.multi_agent.repository import MultiAgentRunRecord, RunStatus
from btc_core.ai.providers.base import AIProviderError
from btc_core.scanner.scoring import OpportunityInputs


def _envelope() -> FrozenSnapshotEnvelope:
    technical = {
        "4h": TimeframeTechnicalContext(timeframe="4h", close=100, trend_percent=0.5, momentum_percent=1.0, recent_high=110, recent_low=90, recent_volume_ratio=1.2, direction=Direction.LONG),
        "1h": TimeframeTechnicalContext(timeframe="1h", close=100, trend_percent=0.4, momentum_percent=0.8, recent_high=105, recent_low=95, recent_volume_ratio=1.0, direction=Direction.LONG),
        "15m": TimeframeTechnicalContext(timeframe="15m", close=100, trend_percent=0.2, momentum_percent=0.3, recent_high=102, recent_low=98, recent_volume_ratio=0.8, direction=Direction.LONG),
    }
    snapshot = AIAnalysisSnapshot(
        symbol="BTCUSDT", timeframe="15m", scanner_direction=Direction.LONG,
        opportunity_score=70,
        components=OpportunityInputs(technical=80, momentum=70, volume=60, order_flow=50, open_interest=40, funding=50, liquidity=90, news=50, macro=50, risk_reward=50),
        last_price=100, funding_rate=0.0001, open_interest_change_percent=1.0,
        long_short_ratio=1.2, spread_percent=0.05,
        technical_by_timeframe=technical, news=AINewsContext(score=50, stories=()),
    )
    return FrozenSnapshotEnvelope(
        snapshot_ref="snap-t004",
        observed_at=datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc),
        snapshot=snapshot,
    )


def _config() -> FrozenConfigSnapshot:
    assignments = []
    for role in AgentRole:
        prompt = role_prompt(role)
        assignments.append(
            FrozenRoleAssignment(
                role=role,
                provider=AIProvider.GEMINI,
                model="model-test",
                base_weight=1.0,
                prompt_version=prompt.version,
                prompt_digest=prompt.digest,
                prompt_text=prompt.instruction,
            )
        )
    return FrozenConfigSnapshot(
        config_version="d" * 64,
        assignments=tuple(assignments),
        min_valid_roles=4,
    )


def _run(config: FrozenConfigSnapshot, envelope: FrozenSnapshotEnvelope) -> MultiAgentRunRecord:
    return MultiAgentRunRecord(
        id="run-t004",
        scanner_candidate_id=42,
        scanner_run_id="scanner-1",
        symbol=envelope.snapshot.symbol,
        timeframe=envelope.snapshot.timeframe,
        started_at=datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc),
        snapshot_ref=envelope.snapshot_ref,
        snapshot_observed_at=envelope.observed_at,
        config_version=config.config_version,
        enabled_role_count=len(config.assignments),
        rollout_mode=config.mode,
        market_context_summary=VortexInputs(
            trend_strength=0.8,
            volatility=0.4,
            momentum=0.6,
            order_flow_imbalance=0.2,
            liquidity=0.9,
            snapshot_ref=envelope.snapshot_ref,
            observed_at=envelope.observed_at,
        ),
    )


class RecordingRepository:
    def __init__(self):
        self.calls = []
        self.attempts = []
        self.finalized = None

    async def ensure_config_snapshot(self, config):
        self.calls.append("config")
        return config.config_version

    async def create_run(self, run):
        self.calls.append("run")
        return run.id

    async def append_attempt(self, attempt):
        self.calls.append(f"attempt:{attempt.role.value}")
        self.attempts.append(attempt)
        return len(self.attempts)

    async def append_consensus(self, consensus):
        self.calls.append("consensus")
        return 101

    async def append_hesitation(self, hesitation):
        self.calls.append("hesitation")
        return 201

    async def finalize_run(self, run_id, *, status, completed_at, valid_role_count):
        self.calls.append("finalize")
        self.finalized = (run_id, status, valid_role_count)


class RecordingInvoker:
    def __init__(self, *, failing_role=None):
        self.failing_role = failing_role
        self.requests = []
        self.active = 0
        self.max_active = 0

    async def invoke(self, assignment, request):
        self.requests.append((assignment, request))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.01)
            if assignment.role is self.failing_role:
                raise AIProviderError("upstream unavailable", code="UPSTREAM_5XX", status_code=503)
            return AIDecision(
                provider=assignment.provider,
                model=assignment.model,
                symbol=request.snapshot_envelope.snapshot.symbol,
                timeframe=request.snapshot_envelope.snapshot.timeframe,
                direction=Direction.LONG,
                confidence=75,
                entry_min=99,
                entry_max=101,
                stop_loss=95,
                take_profits=[105, 110],
                risk_reward=2.0,
                reason_summary=f"{assignment.role.value} evidence",
            )
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_orchestrator_uses_same_snapshot_role_prompts_bounded_concurrency_and_isolates_provider_failure():
    envelope = _envelope()
    config = _config()
    repository = RecordingRepository()
    invoker = RecordingInvoker(failing_role=AgentRole.NEWS)
    orchestrator = MultiAgentOrchestrator(
        repository=repository,
        invoker=invoker,
        max_concurrency=2,
    )

    result = await orchestrator.orchestrate(
        run=_run(config, envelope),
        config=config,
        snapshot_envelope=envelope,
        historical_weights={},
    )

    assert len(invoker.requests) == 6
    assert invoker.max_active <= 2
    assert {id(request.snapshot_envelope.snapshot) for _, request in invoker.requests} == {id(envelope.snapshot)}
    for assignment, request in invoker.requests:
        assert request.role is assignment.role
        assert request.prompt.instruction == assignment.prompt_text
        assert request.prompt.digest == assignment.prompt_digest

    assert len(repository.attempts) == 6
    failed = next(item for item in repository.attempts if item.role is AgentRole.NEWS)
    assert failed.status.value == "FAILED"
    assert failed.error_code == "UPSTREAM_5XX"
    assert failed.direction is None
    assert failed.confidence is None

    consensus_index = repository.calls.index("consensus")
    hesitation_index = repository.calls.index("hesitation")
    assert all(index < consensus_index for index, call in enumerate(repository.calls) if call.startswith("attempt:"))
    assert consensus_index < hesitation_index < repository.calls.index("finalize")
    assert repository.finalized == ("run-t004", RunStatus.PARTIAL, 5)
    assert result.status is RunStatus.PARTIAL
    assert result.valid_role_count == 5
    assert result.consensus.actionable is True
    assert result.hesitation.total >= 0
