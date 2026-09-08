# BTC — AI Futures Trader

Cloud-first AI-assisted crypto futures opportunity scanner and simulation platform.

## Safety status

- Default mode: **SIMULATION**
- Live order execution: **not implemented in this milestone**
- AI direct order: **disabled**
- Deterministic Risk Engine: **mandatory**
- Local AI/GPU: **not required**

## V1 architecture

- `apps/web` — React/Vite PWA for mobile/web operator UI
- `services/api` — FastAPI HTTP service for dashboard/settings APIs
- `btc_core/ai` — structured AI provider/decision contracts
- `btc_core/scanner` — deterministic opportunity scoring
- `btc_core/market` — Binance USD-M public market adapter, feature builder, and scanner
- `services/market_worker` — continuous scanner + realtime Binance WebSocket ingestion worker
- `btc_core/risk` — non-AI risk approval gate
- `btc_core/simulation` — paper position accounting
- `supabase/migrations` — PostgreSQL schema and RLS
- Railway — backend API/workers deployment target
- Cloudflare Workers Static Assets — web deployment target

## Current milestone

Implemented foundation contracts for:

1. AI provider selection: Gemini, Claude, OpenAI-compatible, DeepSeek, OpenRouter
2. LONG/SHORT/WAIT/EXIT structured AI decisions
3. Opportunity scoring for technical, momentum, volume, order flow, OI, funding, liquidity, news, macro and RR
4. Deterministic Risk Gate
5. Simulation PnL model
6. FastAPI health/public config
7. Supabase foundation schema
8. Mobile-first PWA dashboard/settings shell
9. GitHub Actions CI
10. Binance USD-M read-only market client (public endpoints only)
11. Real-market snapshot assembly from candles, funding, OI, long/short ratio and bid/ask spread
12. Market-only Opportunity Scanner with top-volume universe selection and bounded concurrency
13. Binance USDⓈ-M realtime WebSocket ingestion using the 2026 `/market` and `/public` split endpoints
14. Supabase persistence for scanner runs, ranked candidates, live market state and closed candles
15. FastAPI scanner/live-market read APIs
16. Dashboard/Scanner UI polling real backend data instead of mock candidates

The market scanner intentionally keeps News, Macro and Risk/Reward components neutral until the Intelligence and strategy-enrichment milestones. Live orders remain out of scope until simulation and testnet gates are validated.

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

Apply the migrations in `supabase/migrations/` in filename order to a Supabase project. User-owned tables use RLS. Secrets must be stored server-side; do not persist plaintext API keys in browser storage or ordinary public tables.

## Deployment

- Backend: Railway using `railway.toml`
- Frontend: build `apps/web` then deploy static assets with `wrangler.jsonc`


## Run one market scan

The scanner uses Binance public USD-M endpoints and does not require an API key.

```bash
SCANNER_TIMEFRAME=15m SCANNER_UNIVERSE_LIMIT=10 SCANNER_CANDIDATE_LIMIT=5 \
  python -m services.market_worker.app.main
```

For the first deployment keep the universe small (10–30 symbols) while validating Railway rate limits and runtime behavior.

## Run continuous realtime market worker

Apply migration `202609080003_realtime_scanner.sql`, then configure server-side variables:

```bash
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<server-only-key>
SCANNER_TIMEFRAME=15m
SCANNER_INTERVAL_SECONDS=300
SCANNER_UNIVERSE_LIMIT=30
SCANNER_CANDIDATE_LIMIT=10
REALTIME_SYMBOL_LIMIT=10
REALTIME_FLUSH_SECONDS=3
```

Start with:

```bash
python -m services.market_worker.app.main
```

The worker rescans the highest-volume USDⓈ-M perpetuals, stores the ranking, then tracks the top candidates through Binance realtime streams. Book ticker data uses Binance `/public`; mark price and kline data use `/market`, matching the 2026 WebSocket migration.

For Railway, create a separate service for the worker and point its config to `railway.market-worker.toml`. The API service continues to use `railway.toml`. Set `VITE_API_BASE_URL` on the web build to the Railway API origin.
