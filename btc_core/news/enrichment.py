from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from btc_core.news.models import NewsImpactLevel


class NewsScoreStory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    published_at: datetime
    impact_level: NewsImpactLevel
    credibility_score: float = Field(ge=0, le=100)


class NewsScoreRepository(Protocol):
    async def recent_asset_news(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
        limit: int = 50,
    ) -> list[NewsScoreStory]: ...


_IMPACT_POINTS: dict[NewsImpactLevel, float] = {
    NewsImpactLevel.LOW: 2.0,
    NewsImpactLevel.MEDIUM: 6.0,
    NewsImpactLevel.HIGH: 12.0,
}


def calculate_news_score(
    stories: list[NewsScoreStory],
    *,
    now: datetime,
    window_hours: float = 24.0,
) -> float:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if window_hours <= 0:
        raise ValueError("window_hours must be positive")

    score = 50.0
    for story in stories:
        if story.published_at.tzinfo is None:
            continue
        age_hours = (now - story.published_at).total_seconds() / 3600.0
        if age_hours < 0 or age_hours >= window_hours:
            continue
        recency_factor = 1.0 - (age_hours / window_hours)
        credibility_factor = story.credibility_score / 100.0
        score += _IMPACT_POINTS[story.impact_level] * credibility_factor * recency_factor

    return round(max(50.0, min(100.0, score)), 2)


class RecentNewsScoreProvider:
    def __init__(
        self,
        *,
        repo: NewsScoreRepository,
        window_hours: float = 24.0,
        article_limit: int = 50,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if window_hours <= 0:
            raise ValueError("window_hours must be positive")
        if not 1 <= article_limit <= 200:
            raise ValueError("article_limit must be between 1 and 200")
        self._repo = repo
        self._window_hours = window_hours
        self._article_limit = article_limit
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    async def score(self, symbol: str) -> float:
        now = self._now_factory()
        if now.tzinfo is None:
            raise ValueError("now_factory must return a timezone-aware datetime")
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            return 50.0
        since = now - timedelta(hours=self._window_hours)
        stories = await self._repo.recent_asset_news(
            normalized_symbol,
            since,
            now,
            limit=self._article_limit,
        )
        return calculate_news_score(
            stories,
            now=now,
            window_hours=self._window_hours,
        )
