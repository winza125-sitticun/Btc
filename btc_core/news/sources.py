from btc_core.news.models import NewsSource, NewsSourceClass


DEFAULT_NEWS_SOURCES = (
    NewsSource(
        key="sec_press",
        name="U.S. SEC Press Releases",
        feed_url="https://www.sec.gov/news/pressreleases.rss",
        source_class=NewsSourceClass.OFFICIAL_REGULATOR,
        credibility_score=95,
    ),
    NewsSource(
        key="cftc_general",
        name="CFTC General Press Releases",
        feed_url="https://www.cftc.gov/RSS/RSSGP/rssgp.xml",
        source_class=NewsSourceClass.OFFICIAL_REGULATOR,
        credibility_score=95,
    ),
    NewsSource(
        key="cftc_enforcement",
        name="CFTC Enforcement Press Releases",
        feed_url="https://www.cftc.gov/RSS/RSSENF/rssenf.xml",
        source_class=NewsSourceClass.OFFICIAL_REGULATOR,
        credibility_score=95,
    ),
    NewsSource(
        key="fed_press",
        name="Federal Reserve Press Releases",
        feed_url="https://www.federalreserve.gov/feeds/press_all.xml",
        source_class=NewsSourceClass.OFFICIAL_REGULATOR,
        credibility_score=95,
    ),
    NewsSource(
        key="fed_monetary",
        name="Federal Reserve Monetary Policy",
        feed_url="https://www.federalreserve.gov/feeds/press_monetary.xml",
        source_class=NewsSourceClass.OFFICIAL_REGULATOR,
        credibility_score=95,
    ),
    NewsSource(
        key="coinbase_status",
        name="Coinbase Status",
        feed_url="https://status.coinbase.com/history.rss",
        source_class=NewsSourceClass.EXCHANGE_STATUS,
        credibility_score=92,
    ),
    NewsSource(
        key="ethereum_blog",
        name="Ethereum Foundation Blog",
        feed_url="https://blog.ethereum.org/feed.xml",
        source_class=NewsSourceClass.OFFICIAL_PROJECT,
        credibility_score=92,
    ),
    NewsSource(
        key="coindesk",
        name="CoinDesk",
        feed_url="https://www.coindesk.com/arc/outboundfeeds/rss/",
        source_class=NewsSourceClass.MEDIA,
        credibility_score=80,
    ),
)
