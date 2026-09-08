# News Intelligence Foundation V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resilient, deterministic, read-only RSS/Atom news worker that stores normalized, deduplicated, asset-tagged news in Supabase without changing scanner scoring or trading behavior.

**Architecture:** Add a focused `btc_core.news` package for source configuration, feed transport/parsing, normalization, asset tagging, story grouping, deterministic metadata scoring, and Supabase persistence. Add a separate long-running `services.news_worker` Railway service that polls enabled sources every 120 seconds, isolates feed failures, and leaves the scanner's `news=50.0` and `macro=50.0` placeholders untouched.

**Tech Stack:** Python 3.12+, Pydantic 2, httpx async transport, feedparser 6, Supabase PostgREST, pytest, pytest-asyncio, Railway.

**Spec:** `docs/superpowers/specs/2026-09-08-news-intelligence-foundation-design.md`

## Global Constraints

- `TRADING_MODE=SIMULATION`.
- AI Direct Order remains `OFF`.
- Binance authenticated order execution is not implemented.
- News ingestion is read-only with respect to external providers.
- No AI provider is called in Phase 5A.
- Scanner `news` and `macro` components remain exactly `50.0` throughout Phase 5A.
- Scanner weights do not change.
- No public RLS policy is added to `news_articles` or `news_assets` in this phase.
- `news_articles.source_url UNIQUE` remains the exact-idempotency boundary.
- Near-duplicate comparison window is 24 hours.
- Near-duplicate Jaccard threshold is `0.82`.
- Default news polling interval is 120 seconds.
- Production validation requires successful ingestion from at least four distinct verified sources.
- If a configured source no longer exposes stable RSS/Atom, disable it; do not replace it with page scraping.
- `news-worker` runs server-side and receives `SUPABASE_SERVICE_ROLE_KEY` only through Railway variables.
- Do not add Binance API keys, AI keys, withdrawal credentials, or authenticated exchange actions to the news worker.

## File Structure

Create these focused modules:

- `btc_core/news/__init__.py` — package boundary only.
- `btc_core/news/models.py` — validated source, feed-entry, normalized article, story, enrichment, and poll-result models.
- `btc_core/news/sources.py` — reviewed V1 source catalog only.
- `btc_core/news/rss.py` — HTTP fetch, response-size guard, RSS/Atom parse, malformed-entry isolation.
- `btc_core/news/normalize.py` — title/summary/URL/timestamp normalization.
- `btc_core/news/tagging.py` — conservative BTC/SOL/XRP/ETH tagging and ambiguity protection.
- `btc_core/news/dedup.py` — title tokens, Jaccard matching, SHA-256 story fingerprint.
- `btc_core/news/scoring.py` — static credibility and deterministic LOW/MEDIUM/HIGH impact rules.
- `btc_core/news/supabase_repo.py` — PostgREST exact lookup, recent-story read, idempotent article/asset upsert.
- `services/news_worker/__init__.py` and `services/news_worker/app/__init__.py` — service package boundaries.
- `services/news_worker/app/main.py` — poll orchestration and long-running entry point.
- `supabase/migrations/202609080006_news_intelligence_foundation.sql` — only required news fields/indexes.

Modify:

- `pyproject.toml` — add `feedparser>=6.0.11,<7`.
- `.env.example` — add news-worker configuration without secrets.
- `tests/test_market_features.py` — explicit regression that news/macro remain neutral.

Create tests:

- `tests/test_news_models_sources.py`
- `tests/test_news_rss_normalize.py`
- `tests/test_news_tagging_scoring.py`
- `tests/test_news_dedup.py`
- `tests/test_supabase_news_repository.py`
- `tests/test_news_migration.py`
- `tests/test_news_worker.py`

---

### Task 1: Domain Models, Source Catalog, and Parser Dependency

**Files:**
- Modify: `pyproject.toml`
- Create: `btc_core/news/__init__.py`
- Create: `btc_core/news/models.py`
- Create: `btc_core/news/sources.py`
- Test: `tests/test_news_models_sources.py`

**Interfaces:**
- Consumes: Pydantic conventions already used throughout `btc_core`.
- Produces: `NewsSourceClass`, `NewsImpactLevel`, `NewsSource`, `RawFeedEntry`, `NormalizedArticle`, `RecentNewsStory`, `EnrichedNewsArticle`, `FeedFetchResult`, `NewsPollResult`, and `DEFAULT_NEWS_SOURCES`.

- [ ] **Step 1: Write failing model/source tests**

```python
from btc_core.news.models import NewsSourceClass
from btc_core.news.sources import DEFAULT_NEWS_SOURCES


def test_default_source_catalog_has_verified_classes_and_unique_keys():
    keys = [source.key for source in DEFAULT_NEWS_SOURCES]
    assert len(keys) == len(set(keys))
    assert len(DEFAULT_NEWS_SOURCES) >= 8
    assert any(s.source_class is NewsSourceClass.OFFICIAL_REGULATOR for s in DEFAULT_NEWS_SOURCES)
    assert any(s.source_class is NewsSourceClass.EXCHANGE_STATUS for s in DEFAULT_NEWS_SOURCES)
    assert any(s.source_class is NewsSourceClass.MEDIA for s in DEFAULT_NEWS_SOURCES)
    assert all(s.enabled for s in DEFAULT_NEWS_SOURCES)
    assert all(0 <= s.credibility_score <= 100 for s in DEFAULT_NEWS_SOURCES)
```

Also assert these exact stable source keys exist: `sec_press`, `cftc_general`, `cftc_enforcement`, `fed_press`, `fed_monetary`, `coinbase_status`, `ethereum_blog`, `coindesk`.

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
pytest tests/test_news_models_sources.py -q
```

Expected: FAIL because `btc_core.news` does not exist.

- [ ] **Step 3: Add parser dependency and minimal validated models**

Add to `pyproject.toml` dependencies:

```toml
"feedparser>=6.0.11,<7",
```

Implement enums and frozen Pydantic models with these exact fields:

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

- [ ] **Step 4: Add the reviewed V1 catalog**

Use these exact feed endpoints:

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

No worker code may special-case these source keys.

- [ ] **Step 5: Run focused tests and the existing suite**

Run:

```bash
pytest tests/test_news_models_sources.py -q
pytest -q
```

Expected: new test PASS; all prior tests remain PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml btc_core/news tests/test_news_models_sources.py
git commit -m "feat: define news domain models and sources"
```

---

### Task 2: RSS/Atom Fetching and Normalization

**Files:**
- Create: `btc_core/news/rss.py`
- Create: `btc_core/news/normalize.py`
- Test: `tests/test_news_rss_normalize.py`

**Interfaces:**
- Consumes: `NewsSource`, `RawFeedEntry`, `NormalizedArticle` from Task 1.
- Produces: `NewsFeedError`, `NewsFeedClient.fetch(source) -> FeedFetchResult`, `normalize_article(entry) -> NormalizedArticle`.

- [ ] **Step 1: Write failing RSS and Atom parser tests**

Use inline XML fixtures, never the live internet:

```python
RSS_XML = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Example</title><item>
<title>  Bitcoin   ETF approved  </title>
<link>https://example.com/story?utm_source=rss&amp;id=42#top</link>
<description><![CDATA[<p>Market <b>update</b></p>]]></description>
<pubDate>Tue, 08 Sep 2026 08:00:00 GMT</pubDate>
</item></channel></rss>"""

ATOM_XML = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Example</title><entry>
<title>Ethereum upgrade released</title>
<link href="https://example.com/eth-upgrade" />
<updated>2026-09-08T08:05:00Z</updated>
<summary>Protocol release</summary>
</entry></feed>"""
```

Test `httpx.MockTransport` returns each body and assert one normalized raw entry is produced. Add a second RSS item missing title/date and assert it increments `malformed_entries` instead of aborting the source.

- [ ] **Step 2: Verify RED**

```bash
pytest tests/test_news_rss_normalize.py -q
```

Expected: FAIL because `NewsFeedClient` and `normalize_article` do not exist.

- [ ] **Step 3: Implement bounded async feed fetch**

`NewsFeedClient` constructor:

```python
def __init__(
    self,
    *,
    timeout_seconds: float = 10.0,
    max_response_bytes: int = 2_000_000,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
```

Create an `httpx.AsyncClient` with:

```python
headers={"User-Agent": "btc-ai-futures-news-worker/0.1 (+https://github.com/winza125-sitticun/Btc)"}
```

On each response:
- reject non-2xx;
- reject `Content-Length` over `2_000_000` when supplied;
- reject `len(response.content)` over `2_000_000`;
- parse bytes with `feedparser.parse`;
- if parsing is malformed and no entries exist, raise `NewsFeedError`;
- skip only entries without title, link, or a usable `published_parsed`/`updated_parsed` timestamp.

Convert feedparser time tuples using:

```python
datetime(*time_tuple[:6], tzinfo=timezone.utc)
```

- [ ] **Step 4: Implement deterministic normalization**

Required helpers:

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

Strip HTML from feed summaries with a tiny `HTMLParser` subclass and normalize the resulting whitespace. Preserve meaningful query parameters such as `id=42`.

`normalize_article` must force `published_at` to timezone-aware UTC and reject non-http/https canonical URLs.

- [ ] **Step 5: Add normalization assertions**

Assert the RSS fixture becomes:

```python
assert article.title == "Bitcoin ETF approved"
assert article.source_url == "https://example.com/story?id=42"
assert article.summary == "Market update"
assert article.published_at.isoformat() == "2026-09-08T08:00:00+00:00"
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_news_rss_normalize.py -q
pytest -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add btc_core/news/rss.py btc_core/news/normalize.py tests/test_news_rss_normalize.py
git commit -m "feat: fetch and normalize rss news"
```

---

### Task 3: Conservative Asset Tagging and Deterministic Metadata Scoring

**Files:**
- Create: `btc_core/news/tagging.py`
- Create: `btc_core/news/scoring.py`
- Test: `tests/test_news_tagging_scoring.py`

**Interfaces:**
- Consumes: `NormalizedArticle`, `NewsSourceClass`, `NewsImpactLevel`.
- Produces: `tag_core_assets(article) -> tuple[str, ...]`, `classify_impact(article, symbols) -> NewsImpactLevel`, `credibility_for(article) -> float`.

- [ ] **Step 1: Write failing core tagging tests**

```python
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Bitcoin ETF decision", ("BTCUSDT",)),
        ("Ethereum and Ether upgrade", ("ETHUSDT",)),
        ("Solana network update", ("SOLUSDT",)),
        ("Ripple expands XRPL support for XRP", ("XRPUSDT",)),
        ("BTC and ETH market update", ("BTCUSDT", "ETHUSDT")),
    ],
)
def test_core_asset_tagging(text, expected):
    assert tag_text(text) == expected
```

Add false-positive tests:

```python
assert tag_text("gas prices rise as one market changes") == ()
assert tag_text("solid growth outlook") == ()
```

- [ ] **Step 2: Write failing scoring tests**

Required expectations:

```python
assert classify_impact(regulator_article("SEC charges crypto exchange over Bitcoin product"), ("BTCUSDT",)) is NewsImpactLevel.HIGH
assert classify_impact(status_article("Exchange withdrawal outage continues"), ()) is NewsImpactLevel.HIGH
assert classify_impact(project_article("Ethereum protocol upgrade released"), ("ETHUSDT",)) is NewsImpactLevel.MEDIUM
assert classify_impact(media_article("Daily market commentary"), ()) is NewsImpactLevel.LOW
```

Assert credibility returns the static score from `article.source.credibility_score`; no text heuristic may modify credibility.

- [ ] **Step 3: Verify RED**

```bash
pytest tests/test_news_tagging_scoring.py -q
```

- [ ] **Step 4: Implement core tagger**

Use case-insensitive full-name aliases and case-sensitive bare tickers:

```python
FULL_ALIASES = {
    "BTCUSDT": ("bitcoin",),
    "ETHUSDT": ("ethereum", "ether"),
    "SOLUSDT": ("solana",),
    "XRPUSDT": ("xrp", "ripple", "xrpl"),
}
TICKERS = {
    "BTCUSDT": "BTC",
    "ETHUSDT": "ETH",
    "SOLUSDT": "SOL",
    "XRPUSDT": "XRP",
}
```

Search title plus summary. Full aliases use word-boundary matching with `re.IGNORECASE`. Bare tickers require the original text to contain an uppercase token boundary. Return symbols sorted in this fixed order: `BTCUSDT`, `SOLUSDT`, `XRPUSDT`, `ETHUSDT`.

Do not attempt generic Binance ticker tagging in Phase 5A; the function boundary must stay small enough to extend safely later.

- [ ] **Step 5: Implement conservative impact rules**

Use explicit normalized phrase sets. HIGH signals:

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

Rules:
1. any `HIGH_GENERAL` phrase -> HIGH;
2. regulator source + at least one core symbol + `REGULATOR_HIGH` phrase -> HIGH;
3. exchange-status source + `STATUS_HIGH` phrase -> HIGH;
4. any `MEDIUM_GENERAL` phrase -> MEDIUM;
5. otherwise LOW.

Uncertain items fall downward, never upward.

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_news_tagging_scoring.py -q
pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add btc_core/news/tagging.py btc_core/news/scoring.py tests/test_news_tagging_scoring.py
git commit -m "feat: tag assets and score news metadata"
```

---

### Task 4: Exact and Near-Duplicate Story Resolution

**Files:**
- Create: `btc_core/news/dedup.py`
- Test: `tests/test_news_dedup.py`

**Interfaces:**
- Consumes: `NormalizedArticle`, `RecentNewsStory`, tagged symbol tuples.
- Produces: `normalized_title_tokens(title) -> tuple[str, ...]`, `jaccard_similarity(left, right) -> float`, `resolve_content_fingerprint(article, symbols, recent) -> str`.

- [ ] **Step 1: Write failing title/fingerprint tests**

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

Add tests proving:
- unrelated stories do not reuse a fingerprint;
- recent stories older than 24 hours are ignored;
- tagged articles only compare to recent stories sharing at least one symbol;
- untagged articles compare only to the same `source_class`;
- result for a new story is a 64-character lowercase SHA-256 hex string.

- [ ] **Step 2: Verify RED**

```bash
pytest tests/test_news_dedup.py -q
```

- [ ] **Step 3: Implement deterministic title tokenization**

Use Unicode NFKC + lowercase, replace punctuation with spaces, and remove this fixed stopword set:

```python
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "in", "is", "it", "of", "on", "or", "that", "the", "to", "with",
}
```

Remove publisher suffixes only when they appear after `" - "` or `" | "` and the suffix case-insensitively contains the current source name. Keep the remaining nonempty tokens in sorted unique order so fingerprint creation is deterministic.

- [ ] **Step 4: Implement Jaccard and story resolution**

```python
def jaccard_similarity(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
```

`resolve_content_fingerprint` must:
- ignore rows older than `now - timedelta(hours=24)`;
- require shared symbols when the new article has symbols;
- when the new article has no symbols, require matching `source_class`;
- only consider recent rows with a nonempty `content_fingerprint`;
- choose the candidate with highest similarity, breaking ties by newest `published_at`;
- reuse only when similarity `>= 0.82`;
- otherwise return `sha256(" ".join(tokens).encode("utf-8")).hexdigest()`.

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_news_dedup.py -q
pytest -q
```

- [ ] **Step 6: Commit**

```bash
git add btc_core/news/dedup.py tests/test_news_dedup.py
git commit -m "feat: group duplicate news stories"
```

---

### Task 5: Supabase Migration and Idempotent News Repository

**Files:**
- Create: `supabase/migrations/202609080006_news_intelligence_foundation.sql`
- Create: `btc_core/news/supabase_repo.py`
- Test: `tests/test_news_migration.py`
- Test: `tests/test_supabase_news_repository.py`

**Interfaces:**
- Consumes: `EnrichedNewsArticle`, `RecentNewsStory`.
- Produces: `SupabaseNewsRepositoryError`, `SupabaseNewsRepository.article_exists(url)`, `.recent_stories(...)`, `.persist_article(article) -> str`.

- [ ] **Step 1: Write failing migration test**

```python
MIGRATION = Path("supabase/migrations/202609080006_news_intelligence_foundation.sql")


def test_news_migration_is_minimal_and_fail_closed():
    assert MIGRATION.exists(), "news intelligence migration must exist"
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "add column if not exists content_fingerprint text" in sql
    assert "news_articles_published_at_idx" in sql
    assert "news_articles_fingerprint_published_idx" in sql
    assert "news_assets_symbol_news_idx" in sql
    assert "create policy" not in sql
    assert "alter table public.news_articles disable row level security" not in sql
    assert "alter table public.news_assets disable row level security" not in sql
```

- [ ] **Step 2: Write failing repository tests with `httpx.MockTransport`**

Cover:
- `article_exists` returns true for one row and false for empty list;
- `recent_stories` maps nested `news_assets` symbols and `raw_data.source_class` into `RecentNewsStory`;
- `persist_article` POSTs article with `on_conflict=source_url`, `Prefer: resolution=merge-duplicates,return=representation`;
- returned article id is used to upsert `news_assets` with `on_conflict=news_id,symbol`;
- retrying the same article does not require a new row id;
- HTTP error raises `SupabaseNewsRepositoryError`.

- [ ] **Step 3: Verify RED**

```bash
pytest tests/test_news_migration.py tests/test_supabase_news_repository.py -q
```

- [ ] **Step 4: Implement migration 006**

Use exactly:

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

Do not add policies or grants.

- [ ] **Step 5: Implement repository transport**

Follow `btc_core.market.supabase_repo.SupabaseMarketRepository` conventions: async context manager, finite `httpx.Timeout`, `apikey` + Bearer server key headers, centralized `_request`, response body capped in error strings.

`article_exists` query:

```python
params={"select": "id", "source_url": f"eq.{source_url}", "limit": "1"}
```

`recent_stories` query must be bounded:

```python
params={
    "select": "title,content_fingerprint,published_at,raw_data,news_assets(symbol)",
    "published_at": f"gte.{since.isoformat()}",
    "order": "published_at.desc",
    "limit": "200",
}
```

Map unknown/missing `raw_data.source_class` conservatively to `MEDIA` for historical rows.

`persist_article` article payload:

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

After the article upsert returns `id`, upsert each asset link with conflict target `news_id,symbol`. If symbols are empty, stop after the article upsert.

- [ ] **Step 6: Run focused and full tests**

```bash
pytest tests/test_news_migration.py tests/test_supabase_news_repository.py -q
pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add supabase/migrations/202609080006_news_intelligence_foundation.sql btc_core/news/supabase_repo.py tests/test_news_migration.py tests/test_supabase_news_repository.py
git commit -m "feat: persist news intelligence in supabase"
```

---

### Task 6: News Worker Poll Orchestration and Failure Isolation

**Files:**
- Create: `services/news_worker/__init__.py`
- Create: `services/news_worker/app/__init__.py`
- Create: `services/news_worker/app/main.py`
- Modify: `.env.example`
- Test: `tests/test_news_worker.py`

**Interfaces:**
- Consumes: all `btc_core.news` modules from Tasks 1-5.
- Produces: `run_poll_cycle(...) -> NewsPollResult`, `run_forever()`, CLI/module entry point `python -m services.news_worker.app.main`.

- [ ] **Step 1: Write failing orchestration test**

Build fake feed client and repository objects. Use two enabled sources: one returns one valid article and one raises `NewsFeedError`.

Assert:

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
assert result.inserted == 1
assert result.entries_parsed == 1
```

Add tests that:
- an exact duplicate reported by `repo.article_exists()` increments `duplicates` and skips tagging/scoring/persist;
- malformed entry counts from successful feed results are accumulated;
- repository failure escapes `run_poll_cycle` rather than being reported as a successful source;
- `sentiment` passed to persistence remains `None`.

- [ ] **Step 2: Verify RED**

```bash
pytest tests/test_news_worker.py -q
```

- [ ] **Step 3: Implement `run_poll_cycle`**

Processing order for each normalized entry must be exact:

```text
normalize
-> exact duplicate lookup
-> asset tag
-> bounded recent-story query
-> near-duplicate fingerprint
-> credibility + impact
-> persist
```

Use `asyncio.Semaphore(concurrency)` around source fetches. Fetch all sources concurrently, but process each successful source's entries deterministically in source-catalog order so tests/logging are stable.

Create `EnrichedNewsArticle` with:

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

- [ ] **Step 4: Implement environment parsing and long-running loop**

Use bounded env helpers equivalent to market worker style:

```python
poll_seconds = _env_float("NEWS_POLL_SECONDS", 120.0, minimum=30.0, maximum=3600.0)
timeout_seconds = _env_float("NEWS_HTTP_TIMEOUT_SECONDS", 10.0, minimum=2.0, maximum=60.0)
concurrency = _env_int("NEWS_FETCH_CONCURRENCY", 4, minimum=1, maximum=10)
```

Require both `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`; otherwise raise `RuntimeError` before polling.

Each cycle log one compact line with succeeded/failed/parsed/inserted/duplicates/malformed counts. Catch `asyncio.CancelledError` and re-raise. Catch other exceptions at the outer loop, log `news worker cycle failed: ...`, then sleep the normal poll interval. Do not enter a tight retry loop.

- [ ] **Step 5: Extend `.env.example`**

Append:

```dotenv
# News intelligence worker (server-side, deterministic Phase 5A)
NEWS_POLL_SECONDS=120
NEWS_HTTP_TIMEOUT_SECONDS=10
NEWS_FETCH_CONCURRENCY=4
```

Do not add any new secret variable.

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_news_worker.py -q
pytest -q
```

- [ ] **Step 7: Commit**

```bash
git add services/news_worker .env.example tests/test_news_worker.py
git commit -m "feat: add resilient news worker"
```

---

### Task 7: Lock Scanner Neutrality and Full Regression Gate

**Files:**
- Modify: `tests/test_market_features.py`
- No production scanner file should change in this task.

**Interfaces:**
- Consumes: existing `build_market_feature_result`.
- Produces: regression proof that Phase 5A cannot affect opportunity scoring.

- [ ] **Step 1: Add explicit neutrality regression**

Use the existing market snapshot fixture/helper in `tests/test_market_features.py`, then assert:

```python
result = build_market_feature_result(snapshot)
assert result.inputs.news == 50.0
assert result.inputs.macro == 50.0
assert result.inputs.risk_reward == 50.0
```

Also assert `btc_core/market/features.py` is not modified by the implementation branch when reviewing the PR diff.

- [ ] **Step 2: Run the focused test**

```bash
pytest tests/test_market_features.py -q
```

Expected: PASS without any production scanner edit.

- [ ] **Step 3: Run complete backend and frontend gates**

```bash
pytest -q
cd apps/web && npm install && npm run build
```

Expected: all backend tests PASS; frontend TypeScript/Vite build PASS.

- [ ] **Step 4: Commit regression test**

```bash
git add tests/test_market_features.py
git commit -m "test: lock neutral news scanner score"
```

---

### Task 8: Feature PR, Migration Application, and Production News Worker Rollout

**Files:**
- No new product code unless CI/review identifies a defect.
- Update the project handoff/source-of-truth Library files only after production evidence is collected.

**Interfaces:**
- Consumes: completed implementation branch from Tasks 1-7.
- Produces: merged green `main`, applied migration 006, Railway `news-worker`, and verified stored news records.

- [ ] **Step 1: Open the feature PR**

Use a feature branch named:

```text
feat/news-intelligence-foundation
```

PR description must state:
- Phase 5A only;
- deterministic RSS/Atom ingestion;
- scanner news/macro remain 50;
- no AI calls;
- no Binance authenticated calls;
- `SIMULATION` unchanged;
- migration 006 adds no public policies.

- [ ] **Step 2: Verify GitHub Actions before merge**

Required checks:
- backend pytest green;
- frontend npm build green.

If either fails, do not merge. Diagnose the failing test/build first.

- [ ] **Step 3: Apply migration 006 to Supabase**

Apply exactly `supabase/migrations/202609080006_news_intelligence_foundation.sql` to project `ypitothwjbdmbvdmftfv` only after PR code/schema review is complete. Verify these columns/indexes exist and verify no new public RLS policy was created for `news_articles` or `news_assets`.

- [ ] **Step 4: Merge and verify post-merge main CI**

Merge only when PR CI is green. Record the merge SHA and the successful post-merge CI run number in the PR/handoff.

- [ ] **Step 5: Create Railway service manually because Config-as-Code is deprecated for new services**

Service name:

```text
news-worker
```

Source:

```text
winza125-sitticun/Btc
branch: main
```

Start Command:

```text
python -m services.news_worker.app.main
```

Region: Singapore / Southeast Asia, one replica, no public domain, no cron, no healthcheck.

Variables:

```text
APP_ENV=production
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
SUPABASE_URL=https://ypitothwjbdmbvdmftfv.supabase.co
SUPABASE_SERVICE_ROLE_KEY=(set directly in Railway secret UI; never paste into chat)
NEWS_POLL_SECONDS=120
NEWS_HTTP_TIMEOUT_SECONDS=10
NEWS_FETCH_CONCURRENCY=4
```

Do not add `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `SUPABASE_ANON_KEY`, or any AI provider key to this service.

- [ ] **Step 6: Verify production ingestion in Supabase**

After at least one completed poll cycle, query counts grouped by `source`, newest `published_at`, and `created_at`. Acceptance requires articles from at least four distinct verified source keys.

Verify exact idempotency by checking:

```sql
select source_url, count(*)
from public.news_articles
group by source_url
having count(*) > 1;
```

Expected: zero rows.

Verify tags:

```sql
select symbol, count(*)
from public.news_assets
where symbol in ('BTCUSDT', 'SOLUSDT', 'XRPUSDT', 'ETHUSDT')
group by symbol
order by symbol;
```

Absence of a symbol is acceptable when no ingested article actually mentions it; never fabricate tags to satisfy validation.

Verify fingerprints:

```sql
select content_fingerprint, count(*)
from public.news_articles
where content_fingerprint is not null
group by content_fingerprint
order by count(*) desc
limit 20;
```

Every newly inserted Phase 5A row must have a non-null fingerprint.

- [ ] **Step 7: Verify production safety invariants**

Query the latest scanner candidate rows and confirm `news_score=50.0` and `macro_score=50.0`. Confirm Railway services still have `TRADING_MODE=SIMULATION` and `DIRECT_AI_ORDER_ENABLED=false`. Do not enable any order-execution capability.

- [ ] **Step 8: Update handoff/source of truth with evidence**

Record:
- merge SHA;
- CI run IDs;
- migration 006 application timestamp;
- Railway news-worker status/region;
- source keys successfully ingested;
- duplicate query result;
- newest article timestamp;
- observed core asset tags;
- scanner neutrality verification;
- any disabled feed and the concrete reason.

Do not claim Phase 5A complete until these checks are observed from production.
