import re
from datetime import datetime, timedelta, timezone

from btc_core.news.dedup import resolve_content_fingerprint
from btc_core.news.models import NormalizedArticle, NewsSource, NewsSourceClass, RecentNewsStory


NOW = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)


def _article(title: str, source_class: NewsSourceClass = NewsSourceClass.OFFICIAL_REGULATOR):
    source = NewsSource(
        key="new",
        name="New Source",
        feed_url="https://feed.example/rss",
        source_class=source_class,
        credibility_score=95,
    )
    return NormalizedArticle(
        source=source,
        title=title,
        source_url="https://example.com/new",
        published_at=NOW,
    )


def _recent(
    title: str,
    *,
    fingerprint: str = "story-123",
    age: timedelta = timedelta(minutes=10),
    symbols: tuple[str, ...] = ("BTCUSDT",),
    source_class: NewsSourceClass = NewsSourceClass.MEDIA,
):
    return RecentNewsStory(
        title=title,
        content_fingerprint=fingerprint,
        published_at=NOW - age,
        symbols=symbols,
        source_class=source_class,
    )


def test_near_duplicate_reuses_existing_fingerprint():
    article = _article("SEC charges crypto exchange over Bitcoin ETF product")
    recent = _recent("Bitcoin ETF product SEC charges crypto exchange over")
    assert resolve_content_fingerprint(article, ("BTCUSDT",), [recent], now=NOW) == "story-123"


def test_old_unrelated_or_different_asset_stories_are_not_reused():
    article = _article("Bitcoin ETF approval expands institutional access")
    old = _recent(
        "Bitcoin ETF approval expands institutional access",
        fingerprint="old",
        age=timedelta(hours=25),
    )
    unrelated = _recent("Bitcoin mining difficulty changes", fingerprint="unrelated")
    wrong_asset = _recent(
        "Bitcoin ETF approval expands institutional access",
        fingerprint="sol-story",
        symbols=("SOLUSDT",),
    )

    result = resolve_content_fingerprint(article, ("BTCUSDT",), [old, unrelated, wrong_asset], now=NOW)
    assert result not in {"old", "unrelated", "sol-story"}
    assert re.fullmatch(r"[0-9a-f]{64}", result)


def test_untagged_story_requires_matching_source_class():
    article = _article("Federal policy statement released", NewsSourceClass.OFFICIAL_REGULATOR)
    same_class = _recent(
        "Federal policy statement released",
        fingerprint="reg-story",
        symbols=(),
        source_class=NewsSourceClass.OFFICIAL_REGULATOR,
    )
    other_class = _recent(
        "Federal policy statement released",
        fingerprint="media-story",
        symbols=(),
        source_class=NewsSourceClass.MEDIA,
    )

    assert resolve_content_fingerprint(article, (), [other_class, same_class], now=NOW) == "reg-story"
