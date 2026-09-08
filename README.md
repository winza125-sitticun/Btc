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

The next engineering milestone is Binance Futures market ingestion and scanner data adapters. Live orders remain out of scope until simulation and testnet gates are validated.

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

Apply `supabase/migrations/202609080001_v1_foundation.sql` to a Supabase project. User-owned tables use RLS. Secrets must be stored server-side; do not persist plaintext API keys in browser storage or ordinary public tables.

## Deployment

- Backend: Railway using `railway.toml`
- Frontend: build `apps/web` then deploy static assets with `wrangler.jsonc`
