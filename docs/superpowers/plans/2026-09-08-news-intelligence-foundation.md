# News Intelligence Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, read-only RSS/Atom news worker that stores normalized, deduplicated, asset-tagged news in Supabase without changing scanner scoring or trading behavior.

**Architecture:** Add a focused `btc_core.news` package for feed sources, fetching/parsing, normalization, exact/near duplicate handling, core-asset tagging, deterministic metadata scoring, and Supabase persistence. Add a separate long-running `services.news_worker` process on Railway. The scanner remains market-only in Phase 5A with `news=50.0` and `macro=50.0`.

**Tech Stack:** Python 3.12+, Pydantic 2, httpx, feedparser 6, Supabase PostgREST, pytest, pytest-asyncio, Railway.

**Spec:** `docs/superpowers/specs/2026-09-08-news-intelligence-foundation-design.md`

## Global Constraints

- `TRADING_MODE=SIMULATION`.
- AI Direct Order remains `OFF`.
- Binance authenticated order execution remains unimplemented.
- No AI provider is called in Phase 5A.
- Scanner `news` and `macro` inputs remain exactly `50.0`.
- Scanner weights remain unchanged.
- News ingestion is read-only with respect to external providers.
- `news_articles.source_url UNIQUE` remains the exact duplicate boundary.
- Near-duplicate window: 24 hours.
- Near-duplicate Jaccard threshold: `0.82`.
- Default news poll interval: 120 seconds.
- Production validation requires successful ingestion from at least four distinct verified sources.
- No public RLS policy is added to `news_articles` or `news_assets`.
- If a feed is no longer stable RSS/Atom, disable it rather than scrape HTML pages.
- `SUPABASE_SERVICE_ROLE_KEY` exists only in server-side Railway configuration.
- Do not add Binance keys, AI keys, withdrawal credentials, or authenticated exchange actions to `news-worker`.

## File Map

Create:
- `btc_core/news/__init__.py`
- `btc_core/news/models.py`
- `btc_core/news/sources.py`
- `btc_core/news/rss.py`
- `btc_core/news/normalize.py`
- `btc_core/news/tagging.py`
- `btc_core/news/dedup.py`
- `btc_core/news/scoring.py`
- `btc_core/news/supabase_repo.py`
- `services/news_worker/__init__.py`
- `services/news_worker/app/__init__.py`
- `services/news_worker/app/main.py`
- `supabase/migrations/202609080006_news_intelligence_foundation.sql`
- `tests/test_news_models_sources.py`
- `tests/test_news_rss_normalize.py`
- `tests/test_news_tagging_scoring.py`
- `tests/test_news_dedup.py`
- `tests/test_supabase_news_repository.py`
- `tests/test_news_migration.py`
- `tests/test_news_worker.py`

Modify:
- `pyproject.toml`
- `.env.example`
- `tests/test_market_features.py`

---

### Task 1: News Models, Source Catalog, and Parser Dependency

**Files:**
- Modify: `pyproject.toml`
- Create: `btc_core/news/__init__.py`
- Create: `btc_core/news/models.py`
- Create: `btc_core/news/sources.py`
- Test: `tests/test_news_models_sources.py`

**Interfaces:**
- Produces `NewsSourceClass`, `NewsImpactLevel`, `NewsSource`, `RawFeedEntry`, `NormalizedArticle`, `RecentNewsStory`, `EnrichedNewsArticle`, `FeedFetchResult`, `NewsPollResult`, and `DEFAULT_NEWS_SOURCES`.

- [ ] **Step 1: Write the failing source-catalog test**

```python
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
```

- [ ] **Step 2: Verify RED**

```bash
pytest tests/test_news_models_sources.py -q
```

Expected: import failure because `btc_core.news` does not exist.

- [ ] **Step 3: Add the parser dependency**

Add this dependency to `pyproject.toml`:

```toml
"feedparser>=6.0.11,<7",
```

- [ ] **Step 4: Implement validated models**

Use these exact model contracts:

```python
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
```

- [ ] **Step 5: Implement the V1 catalog**

```python
DEFAULT_NEWS_SOURCES = (
    NewsSource(key="sec_press", name="U.S. SEC Press Releases", feed_url="https://www.sec.gov/news/pressreleases.rss", source_class=NewsSourceClass.OFFICIAL_REGULATOR, credibility_score=95),
    NewsSource(key="cftc_general", name="CFTC General Press Releases", feed_url="https://www.cftc.gov/RSS/RSSGP/rssgp.xml", source_class=NewsSourceClass.OFFICIAL_REGULATOR, credibility_score=95),
    NewsSource(key="cftc_enforcement", name="CFTC Enforcement Press Releases", feed_url="https://www.cftc.gov/RSS/RSSENF/rssenf.xml", source_class=NewsSourceClass.OFFICIAL_REGULATOR, credibility_score=95),
    NewsSource(key="fed_press", name="Federal Reserve Press Releases", feed_url="https://www.federalreserve.gov/feeds/press_all.xml", source_class=NewsSourceClass.OFFICIAL_REGULATOR, credibility_score=95),
    NewsSource(key="fed_monetary", name="Federal Reserve Monetary Policy", feed_url="https://www.federalreserve.gov/feeds/press_monetary.xml", source_class=NewsSourceClass.OFFICIAL_REGULATOR, credibility_score=95),
    NewsSource(key="coinbase_status", name="Coinbase Status", feed_url="https://status.coinbase.com/history.rss", source_class=NewsSourceClass.EXCHANGE_STATUS, credibility_score=92),
    NewsSource(key="ethereum_blog", name="Ethereum Foundation Blog", feed_url="https://blog.ethereum.org/feed.xml", source_class=NewsSourceClass.OFFICIAL_PROJECT, credibility_score=92),
    NewsSource(key="coindesk", name="CoinDesk", feed_url="https://www.coindesk.com/arc/outboundfeeds/rss/", source_class=NewsSourceClass.MEDIA, credibility_score=80),
)
```

No worker branch may special-case a source key.

- [ ] **Step 6: Verify GREEN and commit**

```bash
pytest tests/test_news_models_sources.py -q
pytest -q
git add pyproject.toml btc_core/news tests/test_news_models_sources.py
git commit -m "feat: define news models and sources"
```

---

### Task 2: RSS/Atom Fetching and Normalization

**Files:**
- Create: `btc_core/news/rss.py`
- Create: `btc_core/news/normalize.py`
- Test: `tests/test_news_rss_normalize.py`

**Interfaces:**
- Produces `NewsFeedError`, `NewsFeedClient.fetch(source: NewsSource) -> FeedFetchResult`, `normalize_article(entry: RawFeedEntry) -> NormalizedArticle`.

- [ ] **Step 1: Write RSS 2.0 and Atom tests using `httpx.MockTransport`**

Use inline fixtures:

```python
RSS_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><item>
<title>  Bitcoin   ETF approved  </title>
<link>https://example.com/story?utm_source=rss&amp;id=42#top</link>
<description><![CDATA[<p>Market <b>update</b></p>]]></description>
<pubDate>Tue, 08 Sep 2026 08:00:00 GMT</pubDate>
</item></channel></rss>"""

ATOM_XML = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<title>Ethereum upgrade released</title>
<link href="https://example.com/eth-upgrade" />
<updated>2026-09-08T08:05:00Z</updated>
<summary>Protocol release</summary>
</entry></feed>"""
```

Also include one malformed entry missing title or date and assert `malformed_entries == 1` while valid entries still return.

- [ ] **Step 2: Verify RED**

```bash
pytest tests/test_news_rss_normalize.py -q
```

- [ ] **Step 3: Implement `NewsFeedClient`**

Constructor:

```python
def __init__(self, *, timeout_seconds: float = 10.0, max_response_bytes: int = 2_000_000, transport: httpx.AsyncBaseTransport | None = None) -> None:
```

Create `httpx.AsyncClient` with:

```python
headers={"User-Agent": "btc-ai-futures-news-worker/0.1 (+https://github.com/winza125-sitticun/Btc)"}
```

Rules:
- non-2xx -> `NewsFeedError`;
- `Content-Length > max_response_bytes` -> `NewsFeedError`;
- actual response body above `max_response_bytes` -> `NewsFeedError`;
- parse with `feedparser.parse(response.content)`;
- if parser is malformed and has no entries -> `NewsFeedError`;
- skip only malformed entries; do not abort the source if other entries are valid;
- use `published_parsed`, then `updated_parsed` as fallback;
- convert parser time tuples with `datetime(*value[:6], tzinfo=timezone.utc)`.

- [ ] **Step 4: Implement deterministic normalization**

```python
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def canonicalize_url(value: str) -> str:
    parts = urlsplit(value.strip())
    kept = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_QUERY_KEYS
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(kept, doseq=True), ""))
```

Strip HTML from summaries with an `HTMLParser` subclass. Reject non-HTTP(S) URLs. Normalize time to UTC.

- [ ] **Step 5: Assert exact normalized output**

```python
assert article.title == "Bitcoin ETF approved"
assert article.source_url == "https://example.com/story?id=42"
assert article.summary == "Market update"
assert article.published_at.isoformat() == "2026-09-08T08:00:00+00:00"
```

- [ ] **Step 6: Verify GREEN and commit**

```bash
pytest tests/test_news_rss_normalize.py -q
pytest -q
git add btc_core/news/rss.py btc_core/news/normalize.py tests/test_news_rss_normalize.py
git commit -m "feat: fetch and normalize rss news"
```

---

### Task 3: Core Asset Tagging and Deterministic Metadata Scoring

**Files:**
- Create: `btc_core/news/tagging.py`
- Create: `btc_core/news/scoring.py`
- Test: `tests/test_news_tagging_scoring.py`

**Interfaces:**
- Produces `tag_core_assets(article: NormalizedArticle) -> tuple[str, ...]`, `classify_impact(article, symbols) -> NewsImpactLevel`, `credibility_for(article) -> float`.

- [ ] **Step 1: Write failing tagging tests**

Required cases:

```python
assert tag_text("Bitcoin ETF decision") == ("BTCUSDT",)
assert tag_text("Ethereum and Ether upgrade") == ("ETHUSDT",)
assert tag_text("Solana network update") == ("SOLUSDT",)
assert tag_text("Ripple expands XRPL support for XRP") == ("XRPUSDT",)
assert tag_text("BTC and ETH market update") == ("BTCUSDT", "ETHUSDT")
assert tag_text("gas prices rise as one market changes") == ()
assert tag_text("solid growth outlook") == ()
```

- [ ] **Step 2: Write failing impact/credibility tests**

```python
assert classify_impact(regulator_article("SEC charges crypto exchange over Bitcoin product"), ("BTCUSDT",)) is NewsImpactLevel.HIGH
assert classify_impact(status_article("Exchange withdrawal outage continues"), ()) is NewsImpactLevel.HIGH
assert classify_impact(project_article("Ethereum protocol upgrade released"), ("ETHUSDT",)) is NewsImpactLevel.MEDIUM
assert classify_impact(media_article("Daily market commentary"), ()) is NewsImpactLevel.LOW
```

Credibility must equal `article.source.credibility_score` exactly.

- [ ] **Step 3: Verify RED**

```bash
pytest tests/test_news_tagging_scoring.py -q
```

- [ ] **Step 4: Implement conservative tagging**

```python
FULL_ALIASES = {
    "BTCUSDT": ("bitcoin",),
    "SOLUSDT": ("solana",),
    "XRPUSDT": ("xrp", "ripple", "xrpl"),
    "ETHUSDT": ("ethereum", "ether"),
}
TICKERS = {"BTCUSDT": "BTC", "SOLUSDT": "SOL", "XRPUSDT": "XRP", "ETHUSDT": "ETH"}
SYMBOL_ORDER = ("BTCUSDT", "SOLUSDT", "XRPUSDT", "ETHUSDT")
```

Full names are case-insensitive word-boundary matches. Bare tickers are case-sensitive uppercase token matches. Search title plus summary. Do not implement generic Binance ticker matching in Phase 5A.

- [ ] **Step 5: Implement impact rules**

```python
HIGH_GENERAL = {
    "etf approved", "etf approval", "etf rejected", "etf rejection",
    "exploit", "hacked", "hack", "chain halt", "network halt",
    "withdrawal halt", "withdrawals halted", "insolvency", "bankruptcy",
    "emergency rate", "emergency meeting",
}
REGULATOR_HIGH = {"charges", "charged", "enforcement", "lawsuit", "settlement"}
STATUS_HIGH = {"outage", "withdrawal", "degraded", "unavailable", "incident"}
MEDIUM_GENERAL = {"upgrade", "mainnet", "listing", "listed", "partnership", "adoption", "fomc", "rate decision"}
```

Classification order:
1. `HIGH_GENERAL` -> HIGH;
2. regulator source + at least one tagged core symbol + `REGULATOR_HIGH` -> HIGH;
3. exchange-status source + `STATUS_HIGH` -> HIGH;
4. `MEDIUM_GENERAL` -> MEDIUM;
5. otherwise LOW.

- [ ] **Step 6: Verify GREEN and commit**

```bash
pytest tests/test_news_tagging_scoring.py -q
pytest -q
git add btc_core/news/tagging.py btc_core/news/scoring.py tests/test_news_tagging_scoring.py
git commit -m "feat: tag assets and score news metadata"
```

---

### Task 4: Story Fingerprinting and Near-Duplicate Resolution

**Files:**
- Create: `btc_core/news/dedup.py`
- Test: `tests/test_news_dedup.py`

**Interfaces:**
- Produces `normalized_title_tokens(title: str, source_name: str | None = None) -> tuple[str, ...]`, `jaccard_similarity(left, right) -> float`, `resolve_content_fingerprint(article: NormalizedArticle, symbols: tuple[str, ...], recent: list[RecentNewsStory], now: datetime) -> str`.

- [ ] **Step 1: Write failing duplicate tests**

```python
def test_near_duplicate_reuses_existing_fingerprint():
    article = normalized("SEC charges crypto exchange over Bitcoin ETF product")
    recent = RecentNewsStory(
        title="Crypto exchange charged by SEC over Bitcoin ETF product",
        content_fingerprint="story-123",
        published_at=NOW - timedelta(minutes=10),
        symbols=("BTCUSDT",),
        source_class=NewsSourceClass.MEDIA,
    )
    assert resolve_content_fingerprint(article, ("BTCUSDT",), [recent], now=NOW) == "story-123"
```

Also prove:
- unrelated titles receive a different fingerprint;
- rows older than 24 hours are ignored;
- tagged stories compare only to stories sharing at least one symbol;
- untagged stories compare only to matching `source_class`;
- a new fingerprint is 64 lowercase hex characters.

- [ ] **Step 2: Verify RED**

```bash
pytest tests/test_news_dedup.py -q
```

- [ ] **Step 3: Implement title tokenization**

```python
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "in", "is", "it", "of", "on", "or", "that", "the", "to", "with",
}
```

Normalize with Unicode NFKC, lowercase, punctuation-to-space, repeated-whitespace collapse, and stopword removal. If the title ends with `" - <source name>"` or `" | <source name>"` case-insensitively, remove that suffix before tokenization. Return sorted unique tokens.

- [ ] **Step 4: Implement similarity and resolution**

```python
def jaccard_similarity(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
```

Resolver rules:
- ignore `published_at < now - timedelta(hours=24)`;
- when the new article has symbols, require at least one shared symbol;
- when it has no symbols, require the same source class;
- ignore recent rows without `content_fingerprint`;
- select highest similarity, tie-break by newest `published_at`;
- reuse fingerprint only at similarity `>= 0.82`;
- otherwise return `sha256(" ".join(tokens).encode("utf-8")).hexdigest()`.

- [ ] **Step 5: Verify GREEN and commit**

```bash
pytest tests/test_news_dedup.py -q
pytest -q
git add btc_core/news/dedup.py tests/test_news_dedup.py
git commit -m "feat: group duplicate news stories"
```

---

### Task 5: Supabase Schema and Idempotent Repository

**Files:**
- Create: `supabase/migrations/202609080006_news_intelligence_foundation.sql`
- Create: `btc_core/news/supabase_repo.py`
- Test: `tests/test_news_migration.py`
- Test: `tests/test_supabase_news_repository.py`

**Interfaces:**
- Produces `SupabaseNewsRepositoryError`, `SupabaseNewsRepository.article_exists(source_url: str) -> bool`, `.recent_stories(since: datetime) -> list[RecentNewsStory]`, `.persist_article(enriched: EnrichedNewsArticle) -> str`.

- [ ] **Step 1: Write failing migration test**

```python
MIGRATION = Path("supabase/migrations/202609080006_news_intelligence_foundation.sql")


def test_news_migration_is_minimal_and_fail_closed():
    assert MIGRATION.exists()
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "add column if not exists content_fingerprint text" in sql
    assert "news_articles_published_at_idx" in sql
    assert "news_articles_fingerprint_published_idx" in sql
    assert "news_assets_symbol_news_idx" in sql
    assert "create policy" not in sql
    assert "disable row level security" not in sql
```

- [ ] **Step 2: Write failing repository tests using `httpx.MockTransport`**

Cover:
- exact URL lookup true/false;
- recent-story mapping from `news_articles` plus nested `news_assets(symbol)`;
- article upsert uses `on_conflict=source_url`;
- asset links use `on_conflict=news_id,symbol`;
- retrying the same article remains idempotent;
- non-2xx raises `SupabaseNewsRepositoryError`.

- [ ] **Step 3: Verify RED**

```bash
pytest tests/test_news_migration.py tests/test_supabase_news_repository.py -q
```

- [ ] **Step 4: Implement migration 006 exactly**

```sql
alter table public.news_articles
  add column if not exists content_fingerprint text;

create index if not exists news_articles_published_at_idx
  on public.news_articles(published_at desc);

create index if not exists news_articles_fingerprint_published_idx
  on public.news_articles(content_fingerprint, published_at desc);

create index if not exists news_assets_symbol_news_idx
  on public.news_assets(symbol, news_id);
```

No policy or grant changes.

- [ ] **Step 5: Implement repository transport following `SupabaseMarketRepository` conventions**

Exact URL query:

```python
params={"select": "id", "source_url": f"eq.{source_url}", "limit": "1"}
```

Bounded recent query:

```python
params={
    "select": "title,content_fingerprint,published_at,raw_data,news_assets(symbol)",
    "published_at": f"gte.{since.isoformat()}",
    "order": "published_at.desc",
    "limit": "200",
}
```

If historical `raw_data.source_class` is missing or invalid, map it conservatively to `NewsSourceClass.MEDIA`.

Article upsert payload:

```python
payload = {
    "source": enriched.article.source.key,
    "source_url": enriched.article.source_url,
    "title": enriched.article.title,
    "summary": enriched.article.summary,
    "published_at": enriched.article.published_at.isoformat(),
    "sentiment": None,
    "impact_level": enriched.impact_level.value,
    "credibility_score": enriched.credibility_score,
    "content_fingerprint": enriched.content_fingerprint,
    "raw_data": {
        "source_name": enriched.article.source.name,
        "source_class": enriched.article.source.source_class.value,
        "feed_url": enriched.article.source.feed_url,
    },
}
```

POST with:

```python
params={"on_conflict": "source_url"}
headers={"Prefer": "resolution=merge-duplicates,return=representation"}
```

Then upsert `news_assets` rows with conflict target `news_id,symbol`.

- [ ] **Step 6: Verify GREEN and commit**

```bash
pytest tests/test_news_migration.py tests/test_supabase_news_repository.py -q
pytest -q
git add supabase/migrations/202609080006_news_intelligence_foundation.sql btc_core/news/supabase_repo.py tests/test_news_migration.py tests/test_supabase_news_repository.py
git commit -m "feat: persist news intelligence in supabase"
```

---

### Task 6: Poll Orchestration and Source Failure Isolation

**Files:**
- Create: `services/news_worker/__init__.py`
- Create: `services/news_worker/app/__init__.py`
- Create: `services/news_worker/app/main.py`
- Modify: `.env.example`
- Test: `tests/test_news_worker.py`

**Interfaces:**
- Produces `run_poll_cycle(...) -> NewsPollResult`, `run_forever()`, and module entry point `python -m services.news_worker.app.main`.

- [ ] **Step 1: Write failing worker tests with fake clients/repositories**

Use two enabled sources where one succeeds and one raises `NewsFeedError`:

```python
result = await run_poll_cycle(
    sources=sources,
    feed_client=feed_client,
    repo=repo,
    concurrency=2,
    now=NOW,
)
assert result.sources_succeeded == 1
assert result.sources_failed == 1
assert result.entries_parsed == 1
assert result.inserted == 1
```

Also prove:
- `article_exists=True` increments `duplicates` and skips later enrichment;
- malformed-entry counts accumulate;
- repository errors escape `run_poll_cycle` so a database outage is not reported as successful ingestion;
- persisted `EnrichedNewsArticle.sentiment is None`.

- [ ] **Step 2: Verify RED**

```bash
pytest tests/test_news_worker.py -q
```

- [ ] **Step 3: Implement processing order exactly**

```text
fetch/parse
-> normalize
-> exact duplicate lookup
-> core asset tagging
-> recent-story query
-> near-duplicate fingerprint
-> credibility + impact
-> persist
```

Fetch enabled sources concurrently under `asyncio.Semaphore(concurrency)`. One feed failure must not abort other sources. Process successful result sets in catalog order for deterministic tests/logging.

Build persistence records with:

```python
EnrichedNewsArticle(
    article=article,
    symbols=symbols,
    content_fingerprint=fingerprint,
    credibility_score=credibility_for(article),
    impact_level=classify_impact(article, symbols),
    sentiment=None,
)
```

- [ ] **Step 4: Implement environment bounds and long-running loop**

```python
poll_seconds = _env_float("NEWS_POLL_SECONDS", 120.0, minimum=30.0, maximum=3600.0)
timeout_seconds = _env_float("NEWS_HTTP_TIMEOUT_SECONDS", 10.0, minimum=2.0, maximum=60.0)
concurrency = _env_int("NEWS_FETCH_CONCURRENCY", 4, minimum=1, maximum=10)
```

Require nonempty `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` before startup. Catch and re-raise `asyncio.CancelledError`. Log other cycle failures and sleep `poll_seconds`; never tight-loop retries.

- [ ] **Step 5: Extend `.env.example`**

```dotenv
# News intelligence worker (server-side, deterministic Phase 5A)
NEWS_POLL_SECONDS=120
NEWS_HTTP_TIMEOUT_SECONDS=10
NEWS_FETCH_CONCURRENCY=4
```

No new secret variable is added because `SUPABASE_SERVICE_ROLE_KEY` already exists in `.env.example`.

- [ ] **Step 6: Verify GREEN and commit**

```bash
pytest tests/test_news_worker.py -q
pytest -q
git add services/news_worker .env.example tests/test_news_worker.py
git commit -m "feat: add resilient news worker"
```

---

### Task 7: Lock Scanner Neutrality and Run Full Regression Gates

**Files:**
- Modify: `tests/test_market_features.py`
- Do not modify: `btc_core/market/features.py`

**Interfaces:**
- Produces regression proof that the new subsystem cannot alter Phase 5A opportunity scoring.

- [ ] **Step 1: Add explicit neutrality assertions using the existing market snapshot fixture/helper**

```python
result = build_market_feature_result(snapshot)
assert result.inputs.news == 50.0
assert result.inputs.macro == 50.0
assert result.inputs.risk_reward == 50.0
```

- [ ] **Step 2: Run focused backend test**

```bash
pytest tests/test_market_features.py -q
```

- [ ] **Step 3: Run complete backend and frontend gates**

```bash
pytest -q
cd apps/web && npm install && npm run build
```

Expected: all backend tests PASS; frontend TypeScript/Vite build PASS.

- [ ] **Step 4: Review branch diff and commit**

Confirm `btc_core/market/features.py`, risk engine files, simulation execution files, and Binance authenticated execution code were not changed.

```bash
git add tests/test_market_features.py
git commit -m "test: lock neutral news scanner score"
```

---

### Task 8: PR, Migration, Railway Rollout, and Production Verification

**Files:**
- No product-code edits unless review or CI identifies a concrete defect.
- Update Library handoff/source-of-truth only after production evidence exists.

**Interfaces:**
- Produces merged green `main`, applied migration 006, a running Railway `news-worker`, and verified news rows in Supabase.

- [ ] **Step 1: Create implementation branch from current green `main`**

```text
feat/news-intelligence-foundation
```

Implement Tasks 1-7 on that branch with the commits listed above.

- [ ] **Step 2: Open PR and verify CI**

PR description must explicitly state:
- Phase 5A only;
- deterministic RSS/Atom ingestion;
- no AI calls;
- no Binance authenticated calls;
- scanner news/macro remain 50;
- `SIMULATION` and AI Direct Order OFF unchanged;
- migration 006 adds no public policies.

Required checks before merge: backend pytest green and frontend build green.

- [ ] **Step 3: Apply migration 006 to Supabase project `ypitothwjbdmbvdmftfv` after schema review**

Apply only:

```text
supabase/migrations/202609080006_news_intelligence_foundation.sql
```

Verify `content_fingerprint` and all three indexes exist. Verify no new public RLS policy exists for `news_articles` or `news_assets`.

- [ ] **Step 4: Merge only after PR CI succeeds, then verify post-merge main CI**

Record merge SHA and CI run IDs in the PR and handoff.

- [ ] **Step 5: Create Railway service `news-worker` manually**

Source: `winza125-sitticun/Btc`, branch `main`.

Start command:

```text
python -m services.news_worker.app.main
```

Configuration:
- Region: Singapore / Southeast Asia
- Replicas: 1
- Public domain: none
- Cron: none
- Healthcheck: none

Non-secret variables:

```text
APP_ENV=production
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
SUPABASE_URL=https://ypitothwjbdmbvdmftfv.supabase.co
NEWS_POLL_SECONDS=120
NEWS_HTTP_TIMEOUT_SECONDS=10
NEWS_FETCH_CONCURRENCY=4
```

Add the existing `SUPABASE_SERVICE_ROLE_KEY` as a Railway secret directly in the Railway UI. Never paste its value into chat or commit it.

Do not add `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `SUPABASE_ANON_KEY`, or any AI-provider key to this service.

- [ ] **Step 6: Verify production ingestion after completed poll cycles**

Require at least four distinct successful source keys in `news_articles`.

Exact duplicate check:

```sql
select source_url, count(*)
from public.news_articles
group by source_url
having count(*) > 1;
```

Expected: zero rows.

Core asset-tag observation:

```sql
select symbol, count(*)
from public.news_assets
where symbol in ('BTCUSDT', 'SOLUSDT', 'XRPUSDT', 'ETHUSDT')
group by symbol
order by symbol;
```

A symbol may be absent if no ingested article actually mentions it. Do not fabricate tags.

Fingerprint check:

```sql
select content_fingerprint, count(*)
from public.news_articles
where content_fingerprint is not null
group by content_fingerprint
order by count(*) desc
limit 20;
```

Every new Phase 5A article row must have a non-null fingerprint.

- [ ] **Step 7: Verify production safety invariants**

Inspect the latest scanner candidate records and confirm `news_score=50.0` and `macro_score=50.0`. Confirm Railway remains `TRADING_MODE=SIMULATION` and `DIRECT_AI_ORDER_ENABLED=false`. No authenticated Binance execution capability may be introduced.

- [ ] **Step 8: Update project handoff/source-of-truth with observed evidence**

Record:
- merge SHA;
- PR/main CI run IDs;
- migration 006 application time;
- Railway news-worker region/status;
- source keys actually ingested;
- newest article timestamp;
- exact-duplicate query result;
- observed core tags;
- scanner-neutrality verification;
- any disabled source and its concrete failure reason.

Phase 5A is complete only after these production checks are observed.
