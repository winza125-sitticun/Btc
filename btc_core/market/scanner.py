from __future__ import annotations

import asyncio
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from btc_core.ai.models import Direction
from btc_core.market.features import build_market_feature_result
from btc_core.market.models import MarketSnapshot, MarketSymbol, Ticker24h
from btc_core.scanner.scoring import OpportunityInputs


class MarketClientProtocol(Protocol):
    async def list_usdt_perpetuals(self) -> list[MarketSymbol]: ...
    async def ticker_24h(self) -> list[Ticker24h]: ...
    async def market_snapshot(self, symbol: str, timeframe: str, *, candle_limit: int = 60) -> MarketSnapshot: ...


class MarketScannerCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1)
    symbol: str
    timeframe: str
    direction: Direction
    opportunity_score: float = Field(ge=0, le=100)
    directional_signal: float = Field(ge=-1, le=1)
    components: OpportunityInputs
    last_price: float = Field(gt=0)
    quote_volume_24h: float = Field(ge=0)
    funding_rate: float
    open_interest_change_percent: float
    long_short_ratio: float = Field(gt=0)
    spread_percent: float = Field(ge=0)
    market_only: bool = True


class MarketScanFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    reason: str


class MarketScanResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeframe: str
    universe_size: int = Field(ge=0)
    candidates: list[MarketScannerCandidate]
    failures: list[MarketScanFailure]
    enrichment_status: str = "MARKET_ONLY"


class BinanceOpportunityScanner:
    def __init__(self, *, client: MarketClientProtocol, concurrency: int = 5, candle_limit: int = 60) -> None:
        if not 1 <= concurrency <= 20:
            raise ValueError("concurrency must be between 1 and 20")
        if candle_limit < 20:
            raise ValueError("candle_limit must be at least 20")
        self._client = client
        self._concurrency = concurrency
        self._candle_limit = candle_limit

    async def scan(self, *, timeframe: str = "15m", universe_limit: int = 30, candidate_limit: int = 10) -> MarketScanResult:
        if not 1 <= universe_limit <= 200:
            raise ValueError("universe_limit must be between 1 and 200")
        if not 1 <= candidate_limit <= 200:
            raise ValueError("candidate_limit must be between 1 and 200")
        candidate_limit = min(candidate_limit, universe_limit)

        symbols, tickers = await asyncio.gather(
            self._client.list_usdt_perpetuals(),
            self._client.ticker_24h(),
        )
        allowed = {item.symbol for item in symbols}
        ranked_tickers = sorted(
            (ticker for ticker in tickers if ticker.symbol in allowed and ticker.quote_volume > 0),
            key=lambda item: item.quote_volume,
            reverse=True,
        )[:universe_limit]

        semaphore = asyncio.Semaphore(self._concurrency)

        async def collect(ticker: Ticker24h):
            async with semaphore:
                try:
                    snapshot = await self._client.market_snapshot(
                        ticker.symbol,
                        timeframe,
                        candle_limit=self._candle_limit,
                    )
                    features = build_market_feature_result(snapshot)
                    return (
                        MarketScannerCandidate(
                            rank=1,
                            symbol=ticker.symbol,
                            timeframe=timeframe,
                            direction=features.direction,
                            opportunity_score=features.opportunity_score,
                            directional_signal=features.directional_signal,
                            components=features.inputs,
                            last_price=snapshot.mark_price,
                            quote_volume_24h=ticker.quote_volume,
                            funding_rate=snapshot.funding_rate,
                            open_interest_change_percent=snapshot.open_interest_change_percent,
                            long_short_ratio=snapshot.long_short_ratio,
                            spread_percent=snapshot.spread_percent,
                        ),
                        None,
                    )
                except Exception as exc:
                    return None, MarketScanFailure(symbol=ticker.symbol, reason=str(exc)[:300])

        results = await asyncio.gather(*(collect(ticker) for ticker in ranked_tickers))
        candidates = [candidate for candidate, _ in results if candidate is not None]
        failures = [failure for _, failure in results if failure is not None]

        candidates.sort(key=lambda item: (item.opportunity_score, item.quote_volume_24h), reverse=True)
        candidates = [candidate.model_copy(update={"rank": index}) for index, candidate in enumerate(candidates[:candidate_limit], start=1)]

        return MarketScanResult(
            timeframe=timeframe,
            universe_size=len(ranked_tickers),
            candidates=candidates,
            failures=failures,
        )
