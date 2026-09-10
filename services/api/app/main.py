from __future__ import annotations

import os
from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from btc_core.ai.supabase_repo import SupabaseAIAnalysisRepository
from btc_core.market.supabase_repo import SupabaseMarketRepository
from services.api.app.config import PublicConfig, TradingMode


class MarketReader(Protocol):
    async def latest_candidates(self, timeframe: str, limit: int) -> list[dict[str, Any]]: ...
    async def live_states(self, symbols: list[str]) -> list[dict[str, Any]]: ...


class AIReader(Protocol):
    async def latest(self, timeframe: str, limit: int) -> list[dict[str, Any]]: ...
    async def operational_health(
        self,
        timeframe: str,
        window: int,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> Any: ...


app = FastAPI(title="BTC AI Futures API", version="0.3.0")

origins = [item.strip() for item in os.getenv("WEB_ORIGINS", "*").split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _public_trading_mode() -> TradingMode:
    raw = os.getenv("TRADING_MODE", TradingMode.SIMULATION.value).strip().upper()
    try:
        return TradingMode(raw)
    except ValueError:
        return TradingMode.SIMULATION


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


async def get_ai_reader():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    if not url or not key:
        raise HTTPException(status_code=503, detail="AI analysis repository is not configured")
    repo = SupabaseAIAnalysisRepository(supabase_url=url, api_key=key)
    try:
        yield repo
    finally:
        await repo.aclose()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "btc-ai-futures-api"}


@app.get("/api/v1/config/public", response_model=PublicConfig)
def public_config() -> PublicConfig:
    provider = os.getenv("AI_PROVIDER", "").strip().upper() or None
    model = os.getenv("AI_MODEL", "").strip() or None
    return PublicConfig(
        trading_mode=_public_trading_mode(),
        direct_ai_order_enabled=_env_flag("DIRECT_AI_ORDER_ENABLED", False),
        ai_analysis_enabled=_env_flag("AI_ANALYSIS_V1_ENABLED", False),
        ai_provider=provider,
        ai_model=model,
        ai_api_key_configured=bool(os.getenv("AI_API_KEY", "").strip()),
    )


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


@app.get("/api/v1/ai/latest")
async def latest_ai_analyses(
    reader: Annotated[AIReader, Depends(get_ai_reader)],
    timeframe: str = Query(default="15m", min_length=2, max_length=8),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[dict[str, Any]]:
    return await reader.latest(timeframe.strip(), limit)


@app.get("/api/v1/performance/health")
async def performance_health(
    reader: Annotated[AIReader, Depends(get_ai_reader)],
    timeframe: str = Query(default="15m", min_length=2, max_length=8),
    window: int = Query(default=20, ge=20, le=200),
) -> Any:
    """Return bounded, read-only provider and scanner canary evidence."""
    provider = os.getenv("AI_PROVIDER", "").strip().upper() or None
    model = os.getenv("AI_MODEL", "").strip() or None
    return await reader.operational_health(
        timeframe.strip(), window, provider=provider, model=model
    )
