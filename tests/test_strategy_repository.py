from datetime import datetime, timezone
import httpx
import pytest

from btc_core.strategy.outcomes import SignalOutcome
from btc_core.strategy.repository import PublicBinanceKlinesFetcher, SupabaseStrategyRepository
from btc_core.strategy.metrics import StrategyMetrics
from btc_core.strategy.alerts import AlertEngine, AlertType


@pytest.mark.asyncio
async def test_upsert_is_idempotent_and_scoped_to_horizon_conflict():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(201, json=[])
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(handler)) as repo:
        await repo.upsert_outcome(analysis_id=1, scanner_candidate_id=2, symbol="btcusdt", timeframe="15m", direction="LONG", horizon="1H", signal_created_at=now, evaluation_due_at=now, outcome=SignalOutcome(outcome="NO_FILL", data_quality="FULL"))
    assert requests[0].url.params["on_conflict"] == "ai_analysis_id,horizon"
    assert requests[0].headers["prefer"].startswith("resolution=merge-duplicates")
    assert requests[0].content.decode().find("BTCUSDT") >= 0


@pytest.mark.asyncio
async def test_candles_query_is_exact_and_fallback_is_bounded_public_callback():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=[])
    async def fallback(*args): return []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(handler)) as repo:
        adapter = PublicBinanceKlinesFetcher(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])))
        await repo.candles("btcusdt", "1m", start, start, public_binance_klines=adapter)
        await adapter.aclose()
    assert requests[0].url.params["symbol"] == "eq.BTCUSDT"
    assert requests[0].url.params["timeframe"] == "eq.1m"
    assert requests[0].url.path.endswith("market_candles")

@pytest.mark.asyncio
async def test_partial_persisted_coverage_uses_fallback_and_discovery_scopes_success():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith("market_candles"):
            return httpx.Response(200, json=[{"open_time":"2026-01-01T00:00:00+00:00","close_time":"2026-01-01T00:01:00+00:00","open":1,"high":2,"low":1,"close":2}])
        return httpx.Response(200, json=[{"id":1,"market_ai_signal_outcomes":[{"horizon":"1H"}]}])
    async def fallback(*args): return []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(handler)) as repo:
        adapter = PublicBinanceKlinesFetcher(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])))
        await repo.candles("BTCUSDT", "1m", start, start + __import__('datetime').timedelta(hours=1), public_binance_klines=adapter)
        await adapter.aclose()
        await repo.analyses_missing_outcomes()
    assert requests[0].url.path.endswith("market_candles") and len(requests) == 2
    assert requests[-1].url.params["status"] == "eq.SUCCESS"

@pytest.mark.asyncio
async def test_untrusted_fallback_callback_is_rejected():
    async def private_fetch(*args): return []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))) as repo:
        with pytest.raises(ValueError, match="public_binance"):
            await repo.candles("BTCUSDT", "1m", start, start, fallback=private_fetch)

@pytest.mark.asyncio
async def test_subclass_override_cannot_bypass_public_adapter_boundary():
    invoked = False
    class PrivateAdapter(PublicBinanceKlinesFetcher):
        async def __call__(self, *args):
            nonlocal invoked
            invoked = True
            return []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[]))) as repo:
        with pytest.raises(ValueError, match="approved public adapter"):
            await repo.candles("BTCUSDT", "1m", start, start, public_binance_klines=PrivateAdapter())
    assert invoked is False


@pytest.mark.asyncio
async def test_metrics_upsert_uses_literal_unique_dimensions_and_normalizes_nulls():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(201, json=[])
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    metrics = StrategyMetrics(rolling_window="24H", window_ended_at=now, analysis_count=0, eligible_signal_count=0, simulated_trade_count=0, no_fill_count=0, win_count=0, loss_count=0)
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(handler)) as repo:
        await repo.upsert_strategy_metrics(metrics)
    assert requests[0].url.params["on_conflict"] == "provider,model,timeframe,direction,symbol,rolling_window,window_ended_at"
    assert all(requests[0].content.decode().count('"'+key+'":""') == 1 for key in ("provider", "model", "timeframe", "direction", "symbol"))
    assert '"provider":null' not in requests[0].content.decode()


@pytest.mark.asyncio
async def test_alert_repository_filter_removes_nested_auth_fields():
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json=[{"id": 9}])
    event = AlertEngine().observe(
        alert_type=AlertType.HIGH_IMPACT_NEWS,
        dedupe_key="news:repository-filter",
        title="News",
        short_summary="summary",
        payload={"safe": {"value": 3}, "auth_header": "secret", "oauth_token": "secret", 1: {"password": "secret"}},
    )
    async with SupabaseStrategyRepository(supabase_url="https://x.supabase.co", api_key="service", transport=httpx.MockTransport(handler)) as repo:
        await repo.upsert_alert_event(event)
    body = requests[-1].content.decode()
    assert "auth_header" not in body and "oauth_token" not in body and "password" not in body
    assert '"safe":{"value":3}' in body


@pytest.mark.asyncio
async def test_worker_readiness_repository_fails_closed_and_persists_snapshot():
    from btc_core.strategy.readiness_evidence import ReadinessEvidenceRepository

    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "POST" and request.url.path.endswith("market_readiness_checks"):
            return httpx.Response(201, json=[])
        return httpx.Response(200, json=[])

    async with ReadinessEvidenceRepository(
        supabase_url="https://x.supabase.co",
        api_key="service",
        transport=httpx.MockTransport(handler),
    ) as repo:
        snapshot = await repo.evaluate_readiness()

    assert snapshot.overall_status == "NOT_READY"
    persisted = [r for r in requests if r.method == "POST" and r.url.path.endswith("market_readiness_checks")]
    assert len(persisted) == 1
    body = persisted[0].content.decode()
    assert '"overall_status":"NOT_READY"' in body
    assert "service" not in body
