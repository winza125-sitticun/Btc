from __future__ import annotations

import os
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from btc_core.market.supabase_repo import SupabaseMarketRepository
from services.api.app.config import PublicConfig


class MarketReader(Protocol):
    async def latest_candidates(self, timeframe: str, limit: int) -> list[dict[str, Any]]: ...
    async def live_states(self, symbols: list[str]) -> list[dict[str, Any]]: ...


app = FastAPI(title="BTC AI Futures API", version="0.2.0")

origins = [item.strip() for item in os.getenv("WEB_ORIGINS", "*").split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


async def get_market_reader():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not url or not key:
        raise HTTPException(status_code=503, detail="Market data repository is not configured")
    repo = SupabaseMarketRepository(supabase_url=url, api_key=key)
    try:
        yield repo
    finally:
        await repo.aclose()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "btc-ai-futures-api"}


@app.get("/api/v1/config/public", response_model=PublicConfig)
def public_config() -> PublicConfig:
    return PublicConfig()


@app.get("/api/v1/scanner/latest")
async def latest_scanner_candidates(
    reader: Annotated[MarketReader, Depends(get_market_reader)],
    timeframe: str = Query(default="15m", min_length=2, max_length=8),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict[str, Any]]:
    return await reader.latest_candidates(timeframe.strip(), limit)


@app.get("/api/v1/market/live")
async def live_market_state(
    reader: Annotated[MarketReader, Depends(get_market_reader)],
    symbols: str = Query(min_length=1, max_length=600),
) -> list[dict[str, Any]]:
    normalized: list[str] = []
    for item in symbols.split(","):
        symbol = item.strip().upper()
        if symbol and symbol not in normalized:
            normalized.append(symbol)
    if not normalized:
        raise HTTPException(status_code=400, detail="At least one symbol is required")
    if len(normalized) > 50:
        raise HTTPException(status_code=400, detail="At most 50 symbols may be requested")
    return await reader.live_states(normalized)
