from datetime import datetime, timedelta, timezone

import httpx
import pytest

from btc_core.ai.models import AIProvider, Direction
from btc_core.ai.multi_agent.models import AgentRole
from btc_core.ai.multi_agent.performance import EvaluationHorizon, MarketRegime
from btc_core.ai.multi_agent.repository import SupabaseMultiAgentRepository

NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
RUN_ID = "11111111-1111-4111-8111-111111111111"


@pytest.mark.asyncio
async def test_repository_reads_frozen_candidate_context_exact_candles_and_point_in_time_evidence():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/ai_agent_attempts"):
            return httpx.Response(200, json=[{
                "id": 7,
                "multi_agent_run_id": RUN_ID,
                "role": "TECHNICAL",
                "provider": "GEMINI",
                "model": "gemini-test",
                "direction": "LONG",
                "ai_multi_agent_runs": {
                    "symbol": "BTCUSDT",
                    "started_at": (NOW-timedelta(hours=2)).isoformat(),
                    "market_context_summary": {
                        "reference_price": 100.0,
                        "predecision_regime": "BULL",
                    },
                },
            }])
        if path.endswith("/ai_decision_outcomes") and "ai_agent_attempts" not in request.url.params.get("select", ""):
            return httpx.Response(200, json=[{"agent_attempt_id": 7, "horizon": "15M"}])
        if path.endswith("/market_candles"):
            return httpx.Response(200, json=[{
                "symbol": "BTCUSDT", "timeframe": "1h",
                "open_time": (NOW-timedelta(hours=1)).isoformat(),
                "close_time": NOW.isoformat(),
                "high": 105, "low": 95, "close": 103,
            }])
        if path.endswith("/ai_decision_outcomes"):
            mature = NOW-timedelta(minutes=1)
            future = NOW+timedelta(minutes=1)
            base = {
                "multi_agent_run_id": RUN_ID, "agent_attempt_id": 7,
                "horizon": "1H", "state": "EVALUATED", "data_quality": "FULL",
                "directional_hit": True, "signed_return_pct": 3.0,
                "market_regime": "BULL",
                "ai_agent_attempts": {
                    "role": "TECHNICAL", "provider": "GEMINI",
                    "model": "gemini-test", "direction": "LONG",
                },
                "ai_multi_agent_runs": {"symbol": "BTCUSDT"},
            }
            return httpx.Response(200, json=[
                {**base, "matured_at": mature.isoformat()},
                {**base, "matured_at": future.isoformat()},
            ])
        raise AssertionError(path)

    async with SupabaseMultiAgentRepository(
        supabase_url="https://project.supabase.co",
        api_key="service-role",
        transport=httpx.MockTransport(handler),
    ) as repo:
        candidates = await repo.list_outcome_evaluation_candidates(NOW)
        assert len(candidates) == 1
        item = candidates[0]
        assert item.reference_price == 100.0
        assert item.market_regime is MarketRegime.BULL
        assert item.existing_horizons == (EvaluationHorizon.M15,)

        bars = await repo.load_market_outcome_bars(
            "BTCUSDT", "1h", NOW-timedelta(hours=1), NOW+timedelta(hours=1)
        )
        assert len(bars) == 1 and bars[0].close == 103

        evidence = await repo.list_performance_evidence(NOW)
        assert len(evidence) == 1
        assert evidence[0].role is AgentRole.TECHNICAL
        assert evidence[0].provider is AIProvider.GEMINI
        assert evidence[0].direction is Direction.LONG
        assert evidence[0].matured_at <= NOW

    candle_request = next(r for r in requests if r.url.path.endswith("/market_candles"))
    assert candle_request.url.params["close_time"] == f"gte.{(NOW-timedelta(hours=1)).isoformat().replace('+00:00', 'Z')}"
    assert candle_request.url.params["and"] == f"(close_time.lt.{(NOW+timedelta(hours=1)).isoformat().replace('+00:00', 'Z')})"
    evidence_request = requests[-1]
    assert evidence_request.url.params["matured_at"].startswith("lte.")
