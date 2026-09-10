# News Worker Production Rollout Evidence

Date: 2026-09-09 (UTC/GMT+7 evidence captured in the Render dashboard)

## Repository and CI

- PR #9 (news intelligence foundation) merged to `main` at `b7af1fbd2456232df1bc0444081b1f543532b508`.
- CI run #51 passed for backend and web.
- Supabase migration `20260908114010 news_intelligence_foundation` is applied.
- Verified indexes: `news_articles_published_at_idx`, `news_articles_fingerprint_published_idx`, and `news_assets_symbol_news_idx`.
- Public policy count for `news_articles` and `news_assets`: 0.
- Compatibility PR #10 (`build: prepare news worker for Koyeb`) merged to the deployed `main` commit `db4c5ed3a4973a866826f8273f3e71d98fa5cfdc`. Its contract files are `requirements.txt`, `.python-version`, and `.koyebignore`; no worker, feed catalog, schema, scanner, or trading logic was changed.

## Render deployment

The user selected Render instead of Koyeb for this worker.

- Service: `news-worker` (Background Worker)
- Service ID: `srv-dagggu740ujc73f3ulhg`
- Repository/branch: `winza125-sitticun/Btc` / `main`
- Region: Singapore
- Instance: `0.5c-512mb` (one instance)
- Start command: `python -m services.news_worker.app.main`
- Ports/domain: none
- Autodeploy: enabled
- Deployed source: `db4c5ed3a4973a866826f8273f3e71d98fa5cfdc`
- First successful ingestion deploy: `dep-dagim9ad0e5s73clp9sg`, T0 `2026-09-09T09:47:17Z`.
- Log-only redeploy: `dep-dagir6ijnfac73dqrolg`, deployed `2026-09-09T09:57:46Z`, status `Deploy succeeded | Live`.
- `PYTHONUNBUFFERED=1` was added as a log-only environment setting so cycle completion evidence is emitted immediately. It does not alter worker or trading behavior.
- No resize was required. No feed was disabled.

Configured safety/runtime variables were verified in Render: `APP_ENV=production`, `TRADING_MODE=SIMULATION`, `DIRECT_AI_ORDER_ENABLED=false`, the approved Supabase URL, `NEWS_POLL_SECONDS=120`, `NEWS_HTTP_TIMEOUT_SECONDS=10`, and `NEWS_FETCH_CONCURRENCY=4`. The Supabase server-side key is stored only in Render Environment and is not recorded here. No Binance, AI-provider, withdrawal, or live-trading credentials are configured.

## Runtime evidence

Two consecutive cycles completed on the same Render instance (`wg6dm`) without restart:

```text
2026-09-09 16:58:23 GMT+7  news cycle complete sources_ok=6 sources_failed=2 parsed=105 inserted=0 duplicates=105 malformed=0
2026-09-09 17:00:29 GMT+7  news cycle complete sources_ok=6 sources_failed=2 parsed=105 inserted=0 duplicates=105 malformed=0
```

`ethereum_blog` and `coindesk` each returned a redirect (301/308) and failed the approved feed parser. They remain enabled because this is not confirmation of structural unavailability; the other six feeds succeeded.

## Supabase acceptance results

Queries used `T0 = 2026-09-09T09:47:17Z`.

### New sources and timestamps

100 articles were ingested after T0 from six configured source keys:

| source | articles | newest ingested (UTC) | newest published (UTC) |
| --- | ---: | --- | --- |
| `cftc_enforcement` | 10 | 2026-09-09 09:47:52.919618+00 | 2026-09-01 18:45:49+00 |
| `cftc_general` | 10 | 2026-09-09 09:47:51.369346+00 | 2026-09-02 17:27:34+00 |
| `coinbase_status` | 25 | 2026-09-09 09:48:01.481865+00 | 2026-09-10 18:30:00+00 |
| `fed_monetary` | 10 | 2026-09-09 09:47:57.354467+00 | 2026-07-08 18:00:00+00 |
| `fed_press` | 20 | 2026-09-09 09:47:55.793080+00 | 2026-09-04 15:00:00+00 |
| `sec_press` | 25 | 2026-09-09 09:47:49.880097+00 | 2026-09-03 20:30:00+00 |

### Safety invariants

- Exact duplicate query: 0 rows.
- Fingerprints: `new_articles = 100`, `missing_fingerprints = 0`.
- Observed asset tags: `ETHUSDT = 5`, `SOLUSDT = 1`; `BTCUSDT` and `XRPUSDT` were absent in this batch and were not fabricated.
- Latest scanner run: `candidate_count = 10`, `non_neutral_count = 0`.
- Public policies on `news_articles` and `news_assets`: `public_policy_count = 0`.

The worker remains read-only toward providers and runs in simulation mode. Production data was not modified or deleted during verification.
