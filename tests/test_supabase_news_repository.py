from datetime import datetime, timezone

import httpx
import pytest

from btc_core.news.models import (
    EnrichedNewsArticle,
    NewsImpactLevel,
    NewsSource,
    NewsSourceClass,
    NormalizedArticle,
)
from btc_core.news.supabase_repo import SupabaseNewsRepository, SupabaseNewsRepositoryError


NOW = datetime(2026, 9, 8, 9, 30, tzinfo=timezone.utc)


def _enriched() -> EnrichedNewsArticle:
    source = NewsSource(
        key="sec_press",
        name="U.S. SEC Press Releases",
        feed_url="https://www.sec.gov/news/pressreleases.rss",
        source_class=NewsSourceClass.OFFICIAL_REGULATOR,
        credibility_score=95,
    )
    article = NormalizedArticle(
        source=source,
        title="SEC charges crypto exchange over Bitcoin product",
        source_url="https://www.sec.gov/newsroom/press-releases/2026-1",
        summary="Enforcement action",
        published_at=NOW,
    )
    return EnrichedNewsArticle(
        article=article,
        symbols=("BTCUSDT",),
        content_fingerprint="a" * 64,
        credibility_score=95,
        impact_level=NewsImpactLevel.HIGH,
        sentiment=None,
    )


@pytest.mark.asyncio
async def test_article_exists_and_recent_story_mapping():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/news_articles") and request.method == "GET":
            params = dict(request.url.params)
            if params.get("select") == "id":
                return httpx.Response(200, json=[{"id": "article-1"}])
            return httpx.Response(
                200,
                json=[
                    {
                        "title": "Bitcoin ETF approved",
                        "content_fingerprint": "story-1",
                        "published_at": "2026-09-08T09:00:00+00:00",
                        "raw_data": {"source_class": "OFFICIAL_REGULATOR"},
                        "news_assets": [{"symbol": "BTCUSDT"}],
                    },
                    {
                        "title": "Legacy story",
                        "content_fingerprint": "story-2",
                        "published_at": "2026-09-08T08:30:00+00:00",
                        "raw_data": {},
                        "news_assets": [],
                    },
                ],
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with SupabaseNewsRepository(
        supabase_url="https://project.supabase.co",
        api_key="secret",
        transport=httpx.MockTransport(handler),
    ) as repo:
        assert await repo.article_exists("https://example.com/story") is True
        stories = await repo.recent_stories(datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc))

    assert stories[0].symbols == ("BTCUSDT",)
    assert stories[0].source_class is NewsSourceClass.OFFICIAL_REGULATOR
    assert stories[1].source_class is NewsSourceClass.MEDIA
    assert dict(requests[0].url.params)["source_url"] == "eq.https://example.com/story"
    recent_params = dict(requests[1].url.params)
    assert recent_params["limit"] == "200"
    assert recent_params["order"] == "published_at.desc"


@pytest.mark.asyncio
async def test_article_exists_false_for_empty_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    async with SupabaseNewsRepository(
        supabase_url="https://project.supabase.co",
        api_key="secret",
        transport=httpx.MockTransport(handler),
    ) as repo:
        assert await repo.article_exists("https://example.com/missing") is False


@pytest.mark.asyncio
async def test_persist_article_upserts_article_and_assets_idempotently():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/news_articles"):
            assert request.method == "POST"
            assert dict(request.url.params)["on_conflict"] == "source_url"
            assert "resolution=merge-duplicates" in request.headers["prefer"]
            payload = __import__("json").loads(request.content)
            assert payload["sentiment"] is None
            assert payload["content_fingerprint"] == "a" * 64
            assert payload["raw_data"]["source_class"] == "OFFICIAL_REGULATOR"
            return httpx.Response(201, json=[{"id": "article-1"}])
        if request.url.path.endswith("/news_assets"):
            assert request.method == "POST"
            assert dict(request.url.params)["on_conflict"] == "news_id,symbol"
            payload = __import__("json").loads(request.content)
            assert payload == [{"news_id": "article-1", "symbol": "BTCUSDT"}]
            return httpx.Response(201, json=[])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    async with SupabaseNewsRepository(
        supabase_url="https://project.supabase.co",
        api_key="secret",
        transport=httpx.MockTransport(handler),
    ) as repo:
        assert await repo.persist_article(_enriched()) == "article-1"
        assert await repo.persist_article(_enriched()) == "article-1"

    assert len(calls) == 4


@pytest.mark.asyncio
async def test_repository_non_2xx_raises_typed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="database unavailable")

    async with SupabaseNewsRepository(
        supabase_url="https://project.supabase.co",
        api_key="secret",
        transport=httpx.MockTransport(handler),
    ) as repo:
        with pytest.raises(SupabaseNewsRepositoryError):
            await repo.article_exists("https://example.com/story")
