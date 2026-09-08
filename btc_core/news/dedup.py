from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
import re
import unicodedata

from btc_core.news.models import NormalizedArticle, RecentNewsStory


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
}

WINDOW = timedelta(hours=24)
SIMILARITY_THRESHOLD = 0.82


def normalized_title_tokens(title: str, source_name: str | None = None) -> tuple[str, ...]:
    value = unicodedata.normalize("NFKC", title).strip()
    if source_name:
        suffix = re.compile(
            rf"\s+(?:-|\|)\s*{re.escape(unicodedata.normalize('NFKC', source_name))}\s*$",
            re.IGNORECASE,
        )
        value = suffix.sub("", value)
    value = value.casefold()
    value = "".join(char if char.isalnum() or char.isspace() else " " for char in value)
    tokens = {token for token in value.split() if token and token not in STOPWORDS}
    return tuple(sorted(tokens))


def jaccard_similarity(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def resolve_content_fingerprint(
    article: NormalizedArticle,
    symbols: tuple[str, ...],
    recent: list[RecentNewsStory],
    *,
    now: datetime,
) -> str:
    article_tokens = normalized_title_tokens(article.title, article.source.name)
    cutoff = now - WINDOW
    symbol_set = set(symbols)

    best_story: RecentNewsStory | None = None
    best_similarity = -1.0
    for story in recent:
        if story.published_at < cutoff or not story.content_fingerprint:
            continue
        if symbol_set:
            if not symbol_set.intersection(story.symbols):
                continue
        elif story.source_class is not article.source.source_class:
            continue

        similarity = jaccard_similarity(article_tokens, normalized_title_tokens(story.title))
        if similarity > best_similarity or (
            similarity == best_similarity
            and best_story is not None
            and story.published_at > best_story.published_at
        ):
            best_story = story
            best_similarity = similarity

    if best_story is not None and best_similarity >= SIMILARITY_THRESHOLD:
        return str(best_story.content_fingerprint)

    canonical = " ".join(article_tokens).encode("utf-8")
    return sha256(canonical).hexdigest()
