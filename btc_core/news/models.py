from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class NewsSourceClass(str, Enum):
    OFFICIAL_REGULATOR = "OFFICIAL_REGULATOR"
    OFFICIAL_PROJECT = "OFFICIAL_PROJECT"
    EXCHANGE_STATUS = "EXCHANGE_STATUS"
    MEDIA = "MEDIA"


class NewsImpactLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class NewsSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    name: str
    feed_url: str
    source_class: NewsSourceClass
    credibility_score: float = Field(ge=0, le=100)
    enabled: bool = True


class RawFeedEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: NewsSource
    title: str
    url: str
    summary: str | None = None
    published_at: datetime


class NormalizedArticle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: NewsSource
    title: str
    source_url: str
    summary: str | None = None
    published_at: datetime


class RecentNewsStory(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    content_fingerprint: str | None = None
    published_at: datetime
    symbols: tuple[str, ...] = ()
    source_class: NewsSourceClass


class EnrichedNewsArticle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    article: NormalizedArticle
    symbols: tuple[str, ...]
    content_fingerprint: str
    credibility_score: float = Field(ge=0, le=100)
    impact_level: NewsImpactLevel
    sentiment: float | None = None


class FeedFetchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: NewsSource
    entries: tuple[RawFeedEntry, ...] = ()
    malformed_entries: int = Field(default=0, ge=0)


class NewsPollResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sources_succeeded: int = Field(ge=0)
    sources_failed: int = Field(ge=0)
    entries_parsed: int = Field(ge=0)
    inserted: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    malformed_entries: int = Field(ge=0)
