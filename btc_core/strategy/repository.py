from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from .outcomes import OHLCBar, SignalOutcome


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
        if "ai_analysis_id" not in trade:
            raise ValueError("ai_analysis_id is required as the durable idempotency key")
        await self._assert_system_account(account_id)
        payload = {**trade, "account_id": account_id, "status": "PENDING_ENTRY"}
        response = await self._request("POST", "/market_simulation_trades", params={"on_conflict": "ai_analysis_id", "account_id": f"eq.{account_id}"}, headers={"Prefer": "resolution=merge-duplicates,return=representation", "X-Idempotency-Key": idempotency_key}, json=payload)
        rows = response.json()
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
