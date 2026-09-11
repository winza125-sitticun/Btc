from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from .outcomes import OHLCBar, SignalOutcome
from .experiments import StrategyExperiment
from .metrics import StrategyMetrics


class StrategyRepositoryError(RuntimeError):
    pass

class PublicBinanceKlinesFetcher:
    """Concrete, credential-free adapter for the public Binance USD-M API."""
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(base_url="https://fapi.binance.com", transport=transport, timeout=10.0)
    async def __call__(self, symbol, timeframe, start, end, limit):
        response = await self._client.get("/fapi/v1/klines", params={"symbol": symbol, "interval": timeframe, "startTime": int(start.timestamp()*1000), "endTime": int(end.timestamp()*1000), "limit": limit})
        response.raise_for_status()
        return [OHLCBar(timestamp=datetime.fromtimestamp(row[0]/1000, tz=start.tzinfo), open=row[1], high=row[2], low=row[3], close=row[4]) for row in response.json()]
    async def aclose(self): await self._client.aclose()


class SupabaseStrategyRepository:
    def __init__(self, *, supabase_url: str, api_key: str, timeout_seconds: float = 10.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not supabase_url.strip() or not api_key.strip():
            raise ValueError("Supabase URL and API key are required")
        self._client = httpx.AsyncClient(base_url=f"{supabase_url.rstrip('/')}/rest/v1", timeout=httpx.Timeout(timeout_seconds), transport=transport, headers={"apikey": api_key, "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})

    async def __aenter__(self): return self
    async def __aexit__(self, *args): await self.aclose()
    async def aclose(self): await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try: response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc: raise StrategyRepositoryError("Supabase strategy request failed") from exc
        if response.is_error: raise StrategyRepositoryError(f"Supabase strategy returned HTTP {response.status_code}")
        return response

    async def _assert_system_account(self, account_id: str) -> None:
        response = await self._request("GET", "/market_simulation_accounts", params={"select": "id,name", "id": f"eq.{account_id}", "name": "eq.Production Canary", "limit": "1"})
        rows = response.json()
        if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("name") != "Production Canary" or str(rows[0].get("id")) != str(account_id):
            raise StrategyRepositoryError("account is not the Production Canary system account")

    async def analyses_missing_outcomes(self, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500: raise ValueError("limit must be between 1 and 500")
        response = await self._request("GET", "/market_ai_analyses", params={"select": "id,scanner_candidate_id,symbol,timeframe,ai_direction,entry_min,entry_max,stop_loss,take_profits,created_at,market_ai_signal_outcomes(horizon)", "ai_direction": "in.(LONG,SHORT,WAIT,EXIT)", "status": "eq.SUCCESS", "limit": str(limit)})
        rows = response.json()
        if not isinstance(rows, list): return []
        return [row for row in rows if len({str(item.get("horizon")) for item in (row.get("market_ai_signal_outcomes") or []) if isinstance(item, dict)}) < 3]

    discover_missing_outcomes = analyses_missing_outcomes

    async def upsert_outcome(self, *, analysis_id: int, scanner_candidate_id: int, symbol: str, timeframe: str, direction: str, horizon: str, signal_created_at: datetime, evaluation_due_at: datetime, outcome: SignalOutcome, entry_reference: float | None = None) -> None:
        payload = {"ai_analysis_id": analysis_id, "scanner_candidate_id": scanner_candidate_id, "symbol": symbol.strip().upper(), "timeframe": timeframe, "direction": direction, "horizon": horizon, "signal_created_at": signal_created_at.isoformat(), "evaluation_due_at": evaluation_due_at.isoformat(), "entry_reference": entry_reference, **outcome.model_dump(), "evaluated_at": datetime.now().astimezone().isoformat()}
        await self._request("POST", "/market_ai_signal_outcomes", params={"on_conflict": "ai_analysis_id,horizon"}, headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, json=payload)

    async def create_pending_trade(self, *, account_id: str, trade: dict[str, Any], idempotency_key: str, account_name: str) -> dict[str, Any]:
        """Persist a worker-owned paper trade; replaying a key is harmless."""
        if not account_id or not idempotency_key or account_name != "Production Canary":
            raise ValueError("account_id and idempotency_key are required")
        if type(trade.get("ai_analysis_id")) is not int or trade["ai_analysis_id"] <= 0:
            raise ValueError("ai_analysis_id is required as the durable idempotency key")
        await self._assert_system_account(account_id)
        payload = {**trade, "account_id": account_id, "status": "PENDING_ENTRY"}
        response = await self._request("POST", "/market_simulation_trades", params={"on_conflict": "ai_analysis_id", "account_id": f"eq.{account_id}"}, headers={"Prefer": "resolution=ignore-duplicates,return=representation", "X-Idempotency-Key": idempotency_key}, json=payload)
        rows = response.json()
        if isinstance(rows, list) and rows: return rows[0]
        existing = await self._request("GET", "/market_simulation_trades", params={"select": "*", "ai_analysis_id": f"eq.{trade['ai_analysis_id']}", "account_id": f"eq.{account_id}", "limit": "1"})
        rows = existing.json()
        return rows[0] if isinstance(rows, list) and rows else {}

    async def update_trade(self, *, trade_id: int, changes: dict[str, Any], idempotency_key: str) -> None:
        if trade_id <= 0 or not idempotency_key:
            raise ValueError("trade_id and idempotency_key are required")
        if "account_id" not in changes: raise ValueError("account_id is required for scoped updates")
        account_id = changes["account_id"]
        await self._assert_system_account(account_id)
        update = {key: value for key, value in changes.items() if key != "account_id"}
        await self._request("PATCH", f"/market_simulation_trades?id=eq.{trade_id}&account_id=eq.{account_id}", headers={"Prefer": "return=minimal", "X-Idempotency-Key": idempotency_key}, json=update)

    async def reconcile_account(self, *, account_id: str, changes: dict[str, Any], idempotency_key: str, account_name: str) -> None:
        if not account_id or not idempotency_key or account_name != "Production Canary":
            raise ValueError("account_id and idempotency_key are required")
        await self._assert_system_account(account_id)
        """Apply a complete state replacement; repeating the same payload is idempotent."""
        await self._request("PATCH", f"/market_simulation_accounts?id=eq.{account_id}", headers={"Prefer": "return=minimal", "X-Idempotency-Key": idempotency_key}, json=changes)

    async def persisted_candles(self, symbol: str, timeframe: str, start: datetime, end: datetime, limit: int = 1500) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1500: raise ValueError("limit must be between 1 and 1500")
        response = await self._request("GET", "/market_candles", params={"select": "symbol,timeframe,open_time,close_time,open,high,low,close,volume,quote_volume,trade_count,taker_buy_base_volume,taker_buy_quote_volume", "symbol": f"eq.{symbol.strip().upper()}", "timeframe": f"eq.{timeframe}", "open_time": f"gte.{start.isoformat()}", "close_time": f"lte.{end.isoformat()}", "order": "open_time.asc", "limit": str(limit)})
        rows = response.json(); return rows if isinstance(rows, list) else []

    async def upsert_strategy_metrics(self, metrics: StrategyMetrics) -> None:
        """Persist a sanitized metrics snapshot; no analysis payloads are sent."""
        payload = metrics.model_dump(mode="json")
        for key in ("provider", "model", "timeframe", "direction", "symbol"):
            if payload.get(key) is None:
                payload[key] = ""
        await self._request("POST", "/market_strategy_metrics", params={"on_conflict": "provider,model,timeframe,direction,symbol,rolling_window,window_ended_at"}, headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, json=payload)

    async def read_strategy_metrics(self, *, window: str = "24H", limit: int = 100) -> list[dict[str, Any]]:
        if window not in {"24H", "7D", "30D", "ALL"} or not 1 <= limit <= 500:
            raise ValueError("invalid metrics query bound")
        response = await self._request("GET", "/market_strategy_metrics", params={"select": "id,provider,model,timeframe,direction,symbol,rolling_window,window_started_at,window_ended_at,analysis_count,eligible_signal_count,simulated_trade_count,no_fill_count,win_count,loss_count,win_rate,average_net_return,median_net_return,expectancy,profit_factor,max_drawdown_percent,average_mfe_percent,average_mae_percent,tp1_hit_rate,tp2_hit_rate,tp3_hit_rate,sl_hit_rate,provider_success_rate,median_latency_ms,p95_latency_ms,full_data_count,partial_data_count,created_at", "rolling_window": f"eq.{window}", "order": "window_ended_at.desc", "limit": str(limit)})
        rows = response.json(); return rows if isinstance(rows, list) else []

    async def upsert_experiment(self, experiment: StrategyExperiment) -> None:
        await self._request("POST", "/market_strategy_experiments", params={"on_conflict": "name"}, headers={"Prefer": "resolution=merge-duplicates,return=minimal"}, json=experiment.model_dump(mode="json"))

    async def read_experiments(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500: raise ValueError("limit must be between 1 and 500")
        response = await self._request("GET", "/market_strategy_experiments", params={"select": "id,name,description,baseline_identifier,variant_configuration,status,started_at,ended_at,sample_count,metric_deltas,decision_reason,created_at,updated_at", "order": "created_at.desc", "limit": str(limit)})
        rows = response.json(); return rows if isinstance(rows, list) else []

    async def upsert_alert_event(self, event: Any) -> dict[str, Any]:
        """Persist a material alert; duplicate keys update observation only."""
        payload = event.model_dump(mode="json") if hasattr(event, "model_dump") else {
            "alert_type": event.alert_type.value, "severity": event.severity,
            "title": event.title, "short_summary": event.short_summary,
            "dedupe_key": event.dedupe_key, "payload": event.payload,
            "first_observed_at": event.first_observed_at.isoformat(),
            "last_observed_at": event.last_observed_at.isoformat(),
            "status": event.status, "delivery_state": event.delivery_state,
        }
        payload.pop("id", None)
        # Explicitly avoid credentials even if a caller supplied unsafe metadata.
        def clean(value: Any) -> Any:
            if isinstance(value, dict):
                blocked = ("token", "secret", "key", "password", "authorization", "credential", "api_key", "apikey")
                return {str(k): clean(v) for k, v in value.items() if not any(word in str(k).lower() for word in blocked)}
            if isinstance(value, list): return [clean(v) for v in value]
            return value
        payload["payload"] = clean(payload.get("payload", {}))
        existing = await self._request("GET", "/market_alert_events", params={"select": "*", "dedupe_key": f"eq.{payload['dedupe_key']}", "status": "in.(NEW,ACKNOWLEDGED)", "limit": "1"})
        rows = existing.json()
        if isinstance(rows, list) and rows:
            row = rows[0]
            await self._request("PATCH", f"/market_alert_events?id=eq.{row['id']}", headers={"Prefer": "return=representation"}, json={"last_observed_at": payload["last_observed_at"], "updated_at": payload["last_observed_at"]})
            return {**row, "last_observed_at": payload["last_observed_at"], "_created": False}
        try:
            response = await self._request("POST", "/market_alert_events", headers={"Prefer": "return=representation"}, json=payload)
        except StrategyRepositoryError:
            # Another worker may have inserted the same key between GET and POST.
            existing = await self._request("GET", "/market_alert_events", params={"select": "*", "dedupe_key": f"eq.{payload['dedupe_key']}", "status": "in.(NEW,ACKNOWLEDGED)", "limit": "1"})
            rows = existing.json()
            if not isinstance(rows, list) or not rows:
                raise
            row = rows[0]
            await self._request("PATCH", f"/market_alert_events?id=eq.{row['id']}", headers={"Prefer": "return=representation"}, json={"last_observed_at": payload["last_observed_at"], "updated_at": payload["last_observed_at"]})
            return {**row, "last_observed_at": payload["last_observed_at"], "_created": False}
        rows = response.json(); return rows[0] if isinstance(rows, list) and rows else {}

    async def refresh_metrics(self) -> list[dict[str, Any]]:
        """Read the latest persisted metrics for the alert stage."""
        return await self.read_strategy_metrics(limit=100)

    async def derive_alerts(self) -> list[dict[str, Any]]:
        """Persist provider degradation events from the latest metric snapshots."""
        import os
        from .alerts import AlertEngine, AlertType
        from .alert_delivery import LineAdapter, TelegramAdapter, WebhookAdapter, persist_and_deliver_alert
        engine = AlertEngine()
        metrics = await self.refresh_metrics()
        created = []
        for row in metrics:
            rate = row.get("provider_success_rate")
            provider = row.get("provider") or "unknown"
            if rate is not None and float(rate) < 95:
                event = engine.observe(alert_type=AlertType.PROVIDER_DEGRADED, dedupe_key=f"provider:{provider}", title="AI provider degraded", short_summary=f"Provider success rate is {rate}%", severity="WARNING")
                persisted = await self.upsert_alert_event(event)
                created.append({k: v for k, v in persisted.items() if k != "_created"})
                message = f"{event.title}: {event.short_summary}"
                channels = {item.strip().upper() for item in os.getenv("ALERT_CHANNELS", "IN_APP").split(",")}
                adapters = []
                if "TELEGRAM" in channels and os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip():
                    adapters.append(TelegramAdapter(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"]))
                if "LINE" in channels and os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip() and os.getenv("LINE_TARGET_ID", "").strip():
                    adapters.append(LineAdapter(channel_access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"], target_id=os.environ["LINE_TARGET_ID"]))
                if "WEBHOOK" in channels and os.getenv("ALERT_WEBHOOK_URL", "").strip():
                    adapters.append(WebhookAdapter(url=os.environ["ALERT_WEBHOOK_URL"]))
                if persisted.get("id") and persisted.get("_created", True):
                    for adapter in adapters:
                        await persist_and_deliver_alert(self, int(persisted["id"]), adapter, message)
        return created

    async def update_alert_delivery(self, *, alert_id: int, delivery_state: dict[str, Any]) -> None:
        if alert_id <= 0: raise ValueError("alert_id is required")
        await self._request("PATCH", f"/market_alert_events?id=eq.{alert_id}", headers={"Prefer": "return=minimal"}, json={"delivery_state": delivery_state})

    async def read_alert_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500: raise ValueError("limit must be between 1 and 500")
        response = await self._request("GET", "/market_alert_events", params={"select": "id,alert_type,severity,symbol,ai_analysis_id,scanner_run_id,title,short_summary,dedupe_key,first_observed_at,last_observed_at,status,created_at,updated_at", "order": "created_at.desc", "limit": str(limit)})
        rows = response.json(); return rows if isinstance(rows, list) else []

    async def candles(self, symbol: str, timeframe: str, start: datetime, end: datetime, *, public_binance_klines: PublicBinanceKlinesFetcher | None = None, fallback: Callable[[str, str, datetime, datetime, int], Awaitable[list[OHLCBar]]] | None = None) -> list[OHLCBar]:
        if fallback is not None:
            raise ValueError("fallback callbacks are not supported; use public_binance_klines")
        if public_binance_klines is not None and type(public_binance_klines) is not PublicBinanceKlinesFetcher:
            raise ValueError("public_binance_klines must be an approved public adapter")
        rows = await self.persisted_candles(symbol, timeframe, start, end)
        interval = _interval_minutes(timeframe)
        expected = max(1, int((end - start).total_seconds() // (interval * 60)))
        observed = {str(r.get("open_time")) for r in rows}
        required = { (start + timedelta(minutes=interval * i)).isoformat() for i in range(expected) }
        coverage_complete = bool(rows) and required.issubset(observed)
        if coverage_complete or public_binance_klines is None: return [OHLCBar(timestamp=r["open_time"], open=r["open"], high=r["high"], low=r["low"], close=r["close"]) for r in rows]
        result = await public_binance_klines(symbol.strip().upper(), timeframe, start, end, 1500)
        if len(result) > 1500: raise StrategyRepositoryError("fallback candle response exceeded bound")
        return list(result)

    fetch_candles = candles

def _interval_minutes(timeframe: str) -> int:
    value = timeframe.strip().lower()
    units = {"m": 1, "h": 60, "d": 1440}
    if not value or value[-1] not in units or not value[:-1].isdigit(): raise ValueError("unsupported candle timeframe")
    return int(value[:-1]) * units[value[-1]]
