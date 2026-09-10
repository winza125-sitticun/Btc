import httpx
import pytest

from btc_core.news.models import NewsSource, NewsSourceClass
from btc_core.news.normalize import normalize_article
from btc_core.news.rss import NewsFeedClient


RSS_XML = b'''<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>  Bitcoin   ETF approved  </title>
<link>https://example.com/story?utm_source=rss&amp;id=42#top</link>
<description><![CDATA[<p>Market <b>update</b></p>]]></description>
<pubDate>Tue, 08 Sep 2026 08:00:00 GMT</pubDate>
</item>
<item>
<link>https://example.com/malformed</link>
<pubDate>Tue, 08 Sep 2026 08:01:00 GMT</pubDate>
</item>
</channel></rss>'''

ATOM_XML = b'''<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<title>Ethereum upgrade released</title>
<link href="https://example.com/eth-upgrade" />
<updated>2026-09-08T08:05:00Z</updated>
<summary>Protocol release</summary>
</entry></feed>'''


def _source(url: str) -> NewsSource:
    return NewsSource(
        key="test",
        name="Test Source",
        feed_url=url,
        source_class=NewsSourceClass.MEDIA,
        credibility_score=80,
    )


@pytest.mark.asyncio
async def test_fetch_rss_isolates_malformed_entry_and_normalizes_article():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS_XML)

    client = NewsFeedClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.fetch(_source("https://feed.example/rss"))
    finally:
        await client.aclose()

    assert len(result.entries) == 1
    assert result.malformed_entries == 1

    article = normalize_article(result.entries[0])
    assert article.title == "Bitcoin ETF approved"
    assert article.source_url == "https://example.com/story?id=42"
    assert article.summary == "Market update"
    assert article.published_at.isoformat() == "2026-09-08T08:00:00+00:00"


@pytest.mark.asyncio
async def test_fetch_atom_uses_updated_timestamp():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=ATOM_XML)

    client = NewsFeedClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.fetch(_source("https://feed.example/atom"))
    finally:
        await client.aclose()

    assert len(result.entries) == 1
    article = normalize_article(result.entries[0])
    assert article.title == "Ethereum upgrade released"
    assert article.published_at.isoformat() == "2026-09-08T08:05:00+00:00"


@pytest.mark.asyncio
async def test_fetch_follows_http_redirect_to_feed():
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if str(request.url) == "https://feed.example/rss":
            return httpx.Response(
                301,
                headers={"Location": "https://feed.example/en/rss.xml"},
            )
        if str(request.url) == "https://feed.example/en/rss.xml":
            return httpx.Response(200, content=RSS_XML)
        return httpx.Response(404)

    client = NewsFeedClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.fetch(_source("https://feed.example/rss"))
    finally:
        await client.aclose()

    assert len(result.entries) == 1
    assert seen_urls == [
        "https://feed.example/rss",
        "https://feed.example/en/rss.xml",
    ]
