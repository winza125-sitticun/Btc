from datetime import datetime, timezone

from btc_core.news.models import NormalizedArticle, NewsImpactLevel, NewsSource, NewsSourceClass
from btc_core.news.scoring import classify_impact, credibility_for
from btc_core.news.tagging import tag_core_assets, tag_text


NOW = datetime(2026, 9, 8, 8, 0, tzinfo=timezone.utc)


def _article(text: str, source_class: NewsSourceClass, credibility: float = 80) -> NormalizedArticle:
    source = NewsSource(
        key="test",
        name="Test",
        feed_url="https://feed.example/rss",
        source_class=source_class,
        credibility_score=credibility,
    )
    return NormalizedArticle(
        source=source,
        title=text,
        source_url="https://example.com/story",
        summary=None,
        published_at=NOW,
    )


def test_core_asset_tagging_is_conservative():
    assert tag_text("Bitcoin ETF decision") == ("BTCUSDT",)
    assert tag_text("Ethereum and Ether upgrade") == ("ETHUSDT",)
    assert tag_text("Solana network update") == ("SOLUSDT",)
    assert tag_text("Ripple expands XRPL support for XRP") == ("XRPUSDT",)
    assert tag_text("BTC and ETH market update") == ("BTCUSDT", "ETHUSDT")
    assert tag_text("gas prices rise as one market changes") == ()
    assert tag_text("solid growth outlook") == ()


def test_tag_core_assets_uses_title_and_summary():
    article = _article("Market update", NewsSourceClass.MEDIA).model_copy(
        update={"summary": "Bitcoin and Solana activity increases"}
    )
    assert tag_core_assets(article) == ("BTCUSDT", "SOLUSDT")


def test_deterministic_impact_and_credibility():
    regulator = _article(
        "SEC charges crypto exchange over Bitcoin product",
        NewsSourceClass.OFFICIAL_REGULATOR,
        95,
    )
    status = _article("Exchange withdrawal outage continues", NewsSourceClass.EXCHANGE_STATUS, 92)
    project = _article("Ethereum protocol upgrade released", NewsSourceClass.OFFICIAL_PROJECT, 92)
    media = _article("Daily market commentary", NewsSourceClass.MEDIA, 80)

    assert classify_impact(regulator, ("BTCUSDT",)) is NewsImpactLevel.HIGH
    assert classify_impact(status, ()) is NewsImpactLevel.HIGH
    assert classify_impact(project, ("ETHUSDT",)) is NewsImpactLevel.MEDIUM
    assert classify_impact(media, ()) is NewsImpactLevel.LOW
    assert credibility_for(regulator) == 95
    assert credibility_for(media) == 80
