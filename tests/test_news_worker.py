from datetime import datetime, timedelta, timezone

import pytest

from btc_core.news.models import (
    FeedFetchResult,
    NewsSource,
    NewsSourceClass,
    RawFeedEntry,
)
from btc_core.news.rss import NewsFeedError
from services.news_worker.app.main import run_poll_cycle


NOW = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)


def _source(key: str) -> NewsSource:
    return NewsSource(
        key=key,
        name=key,
        feed_url=f"https://{key}.example/feed",
        source_class=NewsSourceClass.MEDIA,
        credibility_score=80,
    )


def _entry(source: NewsSource, *, url: str = "https://example.com/story") -> RawFeedEntry:
    return RawFeedEntry(
        source=source,
        title="Bitcoin ETF approved",
        url=url,
        summary="Bitcoin market update",
        published_at=NOW - timedelta(minutes=5),
    )


class FakeFeedClient:
    def __init__(self, outcomes):
        self.outcomes = outcomes

    async def fetch(self, source):
        outcome = self.outcomes[source.key]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeRepo:
    def __init__(self, *, existing=None, fail_persist=False):
        self.existing = set(existing or ())
        self.fail_persist = fail_persist
        self.persisted = []
        self.recent_since = []

    async def article_exists(self, source_url):
        return source_url in self.existing

    async def recent_stories(self, since):
        self.recent_since.append(since)
        return []

    async def persist_article(self, enriched):
        if self.fail_persist:
            raise RuntimeError("database unavailable")
        self.persisted.append(enriched)
        self.existing.add(enriched.article.source_url)
        return f"article-{len(self.persisted)}"


@pytest.mark.asyncio
async def test_poll_cycle_isolates_source_failure_and_persists_success():
    good = _source("good")
    bad = _source("bad")
    feed_client = FakeFeedClient(
        {
            "good": FeedFetchResult(source=good, entries=(_entry(good),), malformed_entries=2),
            "bad": NewsFeedError("feed unavailable"),
        }
    )
    repo = FakeRepo()

    result = await run_poll_cycle(
        sources=(good, bad),
        feed_client=feed_client,
        repo=repo,
        concurrency=2,
        now=NOW,
    )

    assert result.sources_succeeded == 1
    assert result.sources_failed == 1
    assert result.entries_parsed == 1
    assert result.inserted == 1
    assert result.duplicates == 0
    assert result.malformed_entries == 2
    assert len(repo.persisted) == 1
    assert repo.persisted[0].symbols == ("BTCUSDT",)
    assert repo.persisted[0].sentiment is None
    assert repo.recent_since == [NOW - timedelta(hours=24)]


@pytest.mark.asyncio
async def test_exact_duplicate_is_skipped_before_enrichment():
    source = _source("good")
    entry = _entry(source, url="https://example.com/duplicate")
    feed_client = FakeFeedClient(
        {"good": FeedFetchResult(source=source, entries=(entry,), malformed_entries=0)}
    )
    repo = FakeRepo(existing={"https://example.com/duplicate"})

    result = await run_poll_cycle(
        sources=(source,),
        feed_client=feed_client,
        repo=repo,
        concurrency=1,
        now=NOW,
    )

    assert result.duplicates == 1
    assert result.inserted == 0
    assert repo.persisted == []
    assert repo.recent_since == []


@pytest.mark.asyncio
async def test_repository_failure_escapes_poll_cycle():
    source = _source("good")
    feed_client = FakeFeedClient(
        {"good": FeedFetchResult(source=source, entries=(_entry(source),), malformed_entries=0)}
    )
    repo = FakeRepo(fail_persist=True)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await run_poll_cycle(
            sources=(source,),
            feed_client=feed_client,
            repo=repo,
            concurrency=1,
            now=NOW,
        )
