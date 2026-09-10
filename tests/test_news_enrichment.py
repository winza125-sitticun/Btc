from datetime import datetime, timedelta, timezone


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
