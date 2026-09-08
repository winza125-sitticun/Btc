from __future__ import annotations

from datetime import timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import unicodedata

from btc_core.news.models import NormalizedArticle, RawFeedEntry


TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def canonicalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    kept = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(kept, doseq=True), "")
    )


def _plain_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return normalize_text(parser.text())


def normalize_article(entry: RawFeedEntry) -> NormalizedArticle:
    title = normalize_text(entry.title)
    source_url = canonicalize_url(entry.url)
    parts = urlsplit(source_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("news article URL must use http or https")
    if not title:
        raise ValueError("news article title is required")

    published_at = entry.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    else:
        published_at = published_at.astimezone(timezone.utc)

    summary = None
    if entry.summary:
        plain = _plain_text(entry.summary)
        summary = plain or None

    return NormalizedArticle(
        source=entry.source,
        title=title,
        source_url=source_url,
        summary=summary,
        published_at=published_at,
    )
