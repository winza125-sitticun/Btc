# BTC — AI Futures Trader

Cloud-first AI-assisted crypto futures opportunity scanner and simulation platform.

## Safety status

- Default mode: **SIMULATION**
- Live order execution: **not implemented in this milestone**
- AI direct order: **disabled**
- AI Analysis V1: **disabled by default** until production canary is explicitly enabled
- Deterministic Risk Engine: **mandatory**
- Local AI/GPU: **not required**

AI output is analysis only. A successful AI response is **not** trade authorization. V1 persists a deterministic precheck status and uses `FULL_RISK_CONTEXT_PENDING` when full portfolio/account risk context is not available. No provider may place an order directly in this milestone.

## V1 architecture

- `apps/web` — React/Vite PWA for mobile/web operator UI
- `services/api` — FastAPI read API for scanner, realtime state, public config and sanitized AI analysis
- `btc_core/ai` — AI snapshot, provider adapters, structured decision validation, orchestration and deterministic precheck
- `btc_core/scanner` — deterministic opportunity scoring
- `btc_core/market` — Binance USD-M public market adapter, feature builder and scanner
- `btc_core/news` — recent-news scoring/context used by scanner enrichment and AI snapshots
- `services/market_worker` — continuous scanner + realtime Binance WebSocket ingestion + inline AI analysis worker
- `btc_core/risk` — non-AI risk approval gate
- `btc_core/simulation` — paper position accounting
- `supabase/migrations` — PostgreSQL schema and RLS
- Railway — backend API/workers deployment target
- Cloudflare Workers Static Assets — web deployment target

## Current milestone

Implemented contracts and runtime paths for:

1. AI provider selection: Gemini, Claude, OpenAI-compatible, DeepSeek and OpenRouter
2. LONG/SHORT/WAIT/EXIT structured AI decisions
3. Opportunity scoring for technical, momentum, volume, order flow, OI, funding, liquidity, news, macro and RR
4. Deterministic Risk Gate
5. Simulation PnL model
6. FastAPI health/public config
7. Supabase foundation schema and RLS
8. Mobile-first PWA dashboard/settings shell
9. GitHub Actions CI
10. Binance USD-M read-only market client using public endpoints only
11. Real-market snapshot assembly from candles, funding, OI, long/short ratio and bid/ask spread
12. Opportunity Scanner with top-volume universe selection and bounded concurrency
13. Binance USDⓈ-M realtime WebSocket ingestion using the 2026 `/market` and `/public` split endpoints
14. Supabase persistence for scanner runs, ranked candidates, live market state and closed candles
15. FastAPI scanner/live-market read APIs
16. Dashboard/Scanner UI polling real backend data instead of mock candidates
17. News Enrichment V1 with deterministic bounded recent-news contribution and fail-open behavior
18. AI Analysis V1 inline execution alongside realtime ingestion, limited to selected top candidates with bounded concurrency and retry/timeout policy
19. Multi-timeframe AI snapshot context for `4h`, `1h` and `15m` using bounded summaries instead of raw candle arrays
20. Strict structured-output validation for provider responses before persistence
21. AI decision persistence linked to live `market_scanner_candidates` records
22. Sanitized `GET /api/v1/ai/latest` read path using the Supabase anon key
23. Read-only AI Settings state and AI analysis cards in the web app

Live orders remain out of scope until simulation and testnet gates are validated.

## AI Analysis V1 data flow

```text
Binance market scanner
  -> persist scanner run/candidates
  -> start inline AI analysis task
       -> select eligible top candidates
       -> build bounded 4h + 1h + 15m market snapshot
       -> attach recent sanitized news context
       -> call configured AI provider
       -> validate response against AIDecision schema
       -> run deterministic precheck
       -> persist sanitized AI analysis
  -> realtime market ingestion continues independently
```

The AI task starts only after scanner candidates have been persisted so each analysis is linked to the actual `market_scanner_candidates` row. AI provider failures are fail-open for market ingestion: they do not invalidate the scanner run or stop realtime state updates.

## AI providers

Supported provider values:

- `GEMINI`
- `CLAUDE`
- `OPENAI_COMPATIBLE`
- `DEEPSEEK`
- `OPENROUTER`

The worker uses server-side configuration only. Browser code never receives the provider API key. OpenAI-compatible mode requires an explicit base URL; standard provider adapters use their configured/default API endpoints.

## Server-side AI variables

AI Analysis V1 is off unless explicitly enabled:

```bash
AI_ANALYSIS_V1_ENABLED=false
AI_PROVIDER=
AI_MODEL=
AI_API_KEY=
AI_BASE_URL=
AI_TIMEOUT_SECONDS=20
AI_MAX_RETRIES=1
AI_ANALYSIS_CANDIDATE_LIMIT=3
AI_ANALYSIS_CONCURRENCY=2
AI_MIN_OPPORTUNITY_SCORE=65
```

Keep `AI_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY` and any other secret only in the server deployment environment. Do not place real secret values in `.env.example`, GitHub commits, browser state or public Supabase tables.

Recommended first production canary settings keep the existing safety state:

```bash
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
AI_ANALYSIS_V1_ENABLED=true
AI_ANALYSIS_CANDIDATE_LIMIT=3
AI_ANALYSIS_CONCURRENCY=2
```

Enabling AI analysis does **not** enable order execution.

## AI read API

The public read service exposes sanitized fields only:

```text
GET /api/v1/ai/latest?timeframe=15m&limit=10
GET /api/v1/config/public
```

`/api/v1/config/public` reports provider/model and whether an API key is configured, but never returns the key itself. The API read dependency uses `SUPABASE_ANON_KEY`; it does not fall back to the service-role key.

The web Scanner view can display AI direction, confidence, Entry, SL, TP, R:R, provider/model, reason summary and deterministic precheck status. `FULL_RISK_CONTEXT_PENDING` is displayed as pending/not trade-authorized, never as an approval badge.

## Run backend tests

```bash
python -m pip install -e '.[dev]'
pytest -q
```

## Run API

```bash
uvicorn services.api.app.main:app --reload
```

Open `http://127.0.0.1:8000/health`.

## Run web

```bash
cd apps/web
npm install
npm run dev
```

## Database

Apply the migrations in `supabase/migrations/` in filename order to a Supabase project. AI Analysis V1 requires:

```text
supabase/migrations/202609100001_market_ai_analysis_v1.sql
```

The migration links AI analysis records to the live `market_scanner_candidates` table and exposes read access under RLS for the sanitized analysis path. Secrets must remain server-side; do not persist plaintext API keys in browser storage or ordinary public tables.

## Deployment

- Backend: Railway using `railway.toml`
- Market worker: Railway using `Dockerfile.market-worker` / market-worker service configuration
- Frontend: build `apps/web` then deploy static assets with `wrangler.jsonc`

## Run one market scan

The scanner uses Binance public USD-M endpoints and does not require a Binance API key.

```bash
SCANNER_TIMEFRAME=15m SCANNER_UNIVERSE_LIMIT=10 SCANNER_CANDIDATE_LIMIT=5 \
  python -m services.market_worker.app.main
```

For the first deployment keep the universe small (10–30 symbols) while validating Railway rate limits and runtime behavior.

## Run continuous realtime market worker

Configure server-side variables:

```bash
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<server-only-key>
SCANNER_TIMEFRAME=15m
SCANNER_INTERVAL_SECONDS=300
SCANNER_UNIVERSE_LIMIT=30
SCANNER_CANDIDATE_LIMIT=10
REALTIME_SYMBOL_LIMIT=10
REALTIME_FLUSH_SECONDS=3
NEWS_ENRICHMENT_V1_ENABLED=true
AI_ANALYSIS_V1_ENABLED=false
```

Start with:

```bash
python -m services.market_worker.app.main
```

The worker rescans the highest-volume USDⓈ-M perpetuals, stores the ranking, then tracks selected candidates through Binance realtime streams. Book ticker data uses Binance `/public`; mark price and kline data use `/market`, matching the 2026 WebSocket migration.

For Railway, keep the API and market worker as separate services. Set `VITE_API_BASE_URL` on the web build to the Railway API origin. Apply and verify the AI migration before enabling `AI_ANALYSIS_V1_ENABLED=true`.
