import json
from datetime import datetime, timezone

import httpx
import pytest

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.models import (
    AgentRole,
    ConsensusDecision,
    FrozenConfigSnapshot,
    FrozenRoleAssignment,
    HesitationSnapshot,
    RoleContribution,
    RolloutMode,
    VortexInputs,
)
from btc_core.ai.multi_agent.repository import (
    AgentAttemptRecord,
    AgentPerformanceSnapshot,
    AttemptPersistenceStatus,
    ConsensusRecord,
    DashboardEventRecord,
    DecisionOutcomeRecord,
    HesitationRecord,
    MultiAgentRunRecord,
    OutcomeState,
    RiskResultRecord,
    RiskResultStatus,
    RunStatus,
    SupabaseMultiAgentRepository,
    SupabaseMultiAgentRepositoryError,
)

RUN_ID = "11111111-1111-4111-8111-111111111111"
SCANNER_RUN_ID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 9, 12, 9, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64
CONFIG_VERSION = "b" * 64


def _config() -> FrozenConfigSnapshot:
    return FrozenConfigSnapshot(
        config_version=CONFIG_VERSION,
        mode=RolloutMode.SHADOW,
        assignments=(
            FrozenRoleAssignment(
                role=AgentRole.TECHNICAL,
                provider=AIProvider.GEMINI,
                model="gemini-test",
                base_weight=1.0,
                prompt_version="v1",
                prompt_digest=DIGEST,
                prompt_text="technical mandate",
            ),
        ),
        min_valid_roles=1,
        min_coverage=1.0,
    )


def _run() -> MultiAgentRunRecord:
    return MultiAgentRunRecord(
        id=RUN_ID,
        scanner_candidate_id=901,
        scanner_run_id=SCANNER_RUN_ID,
        symbol="BTCUSDT",
        timeframe="15m",
        started_at=NOW,
        snapshot_ref="snap-901",
        snapshot_observed_at=NOW,
        config_version=CONFIG_VERSION,
        enabled_role_count=1,
        rollout_mode=RolloutMode.SHADOW,
        market_context_summary=VortexInputs(
            trend_strength=0.8,
            volatility=0.4,
            momentum=0.2,
            order_flow_imbalance=0.1,
            liquidity=0.9,
            snapshot_ref="snap-901",
            observed_at=NOW,
        ),
    )


def _contribution() -> RoleContribution:
    return RoleContribution(
        role=AgentRole.TECHNICAL,
        provider=AIProvider.GEMINI,
        model="gemini-test",
        direction=Direction.LONG,
        confidence=80,
        base_weight=1.0,
        historical_multiplier=1.0,
        effective_weight=1.0,
        unsigned_strength=0.8,
        signed_contribution=0.8,
        participated=True,
        attempt_id="1",
    )


def _consensus() -> ConsensusDecision:
    return ConsensusDecision(
        direction=Direction.LONG,
        consensus_confidence=80,
        winning_agreement=1.0,
        coverage=1.0,
        signed_score=1.0,
        actionable=True,
        supporting_roles=(AgentRole.TECHNICAL,),
        role_contributions=(_contribution(),),
        config_version=CONFIG_VERSION,
    )


def _hesitation() -> HesitationSnapshot:
    return HesitationSnapshot(
        total=10,
        disagreement=0,
        confidence_dispersion=0,
        timeframe_conflict=0.2,
        market_uncertainty=0.333333,
        disagreement_contribution=0,
        confidence_dispersion_contribution=0,
        timeframe_conflict_contribution=5,
        market_uncertainty_contribution=5,
    )


@pytest.mark.asyncio
async def test_repository_persists_evidence_in_order_and_finalizes_once():
    requests: list[httpx.Request] = []
    child_id = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal child_id
        requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/ai_multi_agent_configs"):
            return httpx.Response(201, json=[])
        if request.method == "POST" and request.url.path.endswith("/ai_multi_agent_runs"):
            return httpx.Response(201, json=[{"id": RUN_ID}])
        if request.method == "PATCH" and request.url.path.endswith("/ai_multi_agent_runs"):
            return httpx.Response(200, json=[{"id": RUN_ID}])
        if request.method == "POST":
            child_id += 1
            return httpx.Response(201, json=[{"id": child_id}])
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    async with SupabaseMultiAgentRepository(
        supabase_url="https://project.supabase.co",
        api_key="service-role-value",
        transport=httpx.MockTransport(handler),
    ) as repo:
        assert await repo.ensure_config_snapshot(_config()) == CONFIG_VERSION
        assert await repo.create_run(_run()) == RUN_ID
        attempt_id = await repo.append_attempt(
            AgentAttemptRecord(
                multi_agent_run_id=RUN_ID,
                role=AgentRole.TECHNICAL,
                provider=AIProvider.GEMINI,
                model="gemini-test",
                prompt_version="v1",
                prompt_digest=DIGEST,
                status=AttemptPersistenceStatus.SUCCESS,
                direction=Direction.LONG,
                confidence=80,
                entry_min=100,
                entry_max=101,
                stop_loss=98,
                take_profits=(103, 105),
                risk_reward=2.0,
                reason_summary="trend aligned",
                latency_ms=120,
                snapshot_ref="snap-901",
                created_at=NOW,
            )
        )
        consensus_id = await repo.append_consensus(
            ConsensusRecord(multi_agent_run_id=RUN_ID, decision=_consensus(), created_at=NOW)
        )
        await repo.append_hesitation(
            HesitationRecord(
                multi_agent_run_id=RUN_ID,
                consensus_id=consensus_id,
                snapshot=_hesitation(),
                created_at=NOW,
            )
        )
        await repo.append_risk_result(
            RiskResultRecord(
                multi_agent_run_id=RUN_ID,
                consensus_id=consensus_id,
                status=RiskResultStatus.APPROVED,
                approved=True,
                reason_codes=(),
                risk_policy_version="risk-v1",
                created_at=NOW,
            )
        )
        await repo.finalize_run(
            RUN_ID,
            status=RunStatus.COMPLETED,
            completed_at=NOW,
            valid_role_count=1,
        )

    assert attempt_id == 1
    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "ai_multi_agent_configs",
        "ai_multi_agent_runs",
        "ai_agent_attempts",
        "ai_consensus_decisions",
        "ai_hesitation_snapshots",
        "ai_multi_agent_risk_results",
        "ai_multi_agent_runs",
    ]
    finalize = requests[-1]
    assert finalize.url.params["id"] == f"eq.{RUN_ID}"
    assert finalize.url.params["status"] == "eq.RUNNING"
    assert json.loads(finalize.content) == {
        "completed_at": NOW.isoformat().replace("+00:00", "Z"),
        "status": "COMPLETED",
        "valid_role_count": 1,
    }


@pytest.mark.asyncio
async def test_finalize_run_rejects_when_database_reports_no_running_row():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json=[])

    async with SupabaseMultiAgentRepository(
        supabase_url="https://project.supabase.co",
        api_key="service-role-value",
        transport=httpx.MockTransport(handler),
    ) as repo:
        with pytest.raises(SupabaseMultiAgentRepositoryError, match="already terminal or missing"):
            await repo.finalize_run(
                RUN_ID,
                status=RunStatus.PARTIAL,
                completed_at=NOW,
                valid_role_count=1,
            )


@pytest.mark.asyncio
async def test_repository_appends_outcome_performance_and_sanitized_event_without_persisting_api_key():
    requests: list[httpx.Request] = []
    next_id = 10

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal next_id
        requests.append(request)
        next_id += 1
        return httpx.Response(201, json=[{"id": next_id}])

    async with SupabaseMultiAgentRepository(
        supabase_url="https://project.supabase.co",
        api_key="service-role-value",
        transport=httpx.MockTransport(handler),
    ) as repo:
        await repo.append_outcome(
            DecisionOutcomeRecord(
                multi_agent_run_id=RUN_ID,
                agent_attempt_id=None,
                horizon="1H",
                state=OutcomeState.PENDING,
                reference_price=100,
                matured_at=NOW,
                evaluated_at=None,
                market_regime="TRENDING",
                data_quality="MISSING",
            )
        )
        await repo.append_performance_snapshot(
            AgentPerformanceSnapshot(
                role=AgentRole.TECHNICAL,
                provider=AIProvider.GEMINI,
                model="gemini-test",
                as_of=NOW,
                horizon="1H",
                sample_count=20,
                hit_rate=0.6,
                mean_signed_return_pct=0.4,
                normalized_expectancy=0.2,
                quality_score=0.9,
                multiplier=1.1,
                performance_algorithm_version="performance-v1",
            )
        )
        await repo.append_event(
            DashboardEventRecord(
                multi_agent_run_id=RUN_ID,
                sequence=1,
                event_type="ROLE_COMPLETED",
                role=AgentRole.TECHNICAL,
                status="SUCCESS",
                message="technical complete",
                metadata_safe={
                    "safe": 1,
                    "authorization": "Bearer leaked-value",
                    "nested": {"api_key": "leaked-value", "safe2": 2},
                },
                created_at=NOW,
            )
        )

    serialized_bodies = "\n".join(request.content.decode() for request in requests)
    assert "service-role-value" not in serialized_bodies
    assert "leaked-value" not in serialized_bodies
    event_payload = json.loads(requests[-1].content)
    assert event_payload["metadata_safe"] == {"safe": 1, "nested": {"safe2": 2}}
