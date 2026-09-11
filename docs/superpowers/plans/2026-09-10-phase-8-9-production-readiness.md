# Phase 8–9 Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the working production AI Analysis V1 canary into a complete Phase 8 outcome-learning/paper-trading/alert system and Phase 9 live-readiness/dry-run pipeline while preserving SIMULATION-only safety.

**Architecture:** Keep `market-worker` focused on scanner/realtime/AI ingestion. Add a separate `strategy-worker` that consumes persisted analyses and market data to evaluate outcomes, run deterministic paper trades, aggregate metrics, generate material alerts, compute readiness, and create DRY_RUN order intents. API/Web remain read-only for these operational records. No private exchange order submission is introduced.

**Tech Stack:** Python 3.12, asyncio, httpx, Pydantic 2, FastAPI, PostgreSQL/Supabase PostgREST + RLS, React 19 + TypeScript + Vite, pytest/pytest-asyncio, Railway, Cloudflare static assets.

**Spec:** `docs/superpowers/specs/2026-09-10-phase-8-9-production-readiness-design.md`

## Global Constraints

- Production `TRADING_MODE=SIMULATION` throughout this milestone.
- `DIRECT_AI_ORDER_ENABLED=false` throughout this milestone.
- Add `LIVE_ORDER_EXECUTION_ENABLED=false`; Phase 8–9 contains no live submission call.
- AI output never controls leverage, position sizing, risk thresholds, or exchange submission.
- Existing `RiskPolicy` thresholds remain authoritative: confidence >= 75, opportunity score >= 75, risk/reward >= 2.0, leverage <= 5x, risk/trade <= 1%, daily loss < 3%, open positions < 3, high-impact event guard blocks entries.
- Missing account/risk/event/data context fails closed for simulation eligibility and dry-run intent generation.
- Learning measures outcomes and manages experiments only; it never edits prompts, Railway variables, thresholds, provider settings, or production code automatically.
- New rules/variants must remain simulation-only until an explicit later promotion decision.
- Scanner persistence/realtime ingestion must remain isolated from strategy-worker failures.
- Secrets remain server-side and are never returned by API, stored in analytics payloads, or bundled into frontend assets.
- New tables use RLS; service role writes; public/API reads are sanitized.
- Use TDD. Every task starts with a failing test, then minimal implementation, then focused tests, then full backend/web CI before merge.
- Do not lower readiness thresholds merely to obtain `PAPER_READY` or `LIVE_READY`.
- `LIVE_READY` never means live order submission is enabled.

---

# Wave 1 — Phase 7 Validation + Phase 8 Schema Foundation

### Task 1: Production Health Metrics and Canary Validation

**Files:**
- Create: `btc_core/strategy/health.py`
- Create: `tests/test_strategy_health.py`
- Modify: `btc_core/ai/supabase_repo.py`
- Modify: `services/api/app/main.py`
- Modify: `tests/test_api_market.py`

**Interfaces:**
- Consumes: sanitized rows from `market_ai_analyses` and recent `market_scanner_runs`.
- Produces: `ProviderHealthSnapshot`, `compute_provider_health(...)`, repository method `operational_health(...)`, and read-only endpoint `GET /api/v1/performance/health`.

- [ ] **Step 1: Write failing pure health tests**

Create `tests/test_strategy_health.py` with fixtures covering 20 attempts and assert:

```python
from btc_core.strategy.health import compute_provider_health


def test_provider_health_passes_canary_gate():
    result = compute_provider_health(
        attempts=20,
        successes=19,
        invalid_responses=0,
        latencies_ms=[2200] * 19,
        scanner_failures=0,
        scanner_cycles=20,
    )
    assert result.success_rate == 95.0
    assert result.invalid_response_rate == 0.0
    assert result.p95_latency_ms == 2200
    assert result.can_expand is True
    assert result.status == "HEALTHY"


def test_provider_health_degrades_below_90_percent_success():
    result = compute_provider_health(
        attempts=20,
        successes=17,
        invalid_responses=0,
        latencies_ms=[2000] * 17,
        scanner_failures=0,
        scanner_cycles=20,
    )
    assert result.status == "DEGRADED"
    assert result.can_expand is False
```

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_strategy_health.py -q`
Expected: import failure because `btc_core.strategy.health` does not exist.

- [ ] **Step 3: Implement pure health contract**

Create `btc_core/strategy/__init__.py` and `btc_core/strategy/health.py` with immutable Pydantic/dataclass result fields:

```python
attempts: int
successes: int
failures: int
success_rate: float
invalid_response_rate: float
median_latency_ms: int | None
p95_latency_ms: int | None
scanner_failure_rate: float
status: Literal["INSUFFICIENT_SAMPLE", "HEALTHY", "DEGRADED"]
can_expand: bool
reasons: tuple[str, ...]
```

Rules:
- minimum sample for expansion = 20 attempts;
- `can_expand` requires success >=95%, invalid <=2%, p95 <=10000 ms, scanner failure rate = 0;
- `DEGRADED` when rolling 20-attempt success <90% or p95 >20000 ms;
- insufficient sample never expands.

- [ ] **Step 4: Add repository aggregation and sanitized API**

Add a bounded repository method that reads only `status,error_code,latency_ms,provider,model,timeframe,created_at` plus recent scanner failure counts. Do not select `input_snapshot` or secret-bearing fields.

Add `GET /api/v1/performance/health` with query parameters `timeframe` default `15m` and `window` fixed/bounded to latest 20–200 attempts.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_strategy_health.py tests/test_ai_supabase_repo.py tests/test_api_market.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add btc_core/strategy tests/test_strategy_health.py btc_core/ai/supabase_repo.py services/api/app/main.py tests/test_ai_supabase_repo.py tests/test_api_market.py
git commit -m "feat: add provider health and canary validation"
```

### Task 2: Phase 8–9 Database Schema and RLS

**Files:**
- Create: `supabase/migrations/202609100002_phase_8_9_readiness.sql`
- Create: `tests/test_phase_8_9_migration.py`

**Interfaces:**
- Produces system-owned tables required by all later strategy-worker tasks.

- [ ] **Step 1: Write migration contract tests first**

The test must read the migration SQL as text and assert presence of all tables, RLS enablement, idempotency constraints, indexes, and `exchange_submission_allowed boolean not null default false`.

Required tables:
- `market_ai_signal_outcomes`
- `market_simulation_accounts`
- `market_simulation_trades`
- `market_strategy_metrics`
- `market_strategy_experiments`
- `market_alert_events`
- `market_readiness_checks`
- `market_order_intents`

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_phase_8_9_migration.py -q`
Expected: migration file missing.

- [ ] **Step 3: Implement migration**

Use the exact data model and enum/check values from the approved spec. Add:
- unique `(ai_analysis_id, horizon)` on outcomes;
- unique originating analysis on simulation trade creation;
- unique `dedupe_key` for active/material alerts where practical;
- unique idempotency/client intent key on dry-run order intents;
- indexes for due outcome evaluation, pending/open trades, recent alerts, latest readiness, strategy metric windows;
- RLS enabled on every table;
- anon/auth read policies only for sanitized operational tables needed by API;
- no API keys, tokens, secrets, raw provider bodies, or authorization headers in schema.

Seed or safely upsert one system paper account named `Production Canary` with starting balance 1000 USDT.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_phase_8_9_migration.py tests/test_ai_migration.py tests/test_news_migration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/migrations/202609100002_phase_8_9_readiness.sql tests/test_phase_8_9_migration.py
git commit -m "feat: add Phase 8-9 strategy data schema"
```

**Wave 1 verification gate:** Run `pytest -q` and `cd apps/web && npm install && npm run build`. Do not proceed if either fails.

---

# Wave 2 — Outcome Evaluation + Deterministic Paper Trading

### Task 3: Signal Outcome Evaluator

**Files:**
- Create: `btc_core/strategy/outcomes.py`
- Create: `btc_core/strategy/repository.py`
- Create: `tests/test_signal_outcomes.py`
- Create: `tests/test_strategy_repository.py`

**Interfaces:**
- Consumes: one `SUCCESS` AI analysis and bounded candle path.
- Produces: `SignalOutcome`, `evaluate_signal_outcome(...)`, repository due/read/write methods.

- [ ] **Step 1: Write RED tests for LONG/SHORT/WAIT/no-fill and conservative ambiguity**

Test cases must cover:
- LONG entry touched, TP1 reached;
- SHORT entry touched, SL reached;
- no entry touch => `NO_FILL`;
- WAIT calibration => no simulated position, but outcome row permitted;
- same candle touches SL and TP => stop-first result;
- missing candle path => `data_quality=MISSING`, never fabricated WIN/LOSS;
- MFE/MAE sign and percentage calculations.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_signal_outcomes.py -q`

- [ ] **Step 3: Implement pure evaluator**

Use immutable models. Inputs must include direction, entry range, stop, TP list, signal timestamp, horizon, and OHLC path. Compute `entry_touched`, `stop_touched`, `highest_tp_hit`, MFE, MAE, final return, outcome, and data quality. Do not fetch network data inside the pure evaluator.

- [ ] **Step 4: Implement bounded repository methods**

Methods should support:
- discovering analyses missing 1H/4H/24H outcome rows;
- inserting/upserting idempotent outcomes;
- querying persisted candles for exact symbol/window;
- bounded fallback callback for public Binance klines when coverage is missing.

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_signal_outcomes.py tests/test_strategy_repository.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add btc_core/strategy/outcomes.py btc_core/strategy/repository.py tests/test_signal_outcomes.py tests/test_strategy_repository.py
git commit -m "feat: evaluate AI signal outcomes"
```

### Task 4: Full Risk Context and Position Sizing

**Files:**
- Create: `btc_core/strategy/risk.py`
- Create: `tests/test_full_risk_context.py`
- Modify: `btc_core/risk/engine.py` only if a reusable helper is required; do not change existing threshold defaults.

**Interfaces:**
- Produces: `FullRiskContext`, `PositionSize`, `evaluate_full_risk(...)`, `size_position(...)`.

- [ ] **Step 1: Write RED tests**

Cover:
- confidence/opportunity/RR hard rejects;
- risk target default 0.5% balance;
- hard risk cap 1%;
- leverage cap 5x;
- daily realized loss >=3% reject;
- open positions >=3 reject;
- event blocked reject;
- missing event context reject for readiness-sensitive evaluation;
- zero/invalid stop distance reject;
- quantity capped by balance × allowed leverage.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_full_risk_context.py tests/test_risk_engine.py -q`

- [ ] **Step 3: Implement deterministic sizing/risk**

Formula baseline:

```python
risk_amount = balance * min(target_risk_percent, policy.max_risk_percent) / 100
stop_distance = abs(entry_price - stop_loss)
raw_quantity = risk_amount / stop_distance
max_notional = balance * policy.max_leverage
quantity = min(raw_quantity, max_notional / entry_price)
```

Reject non-positive balance/equity/entry/stop distance. AI must not supply quantity, leverage, or risk percent.

- [ ] **Step 4: Run focused tests and commit**

Run: `pytest tests/test_full_risk_context.py tests/test_risk_engine.py -q`

```bash
git add btc_core/strategy/risk.py tests/test_full_risk_context.py btc_core/risk/engine.py
git commit -m "feat: add full simulation risk and sizing"
```

### Task 5: Paper Trade Matching and Accounting

**Files:**
- Create: `btc_core/strategy/simulation.py`
- Create: `tests/test_strategy_simulation.py`
- Modify: `btc_core/strategy/repository.py`

**Interfaces:**
- Produces: deterministic pending-entry/open/close transitions and account reconciliation.

- [ ] **Step 1: Write RED tests**

Cover:
- eligible analysis creates one pending trade only;
- entry must be touched within 60 minutes for 15m signal;
- expiry if not touched; no chasing;
- default taker fee = 5 bps per fill;
- default slippage = 2 bps per fill;
- TP ladder equal thirds across available TPs;
- SL closes all remaining quantity;
- same-candle TP/SL ambiguity chooses SL;
- funding applied when observation is available;
- missing funding marks partial quality;
- realized PnL reconciles balance/equity/drawdown;
- restart/replay does not duplicate fills or trades.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_strategy_simulation.py -q`

- [ ] **Step 3: Implement pure trade state transitions**

Keep pricing/matching logic separate from repository I/O. Persist explicit events/state changes transactionally where possible; use idempotency keys for replay safety.

- [ ] **Step 4: Implement repository persistence and reconciliation**

Add methods for pending/open trades, fill/close updates, and account update with optimistic/idempotent behavior. Never use user-owned simulation rows for the system strategy worker.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_strategy_simulation.py tests/test_strategy_repository.py tests/test_simulation.py -q`

```bash
git add btc_core/strategy/simulation.py btc_core/strategy/repository.py tests/test_strategy_simulation.py tests/test_strategy_repository.py
git commit -m "feat: add deterministic paper trade engine"
```

### Task 6: Strategy Worker Skeleton and Outcome/Simulation Cycle

**Files:**
- Create: `services/strategy_worker/__init__.py`
- Create: `services/strategy_worker/app/__init__.py`
- Create: `services/strategy_worker/app/main.py`
- Create: `Dockerfile.strategy-worker`
- Create: `railway.strategy-worker.toml`
- Create: `tests/test_strategy_worker.py`
- Create: `tests/test_strategy_worker_dockerfile.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes strategy repository + public Binance market client.
- Produces independent 60-second strategy cycle.

- [ ] **Step 1: Write RED worker tests**

Assert cycle order initially supports:
1. finalize due outcomes;
2. expire stale entries;
3. evaluate new analyses for simulation;
4. update/open/close trades;
5. reconcile account.

Assert failure in one stage is recorded/isolated and cannot invoke/stop `market-worker`.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_strategy_worker.py tests/test_strategy_worker_dockerfile.py -q`

- [ ] **Step 3: Implement worker with flags default OFF**

Add environment defaults:

```text
STRATEGY_WORKER_ENABLED=false
OUTCOME_EVALUATION_ENABLED=false
SIMULATION_ENGINE_ENABLED=false
STRATEGY_CYCLE_SECONDS=60
SIM_TARGET_RISK_PERCENT=0.5
SIM_TAKER_FEE_BPS=5
SIM_SLIPPAGE_BPS=2
SIM_ENTRY_VALIDITY_MINUTES_15M=60
LIVE_ORDER_EXECUTION_ENABLED=false
```

If `STRATEGY_WORKER_ENABLED=false`, process may health-log and sleep/exit according to service design, but must not write strategy state.

- [ ] **Step 4: Run focused tests and full Wave 2 verification**

Run: `pytest tests/test_signal_outcomes.py tests/test_full_risk_context.py tests/test_strategy_simulation.py tests/test_strategy_worker.py -q`
Then: `pytest -q`

- [ ] **Step 5: Commit**

```bash
git add services/strategy_worker Dockerfile.strategy-worker railway.strategy-worker.toml .env.example tests/test_strategy_worker.py tests/test_strategy_worker_dockerfile.py
git commit -m "feat: add isolated strategy worker"
```

---

# Wave 3 — Learning Metrics + Material Alerts

### Task 7: Strategy Metrics and Experiment Registry

**Files:**
- Create: `btc_core/strategy/metrics.py`
- Create: `btc_core/strategy/experiments.py`
- Create: `tests/test_strategy_metrics.py`
- Create: `tests/test_strategy_experiments.py`
- Modify: `btc_core/strategy/repository.py`

**Interfaces:**
- Produces rolling 24H/7D/30D/ALL aggregates and simulation-only experiment lifecycle.

- [ ] **Step 1: Write RED metric tests**

Cover sample count, win rate, expectancy, profit factor, max drawdown, median return, average MFE/MAE, TP hit rates, SL rate, no-fill rate, provider success/latency and exclusion of PARTIAL/MISSING rows from full-quality performance aggregates.

- [ ] **Step 2: Write RED experiment lifecycle tests**

Allowed lifecycle:
`DRAFT -> SIMULATION -> PROMOTABLE|REJECTED -> ARCHIVED`.
Reject any method that mutates production env/config. Experiment `variant_configuration` is persisted data only.

- [ ] **Step 3: Implement pure metrics + experiment state machine**

No AI call is required to compute metrics. No automatic Railway/GitHub write is allowed from learning code.

- [ ] **Step 4: Add repository upsert/read methods and run tests**

Run: `pytest tests/test_strategy_metrics.py tests/test_strategy_experiments.py tests/test_strategy_repository.py -q`

- [ ] **Step 5: Commit**

```bash
git add btc_core/strategy/metrics.py btc_core/strategy/experiments.py btc_core/strategy/repository.py tests/test_strategy_metrics.py tests/test_strategy_experiments.py
git commit -m "feat: add strategy learning metrics"
```

### Task 8: Material Alert Engine and Delivery Adapters

**Files:**
- Create: `btc_core/strategy/alerts.py`
- Create: `btc_core/strategy/alert_delivery.py`
- Create: `tests/test_strategy_alerts.py`
- Create: `tests/test_alert_delivery.py`
- Modify: `btc_core/strategy/repository.py`
- Modify: `services/strategy_worker/app/main.py`
- Modify: `.env.example`

**Interfaces:**
- Alert types: `TRADE_SETUP_READY`, `STRUCTURE_CHANGE`, `HIGH_IMPACT_NEWS`, `RISK_BLOCK`, `PROVIDER_DEGRADED`, `READINESS_CHANGED`.

- [ ] **Step 1: Write RED materiality/dedupe tests**

Assert routine unchanged conditions do not create alerts; same dedupe key updates `last_observed_at` rather than creating duplicates; provider degradation and readiness status change create one material event.

- [ ] **Step 2: Write RED delivery tests using MockTransport**

Implement server-side delivery interfaces for Telegram, LINE Messaging API, and generic webhook. Tests must assert secrets appear only in outbound headers/body as required and are not written to alert payload or logs.

- [ ] **Step 3: Implement alert derivation + delivery isolation**

External delivery failure changes delivery state but does not rollback alert persistence and does not fail the worker cycle.

Add env defaults:

```text
ALERTS_V1_ENABLED=false
ALERT_CHANNELS=IN_APP
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
LINE_CHANNEL_ACCESS_TOKEN=
LINE_TARGET_ID=
ALERT_WEBHOOK_URL=
```

- [ ] **Step 4: Wire strategy-worker stage after metrics refresh**

Worker order becomes outcomes -> expiry -> simulation -> reconcile -> metrics -> alerts.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_strategy_alerts.py tests/test_alert_delivery.py tests/test_strategy_worker.py -q`

```bash
git add btc_core/strategy/alerts.py btc_core/strategy/alert_delivery.py btc_core/strategy/repository.py services/strategy_worker/app/main.py .env.example tests/test_strategy_alerts.py tests/test_alert_delivery.py
git commit -m "feat: add material strategy alerts"
```

---

# Wave 4 — Phase 9 Readiness + Dry-Run Order Intents + API/Web + Production Rollout

### Task 9: Readiness Engine

**Files:**
- Create: `btc_core/strategy/readiness.py`
- Create: `tests/test_readiness.py`
- Modify: `btc_core/strategy/repository.py`
- Modify: `services/strategy_worker/app/main.py`

**Interfaces:**
- Produces immutable `NOT_READY`, `PAPER_READY`, `LIVE_READY`, or `BLOCKED` readiness snapshots with mandatory check evidence.

- [ ] **Step 1: Write RED readiness tests**

PAPER_READY requires:
- provider/model reachable;
- >=20 attempts;
- success >=95%;
- p95 <=10s;
- scanner isolation healthy;
- migrations/RLS check healthy;
- simulation account healthy;
- full risk evaluator enabled;
- alert persistence healthy;
- no critical integrity failures.

LIVE_READY requires all PAPER_READY plus:
- >=7 consecutive validation days;
- >=200 AI attempts;
- provider success >=98%;
- invalid response <=1%;
- p95 <=10s;
- >=100 closed full-quality simulated trades;
- positive net expectancy;
- profit factor >=1.20;
- max drawdown <=10%;
- no reconciliation errors;
- daily-loss/max-position/event guards verified;
- kill switch verified;
- >=50 consecutive valid eligible DRY_RUN intents with zero schema/risk failures;
- exchange execution eligibility/connectivity check not blocked;
- private exchange credentials reported configured without revealing values.

Insufficient evidence must never be promoted by lowering thresholds.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_readiness.py -q`

- [ ] **Step 3: Implement deterministic readiness evaluator**

No AI call. No config mutation. Persist every changed/evidence evaluation as immutable snapshot.

- [ ] **Step 4: Wire worker stage after alerts and run tests**

Run: `pytest tests/test_readiness.py tests/test_strategy_worker.py -q`

- [ ] **Step 5: Commit**

```bash
git add btc_core/strategy/readiness.py btc_core/strategy/repository.py services/strategy_worker/app/main.py tests/test_readiness.py
git commit -m "feat: add production readiness engine"
```

### Task 10: DRY_RUN Order Intent Generator and Kill Switch Boundary

**Files:**
- Create: `btc_core/strategy/order_intents.py`
- Create: `tests/test_order_intents.py`
- Create: `tests/test_no_live_execution.py`
- Modify: `btc_core/strategy/repository.py`
- Modify: `services/strategy_worker/app/main.py`
- Modify: `.env.example`

**Interfaces:**
- Produces only `mode=DRY_RUN` order-intent records with `exchange_submission_allowed=false`.

- [ ] **Step 1: Write RED intent tests**

Assert:
- only full-risk-approved eligible setups produce an intent;
- deterministic idempotency key prevents duplicate intents;
- intent carries symbol/side/quantity/leverage/entry/SL/TP and risk evidence;
- `mode == "DRY_RUN"` always;
- `exchange_submission_allowed is False` always;
- no intent for WAIT/PRECHECK_FAILED/account-context-missing/readiness-blocked inputs.

- [ ] **Step 2: Write source safety test**

`tests/test_no_live_execution.py` must scan production Python/TS source and fail if Phase 8–9 introduces known private Binance order submission paths or calls such as `/fapi/v1/order`, `POST order`, or a new execution adapter capable of submitting orders. Allow public market endpoints already present.

Also assert `.env.example` contains:

```text
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
LIVE_ORDER_EXECUTION_ENABLED=false
ORDER_INTENT_DRY_RUN_ENABLED=false
```

- [ ] **Step 3: Run RED**

Run: `pytest tests/test_order_intents.py tests/test_no_live_execution.py -q`

- [ ] **Step 4: Implement generator and worker stage**

Worker order becomes outcomes -> expiry -> simulation -> reconcile -> metrics -> alerts -> readiness -> dry-run intents.

No private Binance authenticated order call may be added.

- [ ] **Step 5: Run tests and commit**

Run: `pytest tests/test_order_intents.py tests/test_no_live_execution.py tests/test_strategy_worker.py -q`

```bash
git add btc_core/strategy/order_intents.py btc_core/strategy/repository.py services/strategy_worker/app/main.py .env.example tests/test_order_intents.py tests/test_no_live_execution.py
git commit -m "feat: add dry-run order intent safety boundary"
```

### Task 11: Read-Only API Contracts

**Files:**
- Create: `btc_core/strategy/read_repository.py` if separating anon-safe reads from service-role writes improves clarity.
- Modify: `services/api/app/main.py`
- Modify: `services/api/app/config.py`
- Create/Modify: `tests/test_api_strategy.py`

**Interfaces:**
- Endpoints:
  - `GET /api/v1/performance/summary`
  - `GET /api/v1/performance/outcomes`
  - `GET /api/v1/simulation/account`
  - `GET /api/v1/simulation/trades`
  - `GET /api/v1/alerts`
  - `GET /api/v1/readiness`
  - `GET /api/v1/order-intents?mode=DRY_RUN`
  - `GET /api/v1/experiments`

- [ ] **Step 1: Write RED API tests**

Assert bounded `limit` and pagination/cursor behavior for lists; sanitized output; no `input_snapshot`, API keys, tokens, webhook URLs, raw provider bodies, or auth headers; no POST/PUT/PATCH/DELETE live-execution route.

Public config may expose only booleans like `telegram_configured`, not secret values.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_api_strategy.py tests/test_api.py tests/test_api_market.py -q`

- [ ] **Step 3: Implement readers/endpoints**

Keep FastAPI dependencies short-lived and read-only using anon key. Ensure CORS still allows GET only.

- [ ] **Step 4: Run tests and commit**

```bash
pytest tests/test_api_strategy.py tests/test_api.py tests/test_api_market.py -q
git add btc_core/strategy/read_repository.py services/api/app/main.py services/api/app/config.py tests/test_api_strategy.py
git commit -m "feat: expose read-only strategy operations API"
```

### Task 12: Web/PWA Performance, Simulation, Alerts, and Readiness UI

**Files:**
- Modify: `apps/web/src/api.ts`
- Modify: `apps/web/src/App.tsx`
- Modify: `apps/web/src/styles.css`
- Create: `tests/test_web_phase_8_9_contract.py`

**Interfaces:**
- Display four operational sections: Performance, Simulation, Alerts, Readiness, plus DRY_RUN intents.

- [ ] **Step 1: Write RED web contract test**

Assert source contains:
- readiness states `NOT_READY`, `PAPER_READY`, `LIVE_READY`, `BLOCKED`;
- exact warning: `Live execution remains disabled. LIVE_READY means readiness checks passed; it does not submit orders.`;
- exact DRY_RUN badge: `DRY RUN — NOT SUBMITTED`;
- insufficient-sample UI state;
- no secret input field for exchange/API credentials in Phase 8–9;
- analysis/trade association uses IDs, not symbol-only matching.

- [ ] **Step 2: Run RED**

Run: `pytest tests/test_web_phase_8_9_contract.py -q`

- [ ] **Step 3: Implement API types/fetchers and UI**

Performance: provider/model/sample/success/error/median/p95/win-rate/expectancy/profit-factor/drawdown/TP-SL rates.
Simulation: balance/equity/realized PnL/drawdown/daily loss/open/pending/recent closed/costs.
Alerts: only material persisted events.
Readiness: overall state + every PASS/FAIL/PENDING check + blocking reasons.
Order intents: always fixed DRY_RUN badge.

- [ ] **Step 4: Build and test**

Run:
```bash
pytest tests/test_web_phase_8_9_contract.py -q
cd apps/web
npm install
npm run build
```
Expected: PASS/build exit 0.

- [ ] **Step 5: Commit**

```bash
git add apps/web/src/api.ts apps/web/src/App.tsx apps/web/src/styles.css tests/test_web_phase_8_9_contract.py
git commit -m "feat: add Phase 8-9 operations dashboard"
```

### Task 13: Documentation, CI Safety, and Production Rollout Configuration

**Files:**
- Modify: `README.md`
- Create: `docs/operations/phase-8-9-production-rollout.md`
- Modify: `.github/workflows/ci.yml` only if needed to ensure both backend tests and web build remain mandatory.
- Modify: `.env.example`
- Create: `tests/test_phase_8_9_safety_defaults.py`

- [ ] **Step 1: Write RED safety-default tests**

Assert documentation/env defaults preserve:
- `TRADING_MODE=SIMULATION`
- `DIRECT_AI_ORDER_ENABLED=false`
- `LIVE_ORDER_EXECUTION_ENABLED=false`
- strategy feature flags OFF by default in example/config until rollout step explicitly enables them;
- no exchange private order endpoint.

- [ ] **Step 2: Document exact rollout sequence**

Required production order:
1. apply schema migration;
2. deploy strategy-worker with all Phase 8 feature flags OFF;
3. verify RLS/table/indexes and scanner health;
4. enable `OUTCOME_EVALUATION_ENABLED=true` only;
5. validate idempotent outcomes;
6. enable `SIMULATION_ENGINE_ENABLED=true`;
7. validate accounting/reconciliation;
8. enable `ALERTS_V1_ENABLED=true` with `ALERT_CHANNELS=IN_APP` first;
9. enable `READINESS_V1_ENABLED=true`;
10. enable `ORDER_INTENT_DRY_RUN_ENABLED=true` only after paper gates are healthy;
11. keep live execution flags false;
12. expand AI candidate limit 1 -> 3 and concurrency 1 -> 2 only after rolling 20-attempt canary gate passes.

Rollback must disable strategy feature flags without touching market-worker/realtime ingestion.

- [ ] **Step 3: Run full repository verification**

Run:
```bash
pytest -q
cd apps/web && npm install && npm run build
```
Expected: zero backend failures and web build exit 0.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/operations/phase-8-9-production-rollout.md .github/workflows/ci.yml .env.example tests/test_phase_8_9_safety_defaults.py
git commit -m "docs: add Phase 8-9 safe production rollout"
```

---

# Codex Execution Protocol

Codex must execute this plan in order and must not implement live exchange submission.

## Required working method

1. Read the approved spec and this plan completely before editing code.
2. Create an isolated feature branch/worktree from current `main`.
3. Execute one task at a time with TDD RED -> GREEN.
4. Commit after each task using the commit messages in this plan or equivalent focused messages.
5. At the end of each Wave, run full backend tests and web build before continuing.
6. Do not silently weaken tests, risk thresholds, readiness thresholds, RLS, or safety flags to obtain GREEN.
7. If a requirement conflicts with current repository reality, stop that task, document the conflict, and choose the safest backward-compatible interpretation; do not invent a live execution path.
8. Never print, read back, commit, or expose production secret values.
9. All external provider/delivery tests use mocks; CI must not make paid AI calls or send real notifications.
10. Before final PR, run a source audit proving no private Binance order submission call was added.

## Final PR acceptance checklist

The final implementation is acceptable only if:
- full `pytest -q` passes;
- web `npm run build` passes;
- migration tests prove RLS and idempotency;
- strategy-worker is isolated from market-worker;
- simulation PnL/cost/reconciliation tests pass;
- alert dedupe tests pass;
- readiness tests pass without threshold relaxation;
- dry-run intent safety tests prove `exchange_submission_allowed=false`;
- no private exchange order submission code exists;
- README/rollout docs explicitly state `LIVE_READY` does not enable live trading;
- production rollout is performed incrementally with feature flags and verified after each step.

## Production verification after merge

After merging and deploying, verify with live operational data but no live orders:
- scanner cycles continue with zero AI-caused failures;
- strategy-worker starts independently;
- outcomes are idempotent;
- simulation account reconciles;
- alerts dedupe;
- readiness status reflects actual evidence and is likely `NOT_READY` or `PAPER_READY` until sample requirements accrue;
- DRY_RUN intents, if generated, are never submitted;
- `TRADING_MODE=SIMULATION`, `DIRECT_AI_ORDER_ENABLED=false`, `LIVE_ORDER_EXECUTION_ENABLED=false` remain true safety boundaries.
