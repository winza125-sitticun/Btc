from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Protocol

from btc_core.ai.analysis import AIAnalysisSnapshot, AINewsContext, TimeframeTechnicalContext
from btc_core.ai.models import Direction
from btc_core.market.models import Candle
from btc_core.market.scanner import MarketScannerCandidate


AI_TIMEFRAMES = ("4h", "1h", "15m")
AI_CANDLE_LIMIT = 60
AI_NEWS_LIMIT = 5
AI_NEWS_WINDOW_HOURS = 24


class KlineClientProtocol(Protocol):
    async def klines(self, symbol: str, timeframe: str, *, limit: int = 60) -> list[Candle]: ...


class NewsContextRepositoryProtocol(Protocol):
    async def recent_asset_context(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
        limit: int = 5,
    ) -> list[object]: ...


def _ema(values: list[float], period: int) -> float:
    if not values:
        raise ValueError("EMA requires values")
    multiplier = 2.0 / (period + 1.0)
    result = values[0]
    for value in values[1:]:
        result = ((value - result) * multiplier) + result
    return result


def _technical_context(timeframe: str, candles: list[Candle]) -> TimeframeTechnicalContext:
    if len(candles) < 20:
        raise ValueError(f"at least 20 candles are required for {timeframe}")

    closes = [item.close for item in candles]
    fast_ema = _ema(closes[-12:], 5)
    slow_ema = _ema(closes[-20:], 12)
    trend_percent = 0.0 if slow_ema == 0 else ((fast_ema / slow_ema) - 1.0) * 100.0

    reference_close = closes[-6]
    momentum_percent = 0.0 if reference_close == 0 else ((closes[-1] / reference_close) - 1.0) * 100.0

    recent = candles[-20:]
    recent_high = max(item.high for item in recent)
    recent_low = min(item.low for item in recent)
    prior_volume = [item.quote_volume for item in candles[-21:-1]]
    average_prior_volume = sum(prior_volume) / len(prior_volume) if prior_volume else candles[-1].quote_volume
    recent_volume_ratio = 1.0 if average_prior_volume <= 0 else candles[-1].quote_volume / average_prior_volume

    if trend_percent > 0:
        direction = Direction.LONG
    elif trend_percent < 0:
        direction = Direction.SHORT
    else:
        direction = Direction.WAIT

    return TimeframeTechnicalContext(
        timeframe=timeframe,
        close=closes[-1],
        trend_percent=round(trend_percent, 6),
        momentum_percent=round(momentum_percent, 6),
        recent_high=recent_high,
        recent_low=recent_low,
        recent_volume_ratio=round(recent_volume_ratio, 6),
        direction=direction,
    )


async def build_ai_snapshot(
    candidate: MarketScannerCandidate,
    *,
    market_client: KlineClientProtocol,
    news_repo: NewsContextRepositoryProtocol | None,
    now: datetime | None = None,
) -> AIAnalysisSnapshot:
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    candle_sets = await asyncio.gather(
        *(
            market_client.klines(candidate.symbol, timeframe, limit=AI_CANDLE_LIMIT)
            for timeframe in AI_TIMEFRAMES
        )
    )
    technical = {
        timeframe: _technical_context(timeframe, candles)
        for timeframe, candles in zip(AI_TIMEFRAMES, candle_sets, strict=True)
    }

    stories: list[object] = []
    if news_repo is not None:
        stories = await news_repo.recent_asset_context(
            candidate.symbol,
            observed_at - timedelta(hours=AI_NEWS_WINDOW_HOURS),
            observed_at,
            limit=AI_NEWS_LIMIT,
        )

    sanitized_stories: list[dict[str, object]] = []
    for story in stories[:AI_NEWS_LIMIT]:
        model_dump = getattr(story, "model_dump", None)
        if callable(model_dump):
            dumped = model_dump(mode="json")
            if isinstance(dumped, dict):
                sanitized_stories.append(dumped)

    return AIAnalysisSnapshot(
        symbol=candidate.symbol,
        timeframe=candidate.timeframe,
        scanner_direction=candidate.direction,
        opportunity_score=candidate.opportunity_score,
        components=candidate.components,
        last_price=candidate.last_price,
        funding_rate=candidate.funding_rate,
        open_interest_change_percent=candidate.open_interest_change_percent,
        long_short_ratio=candidate.long_short_ratio,
        spread_percent=candidate.spread_percent,
        technical_by_timeframe=technical,
        news=AINewsContext(
            score=candidate.components.news,
            stories=tuple(sanitized_stories),
        ),
    )
