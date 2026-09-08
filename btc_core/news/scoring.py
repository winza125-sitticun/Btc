from __future__ import annotations

from btc_core.news.models import NormalizedArticle, NewsImpactLevel, NewsSourceClass


HIGH_GENERAL = {
    "etf approved",
    "etf approval",
    "etf rejected",
    "etf rejection",
    "exploit",
    "hacked",
    "hack",
    "chain halt",
    "network halt",
    "withdrawal halt",
    "withdrawals halted",
    "insolvency",
    "bankruptcy",
    "emergency rate",
    "emergency meeting",
}
REGULATOR_HIGH = {"charges", "charged", "enforcement", "lawsuit", "settlement"}
STATUS_HIGH = {"outage", "withdrawal", "degraded", "unavailable", "incident"}
MEDIUM_GENERAL = {
    "upgrade",
    "mainnet",
    "listing",
    "listed",
    "partnership",
    "adoption",
    "fomc",
    "rate decision",
}


def credibility_for(article: NormalizedArticle) -> float:
    return float(article.source.credibility_score)


def _article_text(article: NormalizedArticle) -> str:
    value = article.title if not article.summary else f"{article.title}\n{article.summary}"
    return value.casefold()


def _contains_any(text: str, phrases: set[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def classify_impact(article: NormalizedArticle, symbols: tuple[str, ...]) -> NewsImpactLevel:
    text = _article_text(article)
    if _contains_any(text, HIGH_GENERAL):
        return NewsImpactLevel.HIGH
    if (
        article.source.source_class is NewsSourceClass.OFFICIAL_REGULATOR
        and bool(symbols)
        and _contains_any(text, REGULATOR_HIGH)
    ):
        return NewsImpactLevel.HIGH
    if (
        article.source.source_class is NewsSourceClass.EXCHANGE_STATUS
        and _contains_any(text, STATUS_HIGH)
    ):
        return NewsImpactLevel.HIGH
    if _contains_any(text, MEDIUM_GENERAL):
        return NewsImpactLevel.MEDIUM
    return NewsImpactLevel.LOW
