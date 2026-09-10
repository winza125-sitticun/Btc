from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import httpx

from .outcomes import OHLCBar, SignalOutcome


class StrategyRepositoryError(RuntimeError):
    pass

class PublicBinanceKlinesFetcher:
    """Explicit adapter boundary for public Binance klines only."""
    is_public_binance_klines = True
    def __init__(self, fetch: Callable[..., Awaitable[list[OHLCBar]]]): self._fetch = fetch
    async def __call__(self, symbol, timeframe, start, end, limit): return await self._fetch(symbol, timeframe, start, end, limit)


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

    async def persisted_candles(self, symbol: str, timeframe: str, start: datetime, end: datetime, limit: int = 1500) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1500: raise ValueError("limit must be between 1 and 1500")
        response = await self._request("GET", "/market_candles", params={"select": "symbol,timeframe,open_time,close_time,open,high,low,close,volume,quote_volume,trade_count,taker_buy_base_volume,taker_buy_quote_volume", "symbol": f"eq.{symbol.strip().upper()}", "timeframe": f"eq.{timeframe}", "open_time": f"gte.{start.isoformat()}", "close_time": f"lte.{end.isoformat()}", "order": "open_time.asc", "limit": str(limit)})
        rows = response.json(); return rows if isinstance(rows, list) else []

    async def candles(self, symbol: str, timeframe: str, start: datetime, end: datetime, *, public_binance_klines: PublicBinanceKlinesFetcher | None = None, fallback: Callable[[str, str, datetime, datetime, int], Awaitable[list[OHLCBar]]] | None = None) -> list[OHLCBar]:
        if fallback is not None:
            if public_binance_klines is not None: raise ValueError("use public_binance_klines, not fallback")
            if not getattr(fallback, "is_public_binance_klines", False): raise ValueError("fallback must be a public_binance klines callback")
            public_binance_klines = fallback
        if public_binance_klines is not None and not getattr(public_binance_klines, "is_public_binance_klines", False):
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
