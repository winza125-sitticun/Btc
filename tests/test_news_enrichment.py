from datetime import datetime, timedelta, timezone

import httpx
import pytest


def test_news_score_uses_impact_credibility_and_recency_with_neutral_baseline():
    from btc_core.news.enrichment import NewsScoreStory, calculate_news_score
    from btc_core.news.models import NewsImpactLevel

    now = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)

    assert calculate_news_score([], now=now) == 50.0

    recent_high = NewsScoreStory(
        published_at=now,
        impact_level=NewsImpactLevel.HIGH,
        credibility_score=100,
    )
    assert calculate_news_score([recent_high], now=now) == 62.0

    older_medium = NewsScoreStory(
        published_at=now - timedelta(hours=12),
        impact_level=NewsImpactLevel.MEDIUM,
        credibility_score=100,
    )
    assert calculate_news_score([older_medium], now=now) == 53.0

    expired_high = NewsScoreStory(
        published_at=now - timedelta(hours=24),
        impact_level=NewsImpactLevel.HIGH,
        credibility_score=100,
    )
    assert calculate_news_score([expired_high], now=now) == 50.0

    future_high = NewsScoreStory(
        published_at=now + timedelta(minutes=1),
        impact_level=NewsImpactLevel.HIGH,
        credibility_score=100,
    )
    assert calculate_news_score([future_high], now=now) == 50.0


def test_news_score_caps_at_100():
    from btc_core.news.enrichment import NewsScoreStory, calculate_news_score
    from btc_core.news.models import NewsImpactLevel

    now = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)
    stories = [
        NewsScoreStory(
            published_at=now,
            impact_level=NewsImpactLevel.HIGH,
            credibility_score=100,
        )
        for _ in range(10)
    ]

    assert calculate_news_score(stories, now=now) == 100.0


@pytest.mark.asyncio
async def test_recent_news_score_provider_uses_24_hour_window():
    from btc_core.news.enrichment import NewsScoreStory, RecentNewsScoreProvider
    from btc_core.news.models import NewsImpactLevel

    now = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)

    class FakeRepo:
        def __init__(self):
            self.calls = []

        async def recent_asset_news(self, symbol, since, until, limit=50):
            self.calls.append((symbol, since, until, limit))
            return [
                NewsScoreStory(
                    published_at=now,
                    impact_level=NewsImpactLevel.HIGH,
                    credibility_score=100,
                )
            ]

    repo = FakeRepo()
    provider = RecentNewsScoreProvider(repo=repo, now_factory=lambda: now)

    assert await provider.score("btcusdt") == 62.0
    assert repo.calls == [("BTCUSDT", now - timedelta(hours=24), now, 50)]


@pytest.mark.asyncio
async def test_supabase_recent_asset_news_filters_symbol_and_closed_window():
    from btc_core.news.models import NewsImpactLevel
    from btc_core.news.supabase_repo import SupabaseNewsRepository

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "published_at": "2026-09-10T02:30:00+00:00",
                    "impact_level": "HIGH",
                    "credibility_score": 95,
                    "news_assets": [{"symbol": "BTCUSDT"}],
                }
            ],
        )

    since = datetime(2026, 9, 9, 3, 0, tzinfo=timezone.utc)
    until = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)
    async with SupabaseNewsRepository(
        supabase_url="https://project.supabase.co",
        api_key="secret",
        transport=httpx.MockTransport(handler),
    ) as repo:
        stories = await repo.recent_asset_news("btcusdt", since, until, limit=50)

    assert len(stories) == 1
    assert stories[0].impact_level is NewsImpactLevel.HIGH
    assert stories[0].credibility_score == 95
    params = requests[0].url.params
    assert params["news_assets.symbol"] == "eq.BTCUSDT"
    assert params.get_list("published_at") == [
        f"gte.{since.isoformat()}",
        f"lte.{until.isoformat()}",
    ]
    assert params["order"] == "published_at.desc"
    assert params["limit"] == "50"
