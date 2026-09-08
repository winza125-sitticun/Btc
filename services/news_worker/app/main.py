from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os

from btc_core.news.dedup import resolve_content_fingerprint
from btc_core.news.models import EnrichedNewsArticle, NewsPollResult, NewsSource
from btc_core.news.normalize import normalize_article
from btc_core.news.rss import NewsFeedClient, NewsFeedError
from btc_core.news.scoring import classify_impact, credibility_for
from btc_core.news.sources import DEFAULT_NEWS_SOURCES
from btc_core.news.supabase_repo import SupabaseNewsRepository
from btc_core.news.tagging import tag_core_assets


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    value = default if raw is None else float(raw)
    return max(minimum, min(maximum, value))


async def run_poll_cycle(
    *,
    sources: tuple[NewsSource, ...] | list[NewsSource],
    feed_client,
    repo,
    concurrency: int,
    now: datetime,
) -> NewsPollResult:
    if not 1 <= concurrency <= 10:
        raise ValueError("concurrency must be between 1 and 10")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    enabled_sources = [source for source in sources if source.enabled]
    semaphore = asyncio.Semaphore(concurrency)

    async def fetch_one(source: NewsSource):
        async with semaphore:
            try:
                return await feed_client.fetch(source), None
            except NewsFeedError as exc:
                return None, exc

    fetched = await asyncio.gather(*(fetch_one(source) for source in enabled_sources))

    sources_succeeded = 0
    sources_failed = 0
    entries_parsed = 0
    inserted = 0
    duplicates = 0
    malformed_entries = 0
    recent_since = now.astimezone(timezone.utc) - timedelta(hours=24)

    for source, (result, error) in zip(enabled_sources, fetched, strict=True):
        if error is not None:
            sources_failed += 1
            print(f"news source failed source={source.key} error={error}")
            continue
        if result is None:
            sources_failed += 1
            continue

        sources_succeeded += 1
        entries_parsed += len(result.entries)
        malformed_entries += result.malformed_entries

        for raw_entry in result.entries:
            try:
                article = normalize_article(raw_entry)
            except (TypeError, ValueError):
                malformed_entries += 1
                continue

            if await repo.article_exists(article.source_url):
                duplicates += 1
                continue

            symbols = tag_core_assets(article)
            recent = await repo.recent_stories(recent_since)
            fingerprint = resolve_content_fingerprint(
                article,
                symbols,
                recent,
                now=now,
            )
            enriched = EnrichedNewsArticle(
                article=article,
                symbols=symbols,
                content_fingerprint=fingerprint,
                credibility_score=credibility_for(article),
                impact_level=classify_impact(article, symbols),
                sentiment=None,
            )
            await repo.persist_article(enriched)
            inserted += 1

    return NewsPollResult(
        sources_succeeded=sources_succeeded,
        sources_failed=sources_failed,
        entries_parsed=entries_parsed,
        inserted=inserted,
        duplicates=duplicates,
        malformed_entries=malformed_entries,
    )


async def run_forever() -> None:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not supabase_url or not service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for news worker")

    poll_seconds = _env_float("NEWS_POLL_SECONDS", 120.0, minimum=30.0, maximum=3600.0)
    timeout_seconds = _env_float(
        "NEWS_HTTP_TIMEOUT_SECONDS", 10.0, minimum=2.0, maximum=60.0
    )
    concurrency = _env_int("NEWS_FETCH_CONCURRENCY", 4, minimum=1, maximum=10)

    async with NewsFeedClient(timeout_seconds=timeout_seconds) as feed_client, SupabaseNewsRepository(
        supabase_url=supabase_url,
        api_key=service_role_key,
    ) as repo:
        while True:
            try:
                result = await run_poll_cycle(
                    sources=DEFAULT_NEWS_SOURCES,
                    feed_client=feed_client,
                    repo=repo,
                    concurrency=concurrency,
                    now=datetime.now(timezone.utc),
                )
                print(
                    "news cycle complete "
                    f"sources_ok={result.sources_succeeded} "
                    f"sources_failed={result.sources_failed} "
                    f"parsed={result.entries_parsed} inserted={result.inserted} "
                    f"duplicates={result.duplicates} malformed={result.malformed_entries}"
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"news worker cycle failed: {exc}")
            await asyncio.sleep(poll_seconds)


def main() -> None:
    asyncio.run(run_forever())


if __name__ == "__main__":
    main()
