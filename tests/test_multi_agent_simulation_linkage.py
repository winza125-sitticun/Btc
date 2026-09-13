from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import httpx
import pytest

from btc_core.ai.multi_agent.models import RolloutMode
from btc_core.risk.engine import RiskPolicy
from btc_core.strategy.order_intents import generate_order_intent
from btc_core.strategy.repository import SupabaseStrategyRepository
from btc_core.strategy.risk import FullRiskContext
from btc_core.strategy.simulation import AccountState, Bar, PaperTradeEngine, TradeSetup, TradeStatus
from services.strategy_worker.app.main import StrategyWorker

RUN_ID = "11111111-1111-4111-8111-111111111111"
ACCOUNT_ID = "22222222-2222-4222-8222-222222222222"
T0 = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


def approved_context():
    return FullRiskContext(90, 90, 3, 3, 0, 0, False, 1000, 1000)


def intent_setup(**overrides):
    value = dict(
        analysis_id=42,
        multi_agent_run_id=None,
        symbol="BTCUSDT",
        side="LONG",
        timeframe="15m",
        entry_min=100,
        entry_max=101,
        stop_loss=95,
        take_profits=(105,),
        full_risk_approved=True,
    )
    value.update(overrides)
    return value


def trade_setup(**overrides):
    value = dict(
        analysis_id=None,
        multi_agent_run_id=RUN_ID,
        symbol="BTCUSDT",
        side="LONG",
        timeframe="15m",
        signal_created_at=T0,
        entry_min=100,
        entry_max=101,
        stop_loss=95,
        take_profits=(105,),
        quantity=1,
        leverage=2,
        risk_amount=5,
        full_risk_approved=True,
    )
    value.update(overrides)
    return TradeSetup(**value)


def test_order_intent_requires_exactly_one_source_and_shadow_cannot_use_multi_agent():
    legacy = generate_order_intent(intent_setup(), approved_context(), RiskPolicy())
    assert legacy is not None
    assert legacy.analysis_id == 42
    assert legacy.multi_agent_run_id is None

    primary = generate_order_intent(
        intent_setup(analysis_id=None, multi_agent_run_id=RUN_ID),
        approved_context(),
        RiskPolicy(),
        multi_agent_mode=RolloutMode.PRIMARY,
    )
    assert primary is not None
    assert primary.analysis_id is None
    assert primary.multi_agent_run_id == RUN_ID
    assert primary.exchange_submission_allowed is False

    assert generate_order_intent(
        intent_setup(analysis_id=None, multi_agent_run_id=RUN_ID),
        approved_context(),
        RiskPolicy(),
        multi_agent_mode=RolloutMode.SHADOW,
    ) is None
    assert generate_order_intent(
        intent_setup(analysis_id=42, multi_agent_run_id=RUN_ID),
        approved_context(),
        RiskPolicy(),
        multi_agent_mode=RolloutMode.PRIMARY,
    ) is None
    assert generate_order_intent(
        intent_setup(analysis_id=None, multi_agent_run_id=None),
        approved_context(),
        RiskPolicy(),
        multi_agent_mode=RolloutMode.PRIMARY,
    ) is None


def test_multi_agent_source_survives_pending_open_and_close_lifecycle():
    setup = trade_setup()
    engine = PaperTradeEngine(AccountState(balance=1000))
    trade = engine.create_pending(setup)
    assert trade.status is TradeStatus.PENDING_ENTRY
    assert trade.analysis_id is None
    assert trade.multi_agent_run_id == RUN_ID
    assert engine.create_pending(setup) is trade

    engine.process([
        Bar(timestamp=T0 + timedelta(minutes=15), open=100, high=101, low=100, close=101),
        Bar(timestamp=T0 + timedelta(minutes=30), open=104, high=106, low=104, close=105),
    ])
    assert trade.status is TradeStatus.TP_EXIT
    assert trade.multi_agent_run_id == RUN_ID

    with pytest.raises(ValueError):
        trade_setup(multi_agent_run_id=None)
    with pytest.raises(ValueError):
        trade_setup(analysis_id=42, multi_agent_run_id=RUN_ID)


@pytest.mark.asyncio
async def test_repository_persists_same_multi_agent_run_on_intent_and_trade():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/market_simulation_accounts"):
            return httpx.Response(200, json=[{"id": ACCOUNT_ID, "name": "Production Canary"}])
        if request.url.path.endswith("/market_order_intents"):
            return httpx.Response(201, json=[])
        if request.url.path.endswith("/market_simulation_trades"):
            return httpx.Response(201, json=[{"id": 9, "multi_agent_run_id": RUN_ID}])
        raise AssertionError(request.url.path)

    intent = generate_order_intent(
        intent_setup(analysis_id=None, multi_agent_run_id=RUN_ID),
        approved_context(),
        RiskPolicy(),
        multi_agent_mode=RolloutMode.PRIMARY,
    )
    assert intent is not None

    async with SupabaseStrategyRepository(
        supabase_url="https://project.supabase.co",
        api_key="service-role",
        transport=httpx.MockTransport(handler),
    ) as repo:
        await repo.upsert_order_intent(intent)
        row = await repo.create_pending_trade(
            account_id=ACCOUNT_ID,
            account_name="Production Canary",
            idempotency_key=intent.idempotency_key,
            trade={
                "ai_analysis_id": None,
                "multi_agent_run_id": RUN_ID,
                "symbol": "BTCUSDT",
                "side": "LONG",
                "planned_entry_min": 100,
                "planned_entry_max": 101,
                "quantity": 1,
                "leverage": 2,
                "risk_amount": 5,
                "stop_loss": 95,
                "take_profits": [105],
                "expires_at": (T0 + timedelta(hours=1)).isoformat(),
                "full_risk_approved": True,
            },
        )

    intent_request = next(r for r in requests if r.url.path.endswith("/market_order_intents"))
    trade_request = next(r for r in requests if r.method == "POST" and r.url.path.endswith("/market_simulation_trades"))
    intent_payload = json.loads(intent_request.content)
    trade_payload = json.loads(trade_request.content)
    assert intent_payload["ai_analysis_id"] is None
    assert intent_payload["multi_agent_run_id"] == RUN_ID
    assert trade_payload["ai_analysis_id"] is None
    assert trade_payload["multi_agent_run_id"] == RUN_ID
    assert trade_request.url.params["on_conflict"] == "multi_agent_run_id"
    assert row["multi_agent_run_id"] == RUN_ID


def test_migration_adds_xor_source_constraints_after_validation():
    sql = Path("supabase/migrations/202609120002_multi_agent_simulation_link.sql").read_text()
    lowered = " ".join(sql.lower().split())
    assert "multi_agent_run_id uuid references public.ai_multi_agent_runs(id)" in lowered
    assert lowered.count("alter column ai_analysis_id drop not null") >= 2
    assert lowered.count("check ((ai_analysis_id is not null) <> (multi_agent_run_id is not null))") >= 2
    assert "validate constraint market_order_intents_analysis_source_xor" in lowered
    assert "validate constraint market_simulation_trades_analysis_source_xor" in lowered
    assert "unique" in lowered and "multi_agent_run_id" in lowered


@pytest.mark.asyncio
async def test_strategy_worker_passes_fail_closed_rollout_mode_to_intent_stage():
    class Repo:
        def __init__(self):
            self.modes = []

        async def create_order_intents(self, multi_agent_mode):
            self.modes.append(multi_agent_mode)
            return []

    repo = Repo()
    worker = StrategyWorker(
        repository=repo,
        market_client=object(),
        enabled=True,
        order_intent_dry_run_enabled=True,
        multi_agent_mode=RolloutMode.SHADOW,
    )
    result = await worker.run_cycle()
    assert result.errors == ()
    assert result.stages == ("create_order_intents",)
    assert repo.modes == ["SHADOW"]
