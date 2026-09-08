# News Intelligence Foundation V1 Design

## Status
Approved in chat on 2026-09-08. This document defines Phase 5A only: deterministic news ingestion and storage. It does not enable AI news analysis and does not change trading behavior.

## Goal
Add a resilient, read-only news intelligence subsystem that continuously ingests trusted public RSS/Atom feeds, normalizes and deduplicates articles, tags affected crypto assets, assigns deterministic source credibility and impact metadata, and persists the results to Supabase for later scanner and AI enrichment.

The subsystem must remain isolated from execution and risk decisions. During this phase, the scanner continues to use `news=50.0` and `macro=50.0` neutral placeholders exactly as it does today.

## Non-goals
Phase 5A does not:
- call any AI provider;
- generate AI sentiment or AI trade recommendations;
- change scanner ranking weights;
- replace the scanner's neutral `news_score` or `macro_score`;
- add Binance authenticated API usage;
- place, cancel, modify, or simulate orders;
- implement macro event ingestion;
- add a user-facing News Dashboard;
- require a paid news provider;
- scrape arbitrary websites whose page structure may change without notice.

## Safety invariants
The following existing rules are unchanged:
- `TRADING_MODE=SIMULATION`.
- AI Direct Order remains `OFF`.
- Binance authenticated order execution is not implemented.
- Market/news ingestion is read-only with respect to external providers.
- News worker failure cannot trigger a trade or bypass the deterministic Risk Engine.
- Missing, stale, malformed, or unavailable news data does not become a bullish or bearish signal in Phase 5A.
- Scanner `news` and `macro` components remain neutral at `50.0` until a later explicitly approved integration phase.

## Approaches considered

### A. Hybrid public feeds, deterministic processing — selected
Use official RSS/Atom feeds and selected established crypto media feeds. Normalize, deduplicate, tag, and score deterministically. Keep AI and paid APIs out of the first milestone.

Advantages:
- no recurring news API cost for the foundation;
- deterministic and testable;
- no AI hallucination risk in ingestion;
- easy to replace or add sources through adapters;
- low operational complexity.

Trade-off:
- feed coverage and metadata quality vary by publisher.

### B. Paid news API first
Use a commercial crypto/news provider as the primary source.

Advantages:
- more consistent schema;
- often broader coverage and lower normalization effort.

Trade-offs:
- recurring cost;
- vendor lock-in;
- API limits and provider-specific outage risk before the pipeline itself is validated.

### C. Public feeds plus AI summarization immediately
Run each article through an AI provider during ingestion.

Advantages:
- richer summaries, sentiment, and entity extraction from day one.

Trade-offs:
- higher cost and latency;
- harder failure modes;
- malformed model output can contaminate stored enrichment;
- unnecessary coupling before deterministic ingestion is proven.

Phase 5A uses Approach A. The adapter boundary must allow Approach B or C to be added later without replacing the storage model or worker orchestration.

## Initial source set
V1 begins with a small, high-signal source set rather than a large uncontrolled catalog:

1. U.S. SEC official press-release RSS feeds.
2. U.S. CFTC official general/enforcement RSS feeds.
3. Federal Reserve official press-release and monetary-policy RSS feeds.
4. Coinbase Status official incident/history feed where RSS/Atom is available.
5. Ethereum Foundation official blog feed.
6. CoinDesk RSS feed as an established crypto-media source.

The implementation must model sources as configuration records/adapters rather than hard-code source-specific parsing into the worker loop. Sources may be disabled individually if their feed becomes unavailable or changes format.

If a listed source no longer exposes a stable public RSS/Atom endpoint during implementation, it is disabled rather than replaced with brittle page scraping. Phase 5A production validation requires successful ingestion from at least four distinct verified sources; adding a replacement source requires the same adapter and test coverage.

Solana Foundation, Ripple/XRPL, additional exchanges, security firms, and other crypto publications may be added only after their public feed/API is verified and covered by source-specific tests.

## Architecture

```text
RSS / Atom Sources
        |
        v
Source Fetchers
        |
        v
Feed Parser
        |
        v
Normalizer
  | canonical URL
  | normalized title
  | published time
        |
        v
Exact Duplicate Resolver
        |
        v
Asset Tagger
        |
        v
Near-Duplicate / Story Resolver
        |
        v
Deterministic Metadata Scorer
  | credibility
  | impact
  | sentiment = NULL in V1
        |
        v
Supabase Repository
  | news_articles
  | news_assets
        |
        v
Future Phase 5B/5C consumers
```

## Code boundaries

### `btc_core.news.models`
Defines immutable/validated Pydantic models used between stages:
- `NewsSource`;
- `RawFeedEntry`;
- `NormalizedArticle`;
- `NewsAssetTag`;
- `NewsImpactLevel`;
- persistence records/results.

The worker and persistence layer consume normalized models rather than raw XML dictionaries.

### `btc_core.news.sources`
Owns the configured source catalog. Each source contains:
- stable source key/name;
- feed URL;
- source class (`OFFICIAL_REGULATOR`, `OFFICIAL_PROJECT`, `EXCHANGE_STATUS`, `MEDIA`);
- default credibility score;
- enabled flag.

Source configuration must support environment overrides later, but V1 may ship a reviewed default catalog.

### `btc_core.news.rss`
Owns network fetch and RSS/Atom parsing.

Requirements:
- `httpx` transport with finite timeout;
- explicit User-Agent;
- bounded response size;
- RSS 2.0 and Atom parsing;
- source-specific parser quirks isolated behind the same normalized entry interface;
- malformed entries are skipped/reportable without aborting the entire source;
- one source failure cannot stop other sources in the same poll cycle.

No browser scraping is part of V1.

### `btc_core.news.normalize`
Normalizes:
- title whitespace and Unicode;
- absolute URL;
- canonical URL by removing known tracking parameters and fragments;
- publication timestamp to UTC;
- optional feed summary as plain text;
- source metadata.

The normalized canonical URL is stored in `news_articles.source_url` and continues to benefit from the existing unique constraint.

### `btc_core.news.dedup`
Provides two deterministic duplicate layers.

#### Exact duplicate
Articles with the same canonical URL are treated as the same source article. Exact duplicate resolution occurs immediately after normalization. Persistence must be idempotent across repeated polling.

#### Cross-source near duplicate
Different publishers may report the same event with different URLs. Near-duplicate resolution happens after asset tagging so recent comparison can be bounded by shared asset context. V1 assigns a deterministic `content_fingerprint` used as a story-group identifier.

Algorithm:
1. normalize title to lowercase Unicode text;
2. remove punctuation, repeated whitespace, common stopwords, and publisher suffixes;
3. tokenize the remaining title;
4. compare against recent articles within a bounded time window, prioritizing articles sharing at least one asset tag; articles with no asset tags compare only within the same source class/category context;
5. use deterministic token-set similarity (Jaccard) with a documented threshold;
6. if a recent article exceeds the threshold, reuse its `content_fingerprint`;
7. otherwise create a new SHA-256 fingerprint from the normalized title representation.

This grouping does not delete source provenance. Each distinct source URL remains a separate `news_articles` row. Several rows may share one fingerprint.

Initial limits:
- comparison window: 24 hours;
- similarity threshold: 0.82;
- maximum recent comparison candidates per incoming article: 100;
- only bounded recent records are queried so ingestion cost does not grow with total history.

### `btc_core.news.tagging`
Deterministically tags assets mentioned in title/summary.

Core aliases:
- Bitcoin, BTC -> `BTCUSDT`;
- Ethereum, Ether, ETH -> `ETHUSDT`;
- Solana, SOL -> `SOLUSDT`;
- XRP, Ripple, XRPL -> `XRPUSDT`.

For other assets, tagging may use the current Binance USDT-M symbol universe, but ticker matching must be strict. Tokens that are common English words or ambiguous symbols such as `ONE` and `GAS` must not be tagged by bare ticker text unless an unambiguous project/asset alias is also present.

A single article may map to multiple `news_assets` rows.

### `btc_core.news.scoring`
Assigns deterministic metadata only. It does not calculate scanner `news_score` in Phase 5A.

#### Credibility score
Default source-class targets:
- official regulator/government: 95;
- official project/protocol: 92;
- official exchange/status channel: 92;
- reviewed established media source: 80.

Per-source configuration may tune these values, but scores remain explicit static configuration rather than AI output.

#### Impact level
Rules are keyword/category based and deterministic.

Likely `HIGH` categories include:
- enforcement action materially affecting a major crypto company/asset;
- ETF approval/rejection or comparable major regulatory decision;
- exploit, hack, bridge/protocol compromise, chain halt;
- major exchange outage, insolvency, withdrawal halt, or market-wide disruption;
- major delisting affecting a tracked asset;
- emergency central-bank decision with broad market implications.

Likely `MEDIUM` categories include:
- major protocol upgrade/release;
- significant listing;
- institutional adoption/partnership with clear asset relevance;
- scheduled policy communication without an emergency condition.

General commentary and low-specificity updates default to `LOW`.

The rules must be conservative: uncertain classification falls to the lower impact level rather than being promoted.

#### Sentiment
`news_articles.sentiment` remains `NULL` in V1. Phase 5A does not infer bullish/bearish sentiment from keyword heuristics.

### `btc_core.news.supabase_repo`
Owns all news persistence.

Responsibilities:
- idempotent article insert/upsert behavior;
- preserve source provenance;
- write asset tags transactionally or with safe retry semantics;
- query bounded recent articles for fingerprint matching;
- never expose service-role credentials outside server-side worker configuration.

### `services.news_worker.app.main`
Long-running Railway worker.

Responsibilities:
1. load source catalog and environment configuration;
2. poll enabled feeds concurrently with a safe concurrency limit;
3. isolate source failures;
4. normalize, exact-deduplicate, tag, story-resolve, score, and persist accepted articles;
5. log per-cycle counts: sources successful/failed, entries parsed, inserted, exact duplicates, grouped near-duplicates, malformed entries;
6. sleep until the next poll cycle.

Default polling interval: 120 seconds.

The worker has no public HTTP domain requirement.

## Database changes
The existing tables are retained:
- `public.news_articles`;
- `public.news_assets`.

Migration `006` adds only fields/indexes required by the foundation:

```text
news_articles.content_fingerprint text
index news_articles(published_at desc)
index news_articles(content_fingerprint, published_at desc)
index news_assets(symbol, news_id)
```

`content_fingerprint` is intentionally non-unique because multiple source articles may represent one story. The migration may leave the column nullable for compatibility with pre-existing rows, but all new Phase 5A worker inserts must populate it.

The existing `news_articles.source_url UNIQUE` constraint remains the exact-idempotency boundary.

No public RLS policy is added to the internal news tables in this phase. They remain server-worker-managed/fail-closed until a later API/dashboard design explicitly defines safe read access.

## Environment configuration
Railway `news-worker` requires only server-side runtime configuration:

```text
APP_ENV=production
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
SUPABASE_URL=https://ypitothwjbdmbvdmftfv.supabase.co
SUPABASE_SERVICE_ROLE_KEY=(configured directly in Railway; never committed or pasted into chat)
NEWS_POLL_SECONDS=120
NEWS_HTTP_TIMEOUT_SECONDS=10
NEWS_FETCH_CONCURRENCY=4
```

No Binance API key, Binance secret, AI provider key, or withdrawal credential is required.

The Railway service should run in Singapore to remain close to the existing Supabase project and market worker. Because Railway Config-as-Code is deprecated for newly created services, use the manually configured Start Command:

```text
python -m services.news_worker.app.main
```

## Failure handling

### Individual source unavailable
Record/log the failure and continue all other sources. The worker waits for the normal next polling cycle instead of entering a tight retry loop.

### Malformed feed or entry
Reject only the malformed source entry where possible. If the feed itself cannot be parsed, mark that source failed for the cycle.

### Supabase unavailable
Do not claim successful ingestion. Log the repository failure and retry on the next cycle. No trading behavior changes because news is not connected to scanner scoring in this phase.

### Stale news
Articles keep their original `published_at`. Later consumers must reason from age; Phase 5A only stores accurate timestamps.

### Duplicate polling
Repeated feed entries must not create duplicate source rows because canonical `source_url` is unique and persistence is idempotent.

## Data flow example
A CFTC enforcement RSS item mentioning a crypto exchange and Bitcoin is fetched. The parser emits a raw entry. Normalization removes tracking parameters and converts publication time to UTC. Exact deduplication checks the canonical URL. The tagger finds `Bitcoin` and emits `BTCUSDT`. Story resolution compares the title with bounded recent BTC-tagged articles. The source class gives the article regulator-level credibility. Enforcement keywords may make impact `HIGH`. The repository inserts one `news_articles` row plus a `news_assets` row for `BTCUSDT`. A later CoinDesk story about the same enforcement action keeps its own URL/source row but may share the same `content_fingerprint` if the deterministic similarity threshold is met.

None of those records changes the active scanner score in Phase 5A.

## Testing strategy
CI uses mocked feeds and mocked Supabase transport/repository behavior; it does not depend on live internet access.

Required tests:
1. parse representative RSS 2.0 feeds;
2. parse representative Atom feeds;
3. normalize URLs and strip tracking parameters without changing meaningful query parameters;
4. normalize publication timestamps to UTC;
5. exact duplicate polling is idempotent;
6. deterministic cross-source fingerprint matching within the 24-hour window;
7. unrelated stories do not share fingerprints;
8. BTC/SOL/XRP/ETH alias tagging;
9. ambiguous ticker false-positive protection;
10. multi-asset tagging;
11. credibility mapping by source class;
12. conservative impact classification;
13. one failed source does not abort successful sources;
14. malformed entries are isolated;
15. repository persists article and asset links correctly;
16. migration `006` contains required indexes and does not add unsafe public policies;
17. regression test proves scanner still builds `news=50.0` and `macro=50.0` after the subsystem is added;
18. all existing backend tests and frontend build remain green.

## Development workflow
Implementation follows the project workflow:

```text
Design -> Plan -> Feature Branch -> Tests First -> Implementation
-> Regression Tests -> GitHub PR -> GitHub Actions -> Review -> Merge main
```

No production code is committed directly to `main`.

## Production verification
Phase 5A is complete only when all of the following are verified after merge:
- `news-worker` is active on Railway;
- at least four distinct verified configured sources have produced stored articles;
- repeated polling does not duplicate identical source URLs;
- `content_fingerprint` groups controlled/tested near-duplicate cases correctly;
- BTC/SOL/XRP/ETH tagging is observable in `news_assets` when relevant articles exist, with fixtures proving all four aliases even if live feeds do not mention every asset during the deployment window;
- one intentionally unavailable/mocked failure path is proven isolated in tests;
- timestamps and source provenance are preserved;
- scanner production behavior remains market-only with neutral `news=50.0` and `macro=50.0`;
- trading mode remains SIMULATION and no authenticated Binance execution capability is introduced.

## Follow-on phases

### Phase 5B — News API and Dashboard
Add safe read APIs and a PWA News view for recent articles, asset filters, source/impact metadata, worker freshness, and story grouping.

### Phase 5C — Deterministic News Score integration
Design and validate a bounded, time-decayed News Score that can replace the scanner's neutral news placeholder. This requires a separate approval because it changes opportunity scoring behavior.

### Later AI enrichment
Only after deterministic ingestion is stable, the AI Provider Gateway may consume selected news context for summaries/sentiment. AI output remains structured, validated, and subordinate to deterministic risk controls.
