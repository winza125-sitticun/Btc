from datetime import datetime, timezone

import pytest

from btc_core.ai.analysis import AINewsContext, AIAnalysisSnapshot, TimeframeTechnicalContext
from btc_core.ai.models import AIDecision, AIProvider, Direction
from btc_core.ai.multi_agent.models import AgentRole, FrozenConfigSnapshot, FrozenRoleAssignment, FrozenSnapshotEnvelope, VortexInputs
from btc_core.ai.multi_agent.orchestrator import MultiAgentOrchestrator
from btc_core.ai.multi_agent.repository import AttemptPersistenceStatus, MultiAgentRunRecord, RiskResultStatus, RunStatus
from btc_core.scanner.scoring import OpportunityInputs

NOW = datetime(2026, 9, 12, 16, 30, tzinfo=timezone.utc)


def _envelope():
    technical = {
        tf: TimeframeTechnicalContext(
            timeframe=tf, close=100, trend_percent=0.5, momentum_percent=0.5,
            recent_high=110, recent_low=90, recent_volume_ratio=1, direction=Direction.LONG,
        )
        for tf in ("4h", "1h", "15m")
    }
    return FrozenSnapshotEnvelope(
        snapshot_ref="prompt-integrity-snapshot",
        observed_at=NOW,
        snapshot=AIAnalysisSnapshot(
            symbol="BTCUSDT", timeframe="15m", scanner_direction=Direction.LONG,
            opportunity_score=90,
            components=OpportunityInputs(
                technical=90, momentum=90, volume=90, order_flow=90, open_interest=90,
                funding=90, liquidity=90, news=90, macro=90, risk_reward=90,
            ),
            last_price=100, funding_rate=0.0001, open_interest_change_percent=1,
            long_short_ratio=1.2, spread_percent=0.05,
            technical_by_timeframe=technical, news=AINewsContext(score=90, stories=()),
        ),
    )


class Repo:
    def __init__(self):
        self.attempts = []
        self.events = []
        self.finalized = None
    async def ensure_config_snapshot(self, config): return config.config_version
    async def create_run(self, run): return run.id
    async def append_attempt(self, attempt):
        self.attempts.append(attempt)
        return len(self.attempts)
    async def append_consensus(self, consensus): return 1
    async def append_hesitation(self, hesitation): return 2
    async def append_risk_result(self, risk): return 3
    async def append_event(self, event):
        self.events.append(event)
        return len(self.events)
    async def finalize_run(self, run_id, *, status, completed_at, valid_role_count):
        self.finalized = (status, valid_role_count)


class Invoker:
    async def invoke(self, assignment, request):
        return AIDecision(
            provider=assignment.provider, model=assignment.model,
            symbol="BTCUSDT", timeframe="15m", direction=Direction.LONG,
            confidence=90, entry_min=99, entry_max=101, stop_loss=95,
            take_profits=[105], risk_reward=3, reason_summary="should not be called",
        )


@pytest.mark.asyncio
async def test_prompt_integrity_failure_is_recorded_and_does_not_abort_run():
    envelope = _envelope()
    assignment = FrozenRoleAssignment(
        role=AgentRole.TECHNICAL,
        provider=AIProvider.GEMINI,
        model="gemini-test",
        base_weight=1,
        prompt_version="v1",
        prompt_digest="0" * 64,
        prompt_text="tampered prompt",
    )
    config = FrozenConfigSnapshot(
        config_version="c" * 64,
        assignments=(assignment,),
        min_valid_roles=1,
        min_coverage=1,
    )
    run = MultiAgentRunRecord(
        id="11111111-1111-4111-8111-111111111111",
        scanner_candidate_id=42,
        scanner_run_id="22222222-2222-4222-8222-222222222222",
        symbol="BTCUSDT",
        timeframe="15m",
        started_at=NOW,
        snapshot_ref=envelope.snapshot_ref,
        snapshot_observed_at=NOW,
        config_version=config.config_version,
        enabled_role_count=1,
        rollout_mode=config.mode,
        market_context_summary=VortexInputs(
            trend_strength=0.8, volatility=0.3, momentum=0.5,
            order_flow_imbalance=0.2, liquidity=0.9,
            snapshot_ref=envelope.snapshot_ref, observed_at=NOW,
        ),
    )
    repo = Repo()
    result = await MultiAgentOrchestrator(repository=repo, invoker=Invoker()).orchestrate(
        run=run,
        config=config,
        snapshot_envelope=envelope,
        historical_weights={},
    )

    assert result.status is RunStatus.INSUFFICIENT_EVIDENCE
    assert result.risk.status is RiskResultStatus.REJECTED
    assert len(repo.attempts) == 1
    assert repo.attempts[0].status is AttemptPersistenceStatus.INVALID_RESPONSE
    assert repo.attempts[0].error_code == "PROMPT_INTEGRITY"
    assert repo.finalized == (RunStatus.INSUFFICIENT_EVIDENCE, 0)
    assert any(event.event_type == "AGENT_ATTEMPT" and event.status == "INVALID_RESPONSE" for event in repo.events)
