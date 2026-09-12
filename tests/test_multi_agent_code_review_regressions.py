import json
from datetime import datetime, timezone

import httpx
import pytest

from btc_core.ai.analysis import AINewsContext, AIAnalysisSnapshot, TimeframeTechnicalContext
from btc_core.ai.models import AIDecision, AIProvider, Direction
from btc_core.ai.multi_agent.models import (
    AgentRole,
    ConsensusDecision,
    FrozenConfigSnapshot,
    FrozenRoleAssignment,
    FrozenSnapshotEnvelope,
    HesitationSnapshot,
    VortexInputs,
)
from btc_core.ai.multi_agent.orchestrator import MultiAgentOrchestrator
from btc_core.ai.multi_agent.prompts import role_prompt
from btc_core.ai.multi_agent.repository import (
    DashboardEventRecord,
    MultiAgentRunRecord,
    RiskResultStatus,
    SupabaseMultiAgentRepository,
)
from btc_core.ai.multi_agent.risk_gate import MultiAgentRiskPolicy, evaluate_multi_agent_risk
from btc_core.risk.engine import RiskPolicy
from btc_core.scanner.scoring import OpportunityInputs
from btc_core.strategy.risk import FullRiskContext

NOW = datetime(2026, 9, 12, 16, 0, tzinfo=timezone.utc)
RUN_ID = "11111111-1111-4111-8111-111111111111"


def _envelope() -> FrozenSnapshotEnvelope:
    technical = {
        "4h": TimeframeTechnicalContext(timeframe="4h", close=100, trend_percent=0.5, momentum_percent=1.0, recent_high=110, recent_low=90, recent_volume_ratio=1.2, direction=Direction.LONG),
        "1h": TimeframeTechnicalContext(timeframe="1h", close=100, trend_percent=0.4, momentum_percent=0.8, recent_high=105, recent_low=95, recent_volume_ratio=1.0, direction=Direction.LONG),
        "15m": TimeframeTechnicalContext(timeframe="15m", close=100, trend_percent=0.2, momentum_percent=0.3, recent_high=102, recent_low=98, recent_volume_ratio=0.8, direction=Direction.LONG),
    }
    snapshot = AIAnalysisSnapshot(
        symbol="BTCUSDT",
        timeframe="15m",
        scanner_direction=Direction.LONG,
        opportunity_score=90,
        components=OpportunityInputs(
            technical=90,
            momentum=85,
            volume=80,
            order_flow=80,
            open_interest=80,
            funding=70,
            liquidity=90,
            news=70,
            macro=70,
            risk_reward=90,
        ),
        last_price=100,
        funding_rate=0.0001,
        open_interest_change_percent=1.0,
        long_short_ratio=1.2,
        spread_percent=0.05,
        technical_by_timeframe=technical,
        news=AINewsContext(score=70, stories=()),
    )
    return FrozenSnapshotEnvelope(snapshot_ref="review-snapshot", observed_at=NOW, snapshot=snapshot)


def _consensus() -> ConsensusDecision:
    return ConsensusDecision(
        direction=Direction.LONG,
        consensus_confidence=90,
        winning_agreement=1.0,
        coverage=1.0,
        signed_score=1.0,
        actionable=True,
        supporting_roles=(AgentRole.TECHNICAL,),
        reason_codes=("ACTIONABLE_LONG",),
        config_version="c" * 64,
    )


def _hesitation() -> HesitationSnapshot:
    return HesitationSnapshot(
        total=10,
        disagreement=0,
        confidence_dispersion=0,
        timeframe_conflict=0,
        market_uncertainty=0.1,
        disagreement_contribution=0,
        confidence_dispersion_contribution=0,
        timeframe_conflict_contribution=0,
        market_uncertainty_contribution=10,
    )


def _full_context(*, daily_loss: float = 0.0, event_blocked: bool | None = False) -> FullRiskContext:
    return FullRiskContext(
        confidence=1,
        opportunity_score=1,
        risk_reward=3,
        requested_leverage=2,
        daily_realized_loss_percent=daily_loss,
        open_positions=0,
        event_blocked=event_blocked,
        balance=1000,
        equity=1000,
    )


def test_multi_agent_risk_is_pending_without_complete_full_risk_context():
    result = evaluate_multi_agent_risk(
        consensus=_consensus(),
        hesitation=_hesitation(),
        snapshot_envelope=_envelope(),
        policy=MultiAgentRiskPolicy(),
        full_risk_context=None,
        full_risk_policy=RiskPolicy(),
    )

    assert result.status is RiskResultStatus.PENDING
    assert result.approved is False
    assert "FULL_RISK_CONTEXT_PENDING" in result.reason_codes


def test_multi_agent_risk_uses_existing_full_risk_engine_for_daily_loss_rejection():
    result = evaluate_multi_agent_risk(
        consensus=_consensus(),
        hesitation=_hesitation(),
        snapshot_envelope=_envelope(),
        policy=MultiAgentRiskPolicy(),
        full_risk_context=_full_context(daily_loss=3.0),
        full_risk_policy=RiskPolicy(),
    )

    assert result.status is RiskResultStatus.REJECTED
    assert result.approved is False
    assert "FULL_RISK_DAILY_LOSS_LIMIT_REACHED" in result.reason_codes


@pytest.mark.asyncio
async def test_persisted_event_metadata_redacts_secret_like_key_variants():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(201, json=[{"id": 1}])

    async with SupabaseMultiAgentRepository(
        supabase_url="https://project.supabase.co",
        api_key="service-role-value",
        transport=httpx.MockTransport(handler),
    ) as repo:
        await repo.append_event(
            DashboardEventRecord(
                multi_agent_run_id=RUN_ID,
                sequence=1,
                event_type="REVIEW",
                status="SUCCESS",
                message="sanitized",
                metadata_safe={
                    "safe": "ok",
                    "provider_api_key": "must-not-persist",
                    "password": "must-not-persist",
                    "credentials": {"token": "must-not-persist"},
                    "nested": {"auth_header": "must-not-persist", "keep": 1},
                },
                created_at=NOW,
            )
        )

    payload = json.loads(requests[-1].content)
    serialized = json.dumps(payload).lower()
    assert "must-not-persist" not in serialized
    assert payload["metadata_safe"] == {"safe": "ok", "nested": {"keep": 1}}


class _Repo:
    def __init__(self):
        self.events = []
        self.risk = None
        self.finalized = None

    async def ensure_config_snapshot(self, config):
        return config.config_version

    async def create_run(self, run):
        return run.id

    async def append_attempt(self, attempt):
        return 1

    async def append_consensus(self, consensus):
        return 2

    async def append_hesitation(self, hesitation):
        return 3

    async def append_risk_result(self, risk):
        self.risk = risk
        return 4

    async def append_event(self, event):
        self.events.append(event)
        return len(self.events)

    async def finalize_run(self, run_id, *, status, completed_at, valid_role_count):
        self.finalized = (run_id, status, valid_role_count)


class _Invoker:
    async def invoke(self, assignment, request):
        return AIDecision(
            provider=assignment.provider,
            model=assignment.model,
            symbol=request.snapshot_envelope.snapshot.symbol,
            timeframe=request.snapshot_envelope.snapshot.timeframe,
            direction=Direction.LONG,
            confidence=90,
            entry_min=99,
            entry_max=101,
            stop_loss=95,
            take_profits=[105],
            risk_reward=3,
            reason_summary="review fixture",
        )


@pytest.mark.asyncio
async def test_orchestrator_emits_sanitized_agent_consensus_hesitation_and_risk_events():
    prompt = role_prompt(AgentRole.TECHNICAL)
    config = FrozenConfigSnapshot(
        config_version="c" * 64,
        assignments=(
            FrozenRoleAssignment(
                role=AgentRole.TECHNICAL,
                provider=AIProvider.GEMINI,
                model="model-test",
                base_weight=1,
                prompt_version=prompt.version,
                prompt_digest=prompt.digest,
                prompt_text=prompt.instruction,
            ),
        ),
        min_valid_roles=1,
        min_coverage=1,
        min_agreement=0.5,
        min_signed_score=0.1,
    )
    envelope = _envelope()
    run = MultiAgentRunRecord(
        id=RUN_ID,
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
            trend_strength=0.8,
            volatility=0.3,
            momentum=0.5,
            order_flow_imbalance=0.2,
            liquidity=0.9,
            snapshot_ref=envelope.snapshot_ref,
            observed_at=NOW,
        ),
    )
    repo = _Repo()
    result = await MultiAgentOrchestrator(repository=repo, invoker=_Invoker()).orchestrate(
        run=run,
        config=config,
        snapshot_envelope=envelope,
        historical_weights={},
    )

    assert result.risk.status is RiskResultStatus.PENDING
    assert [event.event_type for event in repo.events] == [
        "RUN_STARTED",
        "AGENT_ATTEMPT",
        "CONSENSUS",
        "HESITATION",
        "RISK_PENDING",
        "RUN_FINALIZED",
    ]
    assert repo.events[-2].status == "PENDING"
    assert repo.events[-2].metadata_safe["approved"] is False
