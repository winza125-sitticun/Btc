from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from btc_core.strategy.repository import SupabaseStrategyRepository

RUN_ID = "11111111-1111-4111-8111-111111111111"
ACCOUNT_ID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 9, 13, 5, 45, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_primary_runtime_resolves_pending_full_risk_selects_highest_weight_geometry_and_creates_correlated_dry_run():
    requests: list[httpx.Request] = []

    run = {
        "id": RUN_ID,
        "scanner_candidate_id": 42,
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "started_at": NOW.isoformat(),
        "completed_at": NOW.isoformat(),
        "status": "COMPLETED",
        "rollout_mode": "PRIMARY",
    }
    consensus = {
        "id": 501,
        "multi_agent_run_id": RUN_ID,
        "direction": "LONG",
        "consensus_confidence": 88,
        "actionable": True,
        "role_contributions": [
            {"role": "TECHNICAL", "effective_weight": 1.0, "participated": True},
            {"role": "MOMENTUM", "effective_weight": 1.4, "participated": True},
            {"role": "ORDER_FLOW", "effective_weight": 1.4, "participated": True},
        ],
    }
    attempts = [
        {
            "id": 11,
            "role": "TECHNICAL",
            "status": "SUCCESS",
            "direction": "LONG",
            "confidence": 82,
            "entry_min": 100,
            "entry_max": 101,
            "stop_loss": 95,
            "take_profits": [108, 112],
            "risk_reward": 2.5,
        },
        {
            "id": 12,
            "role": "MOMENTUM",
            "status": "SUCCESS",
            "direction": "LONG",
            "confidence": 86,
            "entry_min": 101,
            "entry_max": 102,
            "stop_loss": 96,
            "take_profits": [110, 115],
            "risk_reward": 3.0,
        },
        {
            "id": 13,
            "role": "ORDER_FLOW",
            "status": "SUCCESS",
            "direction": "LONG",
            "confidence": 90,
            "entry_min": 99,
            "entry_max": 100,
            "stop_loss": 94,
            "take_profits": [108, 112],
            "risk_reward": 3.0,
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        method = request.method

        if method == "GET" and path.endswith("/ai_multi_agent_runs"):
            return httpx.Response(200, json=[run])
        if method == "GET" and path.endswith("/ai_multi_agent_risk_results"):
            return httpx.Response(200, json=[{
                "id": 601,
                "multi_agent_run_id": RUN_ID,
                "consensus_id": 501,
                "status": "PENDING",
                "approved": False,
                "reason_codes": ["FULL_RISK_CONTEXT_PENDING"],
                "risk_policy_version": "multi-agent-risk-v1",
            }])
        if method == "GET" and path.endswith("/ai_consensus_decisions"):
            return httpx.Response(200, json=[consensus])
        if method == "GET" and path.endswith("/ai_agent_attempts"):
            return httpx.Response(200, json=attempts)
        if method == "GET" and path.endswith("/market_scanner_candidates"):
            return httpx.Response(200, json=[{"id": 42, "opportunity_score": 90}])
        if method == "GET" and path.endswith("/market_simulation_accounts"):
            return httpx.Response(200, json=[{
                "id": ACCOUNT_ID,
                "name": "Production Canary",
                "starting_balance": 1000,
                "balance": 1000,
                "equity": 1000,
                "daily_realized_loss": 0,
            }])
        if method == "GET" and path.endswith("/market_simulation_trades"):
            return httpx.Response(200, json=[])
        if method == "GET" and path.endswith("/market_alert_events"):
            return httpx.Response(200, json=[])
        if method == "GET" and path.endswith("/market_readiness_checks"):
            return httpx.Response(200, json=[{"overall_status": "PAPER_READY"}])
        if method == "GET" and path.endswith("/market_order_intents"):
            return httpx.Response(200, json=[])
        if method == "POST" and path.endswith("/ai_multi_agent_risk_results"):
            payload = json.loads(request.content)
            return httpx.Response(201, json=[{"id": 602, **payload}])
        if method == "POST" and path.endswith("/market_order_intents"):
            return httpx.Response(201, json=[{"id": 77}])
        if method == "POST" and path.endswith("/market_simulation_trades"):
            return httpx.Response(201, json=[{"id": 9, "multi_agent_run_id": RUN_ID}])
        if method == "PATCH" and path.endswith("/market_order_intents"):
            return httpx.Response(204)
        raise AssertionError(f"unexpected request: {method} {request.url}")

    async with SupabaseStrategyRepository(
        supabase_url="https://project.supabase.co",
        api_key="service-role",
        transport=httpx.MockTransport(handler),
    ) as repo:
        created = await repo.create_order_intents("PRIMARY")

    assert len(created) == 1
    assert created[0]["multi_agent_run_id"] == RUN_ID
    assert created[0]["selected_role"] == "MOMENTUM"
    assert created[0]["simulation_trade_id"] == 9

    risk_post = next(r for r in requests if r.method == "POST" and r.url.path.endswith("/ai_multi_agent_risk_results"))
    risk_payload = json.loads(risk_post.content)
    assert risk_payload["status"] == "APPROVED"
    assert risk_payload["approved"] is True

    intent_post = next(r for r in requests if r.method == "POST" and r.url.path.endswith("/market_order_intents"))
    intent_payload = json.loads(intent_post.content)
    assert intent_payload["multi_agent_run_id"] == RUN_ID
    assert intent_payload["ai_analysis_id"] is None
    assert intent_payload["side"] == "LONG"
    assert intent_payload["entry_price"] == pytest.approx(101.5)
    assert intent_payload["stop_loss"] == 96
    assert intent_payload["take_profit_instructions"] == [110.0, 115.0]
    assert intent_payload["mode"] == "DRY_RUN"
    assert intent_payload["exchange_submission_allowed"] is False
    assert intent_payload["risk_decision_snapshot"]["geometry_role"] == "MOMENTUM"
    assert intent_payload["risk_decision_snapshot"]["geometry_attempt_id"] == 12

    trade_post = next(r for r in requests if r.method == "POST" and r.url.path.endswith("/market_simulation_trades"))
    trade_payload = json.loads(trade_post.content)
    assert trade_payload["multi_agent_run_id"] == RUN_ID
    assert trade_payload["ai_analysis_id"] is None
    assert trade_payload["planned_entry_min"] == 101.0
    assert trade_payload["planned_entry_max"] == 102.0
    assert trade_payload["stop_loss"] == 96.0
    assert trade_payload["full_risk_approved"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["OFF", "SHADOW", "INVALID"])
async def test_non_primary_runtime_is_fail_closed_without_database_activity(mode):
    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"{mode} must not touch strategy persistence")

    async with SupabaseStrategyRepository(
        supabase_url="https://project.supabase.co",
        api_key="service-role",
        transport=httpx.MockTransport(forbidden),
    ) as repo:
        assert await repo.create_order_intents(mode) == []
