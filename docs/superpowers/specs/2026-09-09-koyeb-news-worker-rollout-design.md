# Koyeb News Intelligence Worker Production Rollout Design

## Status

Approved in chat on 2026-09-09. This rollout packages the already-merged Phase 5A news worker for Koyeb and verifies production ingestion. It does not alter worker behavior, trading behavior, scanner scoring, or the Supabase schema.

## Deployment contract

Koyeb's Python buildpack detects Python projects through a root `requirements.txt`, `poetry.lock`, or `Pipfile.lock`. The repository keeps `pyproject.toml` as the dependency source of truth and adds a one-line `requirements.txt` containing `.` so Koyeb installs the project and its declared dependencies. `.python-version` pins the runtime to Python 3.12.14. `.koyebignore` suppresses redeployments for documentation-only changes.

## Koyeb service

- App: `btc-ai-futures-trader`
- Service: `news-worker`
- Source: `winza125-sitticun/Btc`, branch `main`, repository root
- Builder: buildpack
- Type: Worker
- Region: Singapore (`SIN`)
- Scale: one static `eco-nano` instance
- Start command: `python -m services.news_worker.app.main`
- No public ports or domain
- Autodeploy enabled

Only the approved production environment variables are configured. `SUPABASE_SERVICE_ROLE_KEY` is a Koyeb secret and is never stored in the repository or exposed in chat.

## Verification

After deployment, require two consecutive successful poll cycles and verify source counts, duplicate URLs, non-null fingerprints, observed core asset tags, scanner neutrality, zero public news-table policies, and the exact Koyeb safety configuration. Any structurally unavailable feed requires a separate tested disable-source PR; transient failures remain enabled.

## Safety invariants

`TRADING_MODE=SIMULATION`, `DIRECT_AI_ORDER_ENABLED=false`, neutral scanner `news_score` and `macro_score` values of `50.0`, no AI calls, no authenticated Binance execution, no withdrawals, and read-only external ingestion remain unchanged.
