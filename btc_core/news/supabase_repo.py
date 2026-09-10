from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from btc_core.news.enrichment import NewsScoreStory
from btc_core.news.models import EnrichedNewsArticle, NewsImpactLevel, NewsSourceClass, RecentNewsStory


class SupabaseNewsRepositoryError(RuntimeError):
    pass


class RecentAssetContextStory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=500)
    summary: str | None = Field(default=None, max_length=2000)
    published_at: datetime
    impact_level: NewsImpactLevel
    credibility_score: float = Field(ge=0, le=100)


class SupabaseNewsRepository:
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

    async def __aenter__(self) -> "SupabaseNewsRepository":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SupabaseNewsRepositoryError(f"Supabase request failed: {exc}") from exc
        if response.is_error:
            raise SupabaseNewsRepositoryError(
                f"Supabase HTTP {response.status_code}: {response.text[:500]}"
            )
        return response

    async def article_exists(self, source_url: str) -> bool:
        response = await self._request(
            "GET",
            "/news_articles",
            params={"select": "id", "source_url": f"eq.{source_url}", "limit": "1"},
        )
        rows = response.json()
        return isinstance(rows, list) and bool(rows)

    async def recent_stories(self, since: datetime) -> list[RecentNewsStory]:
        response = await self._request(
            "GET",
            "/news_articles",
            params={
                "select": "title,content_fingerprint,published_at,raw_data,news_assets(symbol)",
                "published_at": f"gte.{since.isoformat()}",
                "order": "published_at.desc",
                "limit": "200",
            },
        )
        rows = response.json()
        if not isinstance(rows, list):
            return []

        stories: list[RecentNewsStory] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_data = row.get("raw_data") if isinstance(row.get("raw_data"), dict) else {}
            raw_source_class = raw_data.get("source_class")
            try:
                source_class = NewsSourceClass(str(raw_source_class))
            except ValueError:
                source_class = NewsSourceClass.MEDIA

            asset_rows = row.get("news_assets") if isinstance(row.get("news_assets"), list) else []
            symbols = tuple(
                sorted(
                    {
                        str(item.get("symbol"))
                        for item in asset_rows
                        if isinstance(item, dict) and item.get("symbol")
                    }
                )
            )
            try:
                stories.append(
                    RecentNewsStory(
                        title=str(row["title"]),
                        content_fingerprint=(
                            None
                            if row.get("content_fingerprint") is None
                            else str(row.get("content_fingerprint"))
                        ),
                        published_at=row["published_at"],
                        symbols=symbols,
                        source_class=source_class,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return stories

    async def recent_asset_news(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
        limit: int = 50,
    ) -> list[NewsScoreStory]:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            return []
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")

        response = await self._request(
            "GET",
            "/news_articles",
            params=[
                (
                    "select",
                    "published_at,impact_level,credibility_score,news_assets!inner(symbol)",
                ),
                ("news_assets.symbol", f"eq.{normalized_symbol}"),
                ("published_at", f"gte.{since.isoformat()}"),
                ("published_at", f"lte.{until.isoformat()}"),
                ("order", "published_at.desc"),
                ("limit", str(limit)),
            ],
        )
        rows = response.json()
        if not isinstance(rows, list):
            return []

        stories: list[NewsScoreStory] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                stories.append(
                    NewsScoreStory(
                        published_at=row["published_at"],
                        impact_level=row["impact_level"],
                        credibility_score=row["credibility_score"],
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return stories

    async def recent_asset_context(
        self,
        symbol: str,
        since: datetime,
        until: datetime,
        limit: int = 5,
    ) -> list[RecentAssetContextStory]:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            return []
        if not 1 <= limit <= 20:
            raise ValueError("limit must be between 1 and 20")

        response = await self._request(
            "GET",
            "/news_articles",
            params=[
                (
                    "select",
                    "title,summary,published_at,impact_level,credibility_score,news_assets!inner(symbol)",
                ),
                ("news_assets.symbol", f"eq.{normalized_symbol}"),
                ("published_at", f"gte.{since.isoformat()}"),
                ("published_at", f"lte.{until.isoformat()}"),
                ("order", "published_at.desc"),
                ("limit", str(limit)),
            ],
        )
        rows = response.json()
        if not isinstance(rows, list):
            return []

        stories: list[RecentAssetContextStory] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                stories.append(
                    RecentAssetContextStory(
                        title=row["title"],
                        summary=row.get("summary"),
                        published_at=row["published_at"],
                        impact_level=row["impact_level"],
                        credibility_score=row["credibility_score"],
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return stories

    async def persist_article(self, enriched: EnrichedNewsArticle) -> str:
        article = enriched.article
        payload = {
            "source": article.source.key,
            "source_url": article.source_url,
            "title": article.title,
            "summary": article.summary,
            "published_at": article.published_at.isoformat(),
            "sentiment": None,
            "impact_level": enriched.impact_level.value,
            "credibility_score": enriched.credibility_score,
            "content_fingerprint": enriched.content_fingerprint,
            "raw_data": {
                "source_name": article.source.name,
                "source_class": article.source.source_class.value,
                "feed_url": article.source.feed_url,
            },
        }
        response = await self._request(
            "POST",
            "/news_articles",
            params={"on_conflict": "source_url"},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            json=payload,
        )
        rows = response.json()
        if not isinstance(rows, list) or not rows or not rows[0].get("id"):
            raise SupabaseNewsRepositoryError("Supabase did not return a news article id")
        news_id = str(rows[0]["id"])

        if enriched.symbols:
            asset_payload = [
                {"news_id": news_id, "symbol": symbol} for symbol in enriched.symbols
            ]
            await self._request(
                "POST",
                "/news_assets",
                params={"on_conflict": "news_id,symbol"},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                json=asset_payload,
            )
        return news_id
