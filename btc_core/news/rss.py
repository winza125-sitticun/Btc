from __future__ import annotations

from datetime import datetime, timezone

import feedparser
import httpx

from btc_core.news.models import FeedFetchResult, NewsSource, RawFeedEntry


class NewsFeedError(RuntimeError):
    pass


class NewsFeedClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 2_000_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        self._max_response_bytes = max_response_bytes
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
            follow_redirects=True,
            headers={
                "User-Agent": "btc-ai-futures-news-worker/0.1 (+https://github.com/winza125-sitticun/Btc)"
            },
        )

    async def __aenter__(self) -> "NewsFeedClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, source: NewsSource) -> FeedFetchResult:
        try:
            response = await self._client.get(source.feed_url)
        except httpx.HTTPError as exc:
            raise NewsFeedError(f"feed request failed for {source.key}: {exc}") from exc

        if response.is_error:
            raise NewsFeedError(f"feed HTTP {response.status_code} for {source.key}")

        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self._max_response_bytes:
                    raise NewsFeedError(f"feed response too large for {source.key}")
            except ValueError:
                pass

        content = response.content
        if len(content) > self._max_response_bytes:
            raise NewsFeedError(f"feed response too large for {source.key}")

        parsed = feedparser.parse(content)
        if getattr(parsed, "bozo", False) and not parsed.entries:
            raise NewsFeedError(f"feed parse failed for {source.key}")

        entries: list[RawFeedEntry] = []
        malformed_entries = 0
        for item in parsed.entries:
            title = str(item.get("title") or "").strip()
            url = str(item.get("link") or "").strip()
            time_value = item.get("published_parsed") or item.get("updated_parsed")
            if not title or not url or not time_value:
                malformed_entries += 1
                continue
            try:
                published_at = datetime(*time_value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                malformed_entries += 1
                continue

            summary_value = item.get("summary") or item.get("description")
            summary = None if summary_value is None else str(summary_value)
            entries.append(
                RawFeedEntry(
                    source=source,
                    title=title,
                    url=url,
                    summary=summary,
                    published_at=published_at,
                )
            )

        return FeedFetchResult(
            source=source,
            entries=tuple(entries),
            malformed_entries=malformed_entries,
        )
