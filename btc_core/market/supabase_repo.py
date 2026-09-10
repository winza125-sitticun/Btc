from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from btc_core.market.models import Candle
from btc_core.market.realtime import LiveMarketState
from btc_core.market.scanner import MarketScanResult


class SupabaseRepositoryError(RuntimeError):
    pass


class PersistedCandidateRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: int = Field(gt=0)
    rank: int = Field(ge=1)
    symbol: str = Field(min_length=1, max_length=30)


class PersistedScanRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    candidates: tuple[PersistedCandidateRef, ...] = ()


class SupabaseMarketRepository:
    def __init__(
        self,
        *,
        supabase_url: str,
        api_key: str,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not supabase_url.strip() or not api_key.strip():
            raise ValueError("Supabase URL and API key are required")
        self._client = httpx.AsyncClient(
            base_url=f"{supabase_url.rstrip('/')}/rest/v1",
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            headers={
                "apikey": api_key,
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    async def __aenter__(self) -> "SupabaseMarketRepository":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SupabaseRepositoryError(f"Supabase request failed: {exc}") from exc
        if response.is_error:
            detail = response.text[:500]
            raise SupabaseRepositoryError(f"Supabase HTTP {response.status_code}: {detail}")
        return response

    async def persist_scan(self, result: MarketScanResult) -> PersistedScanRef:
        now = datetime.now(timezone.utc).isoformat()
        run_response = await self._request(
            "POST",
            "/market_scanner_runs",
            headers={"Prefer": "return=representation"},
            json={
                "timeframe": result.timeframe,
                "universe_size": result.universe_size,
                "candidate_count": len(result.candidates),
                "failure_count": len(result.failures),
                "started_at": now,
                "completed_at": now,
                "source": "BINANCE_USDM",
            },
        )
        rows = run_response.json()
        if not isinstance(rows, list) or not rows or not rows[0].get("id"):
            raise SupabaseRepositoryError("Supabase did not return a scanner run id")
        run_id = str(rows[0]["id"])

        persisted_candidates: tuple[PersistedCandidateRef, ...] = ()
        if result.candidates:
            payload = []
            for candidate in result.candidates:
                components = candidate.components
                payload.append(
                    {
                        "run_id": run_id,
                        "rank": candidate.rank,
                        "symbol": candidate.symbol,
                        "timeframe": candidate.timeframe,
                        "direction": candidate.direction.value,
                        "opportunity_score": candidate.opportunity_score,
                        "directional_signal": candidate.directional_signal,
                        "technical_score": components.technical,
                        "momentum_score": components.momentum,
                        "volume_score": components.volume,
                        "orderflow_score": components.order_flow,
                        "oi_score": components.open_interest,
                        "funding_score": components.funding,
                        "liquidity_score": components.liquidity,
                        "news_score": components.news,
                        "macro_score": components.macro,
                        "rr_score": components.risk_reward,
                        "last_price": candidate.last_price,
                        "quote_volume_24h": candidate.quote_volume_24h,
                        "funding_rate": candidate.funding_rate,
                        "open_interest_change_percent": candidate.open_interest_change_percent,
                        "long_short_ratio": candidate.long_short_ratio,
                        "spread_percent": candidate.spread_percent,
                    }
                )
            candidate_response = await self._request(
                "POST",
                "/market_scanner_candidates",
                headers={"Prefer": "return=representation"},
                json=payload,
            )
            candidate_rows = candidate_response.json()
            if not isinstance(candidate_rows, list) or len(candidate_rows) != len(result.candidates):
                raise SupabaseRepositoryError("Supabase did not return all scanner candidate ids")
            try:
                persisted_candidates = tuple(
                    PersistedCandidateRef(
                        id=int(row["id"]),
                        rank=int(row["rank"]),
                        symbol=str(row["symbol"]).strip().upper(),
                    )
                    for row in candidate_rows
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise SupabaseRepositoryError("Supabase returned invalid scanner candidate references") from exc

        return PersistedScanRef(run_id=run_id, candidates=persisted_candidates)

    async def upsert_live_states(self, states: list[LiveMarketState]) -> None:
        if not states:
            return
        updated_at = datetime.now(timezone.utc).isoformat()
        payload = [state.model_dump(mode="json") | {"updated_at": updated_at} for state in states]
        await self._request(
            "POST",
            "/market_live_state",
            params={"on_conflict": "symbol"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=payload,
        )

    async def upsert_candle(self, candle: Candle) -> None:
        payload = candle.model_dump(mode="json")
        await self._request(
            "POST",
            "/market_candles",
            params={"on_conflict": "symbol,timeframe,open_time"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=payload,
        )

    async def latest_candidates(self, timeframe: str, limit: int) -> list[dict[str, Any]]:
        run_response = await self._request(
            "GET",
            "/market_scanner_runs",
            params={
                "select": "id,timeframe,completed_at",
                "timeframe": f"eq.{timeframe}",
                "completed_at": "not.is.null",
                "order": "completed_at.desc",
                "limit": "1",
            },
        )
        runs = run_response.json()
        if not runs:
            return []
        run_id = runs[0]["id"]
        response = await self._request(
            "GET",
            "/market_scanner_candidates",
            params={
                "select": "id,run_id,rank,symbol,timeframe,direction,opportunity_score,last_price,quote_volume_24h,funding_rate,open_interest_change_percent,long_short_ratio,spread_percent,created_at",
                "run_id": f"eq.{run_id}",
                "order": "rank.asc",
                "limit": str(limit),
            },
        )
        rows = response.json()
        return rows if isinstance(rows, list) else []

    async def live_states(self, symbols: list[str]) -> list[dict[str, Any]]:
        if not symbols:
            return []
        normalized = [item.strip().upper() for item in symbols if item.strip()]
        symbol_filter = "in.(" + ",".join(normalized) + ")"
        response = await self._request(
            "GET",
            "/market_live_state",
            params={
                "select": "*",
                "symbol": symbol_filter,
                "order": "symbol.asc",
            },
        )
        rows = response.json()
        return rows if isinstance(rows, list) else []
