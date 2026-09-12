from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import services.api.app.main as api_main
from btc_core.ai.multi_agent.read_repository import MultiAgentReadRepository


RUN_ID = "11111111-1111-4111-8111-111111111111"
NOW = "2026-09-12T10:00:00Z"
CONFIG_VERSION = "a" * 64
PROMPT_DIGEST = "b" * 64

HESITATION = {
    "total": 22.0,
    "disagreement": 0.2,
    "confidence_dispersion": 0.1,
    "timeframe_conflict": 0.3,
    "market_uncertainty": 0.25,
    "disagreement_contribution": 8.0,
    "confidence_dispersion_contribution": 3.0,
    "timeframe_conflict_contribution": 6.0,
    "market_uncertainty_contribution": 5.0,
    "algorithm_version": "hesitation-v1",
}

CONSENSUS = {
    "id": 7,
    "direction": "LONG",
    "consensus_confidence": 84.0,
    "winning_agreement": 0.8,
    "coverage": 1.0,
    "signed_score": 0.7,
    "actionable": True,
    "supporting_roles": ["TECHNICAL"],
    "opposing_roles": [],
    "reason_codes": ["CONSENSUS_LONG"],
    "role_contributions": [
        {
            "role": "TECHNICAL",
            "provider": "GEMINI",
            "model": "gemini-test",
            "direction": "LONG",
            "confidence": 90.0,
            "base_weight": 1.0,
            "historical_multiplier": 1.0,
            "effective_weight": 1.0,
            "unsigned_strength": 0.9,
            "signed_contribution": 0.9,
            "participated": True,
            "attempt_id": 1,
        }
    ],
    "config_version": CONFIG_VERSION,
    "algorithm_version": "consensus-v1",
    "hesitation": HESITATION,
    "created_at": NOW,
}

RISK = {
    "status": "APPROVED",
    "approved": True,
    "reason_codes": [],
    "risk_policy_version": "multi-agent-risk-v1",
    "created_at": NOW,
}

VORTEX = {
    "trend_strength": 0.8,
    "volatility": 0.4,
    "momentum": 0.6,
    "order_flow_imbalance": 0.3,
    "liquidity": 0.9,
    "consensus_direction": "LONG",
    "winning_agreement": 0.8,
    "hesitation_total": 22.0,
    "observed_at": NOW,
    "snapshot_ref": "snapshot-1",
    "mapping_version": "vortex-input-v1",
}

SUMMARY = {
    "record_type": "MULTI_AGENT",
    "id": RUN_ID,
    "scanner_candidate_id": 42,
    "symbol": "BTCUSDT",
    "timeframe": "15m",
    "started_at": NOW,
    "completed_at": NOW,
    "status": "COMPLETED",
    "config_version": CONFIG_VERSION,
    "enabled_role_count": 1,
    "valid_role_count": 1,
    "rollout_mode": "PRIMARY",
    "vortex_inputs": VORTEX,
    "consensus": CONSENSUS,
    "risk": RISK,
}

ATTEMPT = {
    "id": 1,
    "role": "TECHNICAL",
    "provider": "GEMINI",
    "model": "gemini-test",
    "prompt_version": "v1",
    "prompt_digest": PROMPT_DIGEST,
    "status": "SUCCESS",
    "direction": "LONG",
    "confidence": 90.0,
    "entry_min": 100.0,
    "entry_max": 101.0,
    "stop_loss": 95.0,
    "take_profits": [105.0],
    "risk_reward": 2.0,
    "reason_summary": "bounded reason",
    "latency_ms": 321,
    "error_code": None,
    "error_message": None,
    "snapshot_ref": "snapshot-1",
    "created_at": NOW,
}

DETAIL = {**SUMMARY, "attempts": [ATTEMPT]}


class FakeMultiAgentReader:
    async def latest_runs(self, *, timeframe: str, limit: int):
        assert timeframe == "15m"
        assert limit == 10
        return [SUMMARY]

    async def run_detail(self, run_id: str):
        return DETAIL if run_id == RUN_ID else None

    async def dashboard_events(self, *, run_id: str, limit: int):
        assert run_id == RUN_ID
        assert limit == 100
        return [
            {
                "id": 1,
                "run_id": RUN_ID,
                "source": "MULTI_AGENT",
                "event_type": "CONSENSUS",
                "role": None,
                "status": "COMPLETED",
                "message": "consensus stored",
                "metadata_safe": {
                    "safe": "ok",
                    "api_key": "must-not-leak",
                    "nested": {"token": "must-not-leak", "keep": 1},
                    "secret_configured": True,
                },
                "created_at": NOW,
            }
        ]

    async def performance_summaries(
        self,
        *,
        role: str | None,
        symbol: str | None,
        horizon: str | None,
        limit: int,
    ):
        assert role == "TECHNICAL"
        assert symbol == "BTCUSDT"
        assert horizon == "1H"
        assert limit == 50
        return [
            {
                "role": "TECHNICAL",
                "provider": "GEMINI",
                "model": "gemini-test",
                "symbol": "BTCUSDT",
                "direction": None,
                "market_regime": None,
                "horizon": "1H",
                "sample_count": 30,
                "hit_rate": 0.6,
                "mean_signed_return_pct": 0.5,
                "normalized_expectancy": 0.625,
                "quality_score": 0.6075,
                "multiplier": 1.05375,
                "as_of": NOW,
                "algorithm_version": "performance-v1",
            }
        ]


@pytest.fixture
def client():
    dependency = getattr(api_main, "get_multi_agent_reader", None)
    assert dependency is not None, "T009 must expose an anon-backed multi-agent reader dependency"
    api_main.app.dependency_overrides[dependency] = lambda: FakeMultiAgentReader()
    try:
        yield TestClient(api_main.app)
    finally:
        api_main.app.dependency_overrides.clear()


def test_repo_contains_authoritative_openapi_contract():
    text = Path("contracts/openapi.yaml").read_text(encoding="utf-8")
    for path in (
        "/api/v1/multi-agent/config:",
        "/api/v1/multi-agent/latest:",
        "/api/v1/multi-agent/runs/{run_id}:",
        "/api/v1/multi-agent/events:",
        "/api/v1/multi-agent/performance:",
        "MultiAgentRunDetail:",
        "DashboardEvent:",
        "PerformanceSummary:",
    ):
        assert path in text


def test_config_is_sanitized_and_exposes_only_secret_presence(monkeypatch):
    monkeypatch.setenv("AI_MULTI_AGENT_ENABLED", "true")
    monkeypatch.setenv("AI_MULTI_AGENT_MODE", "SHADOW")
    monkeypatch.setenv("AI_ROLE_TECHNICAL_ENABLED", "true")
    monkeypatch.setenv("AI_ROLE_TECHNICAL_PROVIDER", "GEMINI")
    monkeypatch.setenv("AI_ROLE_TECHNICAL_MODEL", "gemini-test")
    monkeypatch.setenv("GEMINI_API_KEY", "top-secret-value")

    response = TestClient(api_main.app).get("/api/v1/multi-agent/config")
    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body).lower()
    assert "top-secret-value" not in serialized
    assert "prompt_text" not in serialized
    assert "api_key" not in serialized
    technical = next(item for item in body["roles"] if item["role"] == "TECHNICAL")
    assert technical["enabled"] is True
    assert technical["provider"] == "GEMINI"
    assert technical["model"] == "gemini-test"
    assert technical["secret_configured"] is True
    assert len(technical["prompt_digest"]) == 64


def test_latest_and_detail_match_contract_and_keep_risk_separate(client):
    latest = client.get("/api/v1/multi-agent/latest", params={"timeframe": "15m", "limit": 10})
    assert latest.status_code == 200
    item = latest.json()[0]
    assert item["record_type"] == "MULTI_AGENT"
    assert item["vortex_inputs"] == VORTEX
    assert item["consensus"]["role_contributions"][0]["attempt_id"] == 1
    assert item["consensus"]["hesitation"]["algorithm_version"] == "hesitation-v1"
    assert item["risk"]["status"] == "APPROVED"
    assert "risk" not in item["consensus"]

    detail = client.get(f"/api/v1/multi-agent/runs/{RUN_ID}")
    assert detail.status_code == 200
    assert detail.json()["attempts"][0]["error_message"] is None
    missing = client.get("/api/v1/multi-agent/runs/22222222-2222-4222-8222-222222222222")
    assert missing.status_code == 404


def test_events_recursively_strip_secrets_without_stripping_secret_configured(client):
    response = client.get("/api/v1/multi-agent/events", params={"run_id": RUN_ID, "limit": 100})
    assert response.status_code == 200
    body = response.json()
    metadata = body[0]["metadata_safe"]
    assert metadata == {"safe": "ok", "nested": {"keep": 1}, "secret_configured": True}
    serialized = json.dumps(body).lower()
    assert "must-not-leak" not in serialized
    assert "api_key" not in serialized
    assert '"token"' not in serialized


def test_performance_endpoint_preserves_segmentation(client):
    response = client.get(
        "/api/v1/multi-agent/performance",
        params={"role": "TECHNICAL", "symbol": "BTCUSDT", "horizon": "1H", "limit": 50},
    )
    assert response.status_code == 200
    item = response.json()[0]
    assert item["role"] == "TECHNICAL"
    assert item["symbol"] == "BTCUSDT"
    assert item["horizon"] == "1H"
    assert item["sample_count"] == 30
    assert item["algorithm_version"] == "performance-v1"


def test_multi_agent_reader_never_falls_back_to_service_role(monkeypatch):
    dependency = getattr(api_main, "get_multi_agent_reader", None)
    assert dependency is not None
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "must-not-be-used")
    with pytest.raises(RuntimeError, match="SUPABASE_URL and SUPABASE_ANON_KEY"):
        dependency()


@pytest.mark.asyncio
async def test_repository_merges_correlated_events_in_stable_source_order():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/ai_dashboard_events"):
            return httpx.Response(200, json=[{
                "id": 30, "multi_agent_run_id": RUN_ID, "sequence": 1,
                "event_type": "RISK", "role": None, "status": "APPROVED",
                "message": "risk stored", "metadata_safe": {}, "created_at": NOW,
            }])
        if path.endswith("/market_order_intents"):
            return httpx.Response(200, json=[{
                "id": 20, "simulation_trade_id": 10, "multi_agent_run_id": RUN_ID,
                "mode": "DRY_RUN", "symbol": "BTCUSDT", "side": "LONG",
                "validation_status": "VALID", "exchange_submission_allowed": False,
                "created_at": NOW, "updated_at": NOW,
            }])
        if path.endswith("/market_simulation_trades"):
            return httpx.Response(200, json=[{
                "id": 10, "multi_agent_run_id": RUN_ID, "symbol": "BTCUSDT",
                "side": "LONG", "status": "OPEN", "opened_at": NOW,
                "closed_at": None, "created_at": NOW, "updated_at": NOW,
            }])
        raise AssertionError(path)

    async with MultiAgentReadRepository(
        supabase_url="https://example.supabase.co",
        api_key="anon-key",
        transport=httpx.MockTransport(handler),
    ) as repo:
        events = await repo.dashboard_events(run_id=RUN_ID, limit=100)

    assert [item["source"] for item in events] == ["MULTI_AGENT", "ORDER_INTENT", "SIMULATION"]
    assert [item["id"] for item in events] == [30, 20, 10]
    assert all(item["run_id"] == RUN_ID for item in events)
    assert all("multi_agent_run_id" in str(request.url) for request in requests)
