# AI Futures Trader V1 Foundation Design

## Scope
This milestone establishes the production-shaped foundation for a cloud-only crypto futures trading system. It does not place real orders. The default trading mode is simulation.

## Architecture
- Web/PWA: React + Vite + TypeScript, deployed to Cloudflare Workers Static Assets.
- API and long-running workers: Python 3.12+; FastAPI for HTTP; deployed to Railway.
- Database/Auth/Realtime/Storage: Supabase PostgreSQL.
- AI: provider adapters for Gemini, Claude, OpenAI-compatible APIs, DeepSeek, and OpenRouter. No local model is required.
- Exchange: Binance Futures adapters are introduced in the next milestone; this milestone defines contracts and risk/simulation primitives only.

## Safety invariants
1. Trading mode defaults to SIMULATION.
2. AI decisions cannot bypass deterministic risk checks.
3. API keys and exchange secrets are never returned to the browser.
4. Direct AI order execution is disabled by default.
5. Risk engine rejects signals below confidence, opportunity score, or risk/reward thresholds.
6. High-impact event blocking is represented as an explicit risk input.

## Core contracts
### AI
Provider enum: GEMINI, CLAUDE, OPENAI_COMPATIBLE, DEEPSEEK, OPENROUTER.
AI decision enum: LONG, SHORT, WAIT, EXIT.
AI output uses structured fields: direction, confidence, entry range, stop loss, take profits, risk/reward, and reason summary.

### Scanner
Opportunity score is deterministic and normalized to 0-100. V1 weights: technical 20%, momentum 10%, volume 8%, order flow 15%, open interest 10%, funding 5%, liquidity 10%, news 10%, macro 5%, risk/reward 7%.

### Risk
Risk policy defaults: min confidence 75, min opportunity score 75, min RR 2.0, max leverage 5, max risk/trade 1%, max daily loss 3%, max open positions 3. Event guard blocks new entries.

### Simulation
Simulation positions track side, entry, quantity, leverage, stop loss, take profits, fee/slippage/funding costs and realized/unrealized PnL. V1 supports deterministic mark-to-market calculations; order matching arrives in a later milestone.

## Database foundation
Initial migration creates profiles, AI provider configs, scanner runs/candidates, AI decisions, risk decisions, simulation accounts/positions, market candles, derivatives metrics, news articles/assets, and macro events. Row-level security is enabled for user-owned configuration and simulation tables.

## UI foundation
Dashboard displays trading mode, balance, PnL, scanner candidates, and provider status using mocked data until API integration is connected. Settings exposes provider/model/role configuration fields with secret values represented only as configured/not configured.

## Verification
- Python unit tests cover scanner scoring, AI structured validation, risk rejection/approval, simulation PnL, and API health.
- CI runs pytest.
- Frontend build is verified when npm dependencies can be installed in CI.
