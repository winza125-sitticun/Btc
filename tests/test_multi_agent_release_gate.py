from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from btc_core.ai.analysis import AINewsContext, AIAnalysisSnapshot, TimeframeTechnicalContext
from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.config import load_multi_agent_config, resolve_multi_agent_mode
from btc_core.ai.multi_agent.consensus import build_consensus
from btc_core.ai.multi_agent.hesitation import calculate_hesitation
from btc_core.ai.multi_agent.models import AgentAttempt, AgentRole, AttemptStatus, FrozenSnapshotEnvelope, RolloutMode
from btc_core.ai.multi_agent.performance import EvaluationHorizon, MarketRegime, PerformanceEvidence, summarize_performance
from btc_core.ai.multi_agent.risk_gate import MultiAgentRiskPolicy, evaluate_multi_agent_risk
from btc_core.ai.multi_agent.repository import OutcomeState
from btc_core.risk.engine import RiskPolicy
from btc_core.scanner.scoring import OpportunityInputs
from btc_core.strategy.order_intents import EXCHANGE_SUBMISSION_ALLOWED, generate_order_intent
from btc_core.strategy.risk import FullRiskContext
from btc_core.strategy.simulation import AccountState, PaperTradeEngine, TradeSetup
from services.api.app.multi_agent_api import sanitize_multi_agent_public

RUN_ID = "11111111-1111-4111-8111-111111111111"
START = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


def _config_env() -> dict[str, str]:
    env = {
        "AI_MULTI_AGENT_ENABLED": "true",
        "AI_MULTI_AGENT_MODE": "PRIMARY",
        "AI_MULTI_AGENT_MIN_VALID_ROLES": "4",
        "AI_MULTI_AGENT_MIN_COVERAGE": "0.67",
        "AI_MULTI_AGENT_MIN_AGREEMENT": "0.60",
        "AI_MULTI_AGENT_MIN_SIGNED_SCORE": "0.25",
        "GEMINI_API_KEY": "release-gate-secret-must-not-leak",
    }
    for role in AgentRole:
        prefix = f"AI_ROLE_{role.value}_"
        env[prefix + "ENABLED"] = "true"
        env[prefix + "PROVIDER"] = "GEMINI"
        env[prefix + "MODEL"] = "gemini-release-fixture"
        env[prefix + "PROMPT_VERSION"] = "v1"
    return env


def _snapshot() -> FrozenSnapshotEnvelope:
    technical = {
        "4h": TimeframeTechnicalContext(timeframe="4h", close=100, trend_percent=1.2, momentum_percent=1.0, recent_high=110, recent_low=90, recent_volume_ratio=1.2, direction=Direction.LONG),
        "1h": TimeframeTechnicalContext(timeframe="1h", close=100, trend_percent=0.8, momentum_percent=0.7, recent_high=106, recent_low=95, recent_volume_ratio=1.1, direction=Direction.LONG),
        "15m": TimeframeTechnicalContext(timeframe="15m", close=100, trend_percent=0.4, momentum_percent=0.5, recent_high=103, recent_low=98, recent_volume_ratio=1.0, direction=Direction.LONG),
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
            order_flow=75,
            open_interest=80,
            funding=50,
            liquidity=90,
            news=70,
            macro=70,
            risk_reward=85,
        ),
        last_price=100,
        funding_rate=0.0001,
        open_interest_change_percent=1.0,
        long_short_ratio=1.2,
        spread_percent=0.05,
        technical_by_timeframe=technical,
        news=AINewsContext(score=70, stories=()),
    )
    return FrozenSnapshotEnvelope(snapshot_ref="release-snapshot-v1", observed_at=START, snapshot=snapshot)


def _attempt(role: AgentRole, direction: Direction | None, confidence: float | None, *, status: AttemptStatus = AttemptStatus.SUCCESS) -> AgentAttempt:
    return AgentAttempt(
        attempt_id=f"attempt-{role.value.lower()}",
        role=role,
        provider=AIProvider.GEMINI,
        model="gemini-release-fixture",
        status=status,
        direction=direction,
        confidence=confidence,
    )


def _attempts() -> tuple[AgentAttempt, ...]:
    return (
        _attempt(AgentRole.TECHNICAL, Direction.LONG, 90),
        _attempt(AgentRole.MOMENTUM, Direction.LONG, 85),
        _attempt(AgentRole.ORDER_FLOW, Direction.LONG, 80),
        _attempt(AgentRole.NEWS, Direction.WAIT, 55),
        _attempt(AgentRole.CONTRARIAN, Direction.SHORT, 60),
        _attempt(AgentRole.RISK_REVIEW, None, None, status=AttemptStatus.FAILED),
    )


def test_fixed_fixture_reconstructs_consensus_hesitation_risk_and_secrets():
    frozen = load_multi_agent_config(_config_env()).to_frozen_snapshot()
    attempts = _attempts()
    weights = {role: 1.0 for role in AgentRole}

    first = build_consensus(attempts, frozen, weights)
    second = build_consensus(attempts, frozen, weights)
    assert first == second
    assert first.direction is Direction.LONG
    assert first.actionable is True
    assert first.coverage == pytest.approx(5 / 6, abs=1e-6)
    assert first.supporting_roles == (AgentRole.TECHNICAL, AgentRole.MOMENTUM, AgentRole.ORDER_FLOW)
    assert first.opposing_roles == (AgentRole.NEWS, AgentRole.CONTRARIAN)

    directional = [item for item in first.role_contributions if item.direction in {Direction.LONG, Direction.SHORT}]
    long_strength = sum(item.unsigned_strength for item in directional if item.direction is Direction.LONG)
    short_strength = sum(item.unsigned_strength for item in directional if item.direction is Direction.SHORT)
    reconstructed_signed_score = (long_strength - short_strength) / (long_strength + short_strength)
    assert first.signed_score == pytest.approx(reconstructed_signed_score, abs=1e-6)

    prompt_digests = [item.prompt_digest for item in frozen.assignments]
    assert len(prompt_digests) == 6
    assert len(set(prompt_digests)) == 6

    hesitation = calculate_hesitation(attempts, first, _snapshot())
    reconstructed_hesitation = (
        hesitation.disagreement_contribution
        + hesitation.confidence_dispersion_contribution
        + hesitation.timeframe_conflict_contribution
        + hesitation.market_uncertainty_contribution
    )
    assert hesitation.total == pytest.approx(reconstructed_hesitation, abs=1e-6)

    risk = evaluate_multi_agent_risk(
        consensus=first,
        hesitation=hesitation,
        snapshot_envelope=_snapshot(),
        policy=MultiAgentRiskPolicy(min_opportunity_score=95),
    )
    assert risk.approved is False
    assert "OPPORTUNITY_SCORE_BELOW_MINIMUM" in risk.reason_codes

    serialized = frozen.model_dump_json()
    assert "release-gate-secret-must-not-leak" not in serialized
    public = sanitize_multi_agent_public({
        "api_key": "release-gate-secret-must-not-leak",
        "nested": {"authorization": "release-gate-secret-must-not-leak", "safe": "ok"},
        "secret_configured": True,
    })
    assert public == {"nested": {"safe": "ok"}, "secret_configured": True}


def test_point_in_time_weighting_excludes_future_maturity_and_keeps_cold_start():
    as_of = START + timedelta(days=10)
    rows = [
        PerformanceEvidence(
            multi_agent_run_id=f"run-{index}",
            agent_attempt_id=index + 1,
            role=AgentRole.TECHNICAL,
            provider=AIProvider.GEMINI,
            model="gemini-release-fixture",
            symbol="BTCUSDT",
            direction=Direction.LONG,
            market_regime=MarketRegime.BULL,
            horizon="1H",
            state=OutcomeState.EVALUATED,
            data_quality="FULL",
            matured_at=as_of - timedelta(days=1),
            directional_hit=True,
            signed_return_pct=2.0,
        )
        for index in range(29)
    ]
    rows.append(
        PerformanceEvidence(
            multi_agent_run_id="future-run",
            agent_attempt_id=99,
            role=AgentRole.TECHNICAL,
            provider=AIProvider.GEMINI,
            model="gemini-release-fixture",
            symbol="BTCUSDT",
            direction=Direction.LONG,
            market_regime=MarketRegime.BULL,
            horizon="1H",
            state=OutcomeState.EVALUATED,
            data_quality="FULL",
            matured_at=as_of + timedelta(seconds=1),
            directional_hit=False,
            signed_return_pct=-50.0,
        )
    )
    summary = summarize_performance(
        rows,
        as_of=as_of,
        role=AgentRole.TECHNICAL,
        provider=AIProvider.GEMINI,
        model="gemini-release-fixture",
        horizon=EvaluationHorizon.H1,
    )
    assert summary.sample_count == 29
    assert summary.hit_rate == 1.0
    assert summary.multiplier == 1.0


def test_multi_agent_intent_and_simulation_keep_run_correlation_without_live_execution():
    risk_context = FullRiskContext(90, 90, 3, 3, 0, 0, False, 1000, 1000)
    setup = {
        "analysis_id": None,
        "multi_agent_run_id": RUN_ID,
        "symbol": "BTCUSDT",
        "side": "LONG",
        "timeframe": "15m",
        "entry_min": 100,
        "entry_max": 101,
        "stop_loss": 95,
        "take_profits": (110, 120),
        "confidence": 90,
        "opportunity_score": 90,
        "risk_reward": 3,
    }
    assert generate_order_intent(setup, risk_context, RiskPolicy(), multi_agent_mode="SHADOW") is None
    intent = generate_order_intent(setup, risk_context, RiskPolicy(), multi_agent_mode="PRIMARY")
    assert intent is not None
    assert intent.multi_agent_run_id == RUN_ID
    assert intent.analysis_id is None
    assert intent.mode == "DRY_RUN"
    assert intent.exchange_submission_allowed is False
    assert EXCHANGE_SUBMISSION_ALLOWED is False

    trade_setup = TradeSetup(
        analysis_id=None,
        multi_agent_run_id=RUN_ID,
        symbol=intent.symbol,
        side=intent.side,
        timeframe="15m",
        signal_created_at=START,
        entry_min=intent.entry_min,
        entry_max=intent.entry_max,
        stop_loss=intent.stop_loss,
        take_profits=intent.take_profits,
        quantity=intent.quantity,
        leverage=intent.leverage,
        risk_amount=float(intent.risk_evidence["risk_amount"]),
        full_risk_approved=True,
    )
    trade = PaperTradeEngine(AccountState()).create_pending(trade_setup)
    assert trade.multi_agent_run_id == RUN_ID
    assert trade.analysis_id is None
    assert trade.setup.source_key == f"multi-agent:{RUN_ID}"


def test_rollout_precedence_remains_fail_closed():
    assert resolve_multi_agent_mode(None, "PRIMARY") is RolloutMode.OFF
    assert resolve_multi_agent_mode("false", "PRIMARY") is RolloutMode.OFF
    assert resolve_multi_agent_mode("true", "") is RolloutMode.OFF
    assert resolve_multi_agent_mode("true", "BROKEN") is RolloutMode.OFF
    assert resolve_multi_agent_mode("true", "OFF") is RolloutMode.OFF
    assert resolve_multi_agent_mode("true", "SHADOW") is RolloutMode.SHADOW
    assert resolve_multi_agent_mode("true", "PRIMARY") is RolloutMode.PRIMARY


def test_release_runbook_documents_rollback_legacy_no_live_and_approved_t011_variance():
    root = Path(__file__).parents[1]
    runbook = root / "docs/operations/multi-agent-vortex-rollout.md"
    assert runbook.exists(), "T012 requires the multi-agent rollout/rollback runbook"
    text = runbook.read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    for required in (
        "OFF -> SHADOW -> PRIMARY",
        "rollback",
        "no destructive migration rollback",
        "/api/v1/ai/latest",
        "SIMULATION",
        "DIRECT_AI_ORDER_ENABLED=false",
        "exchange_submission_allowed=false",
        "T011",
        "intentionally omitted",
        "SC-010",
        "SC-011",
        "not applicable",
        "3s",
        "15s",
        "60s",
        "30s",
        "2s -> 5s -> 10s -> 30s",
    ):
        assert required.lower() in text.lower()
    assert "multi-agent-vortex-rollout.md" in readme
