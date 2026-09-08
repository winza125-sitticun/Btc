from btc_core.news.models import NewsSourceClass
from btc_core.news.sources import DEFAULT_NEWS_SOURCES


def test_default_sources_are_unique_and_reviewed():
    keys = [source.key for source in DEFAULT_NEWS_SOURCES]
    assert len(keys) == len(set(keys))
    assert set(keys) == {
        "sec_press",
        "cftc_general",
        "cftc_enforcement",
        "fed_press",
        "fed_monetary",
        "coinbase_status",
        "ethereum_blog",
        "coindesk",
    }
    assert any(s.source_class is NewsSourceClass.OFFICIAL_REGULATOR for s in DEFAULT_NEWS_SOURCES)
    assert any(s.source_class is NewsSourceClass.EXCHANGE_STATUS for s in DEFAULT_NEWS_SOURCES)
    assert any(s.source_class is NewsSourceClass.MEDIA for s in DEFAULT_NEWS_SOURCES)
    assert all(s.enabled for s in DEFAULT_NEWS_SOURCES)
    assert all(0 <= s.credibility_score <= 100 for s in DEFAULT_NEWS_SOURCES)
