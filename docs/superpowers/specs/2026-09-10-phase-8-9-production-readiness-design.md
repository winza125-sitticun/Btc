# Phase 8–9 Production Readiness Design

Status: Design A approved in chat; written spec pending final user review.

Date: 2026-09-10
Repository: `winza125-sitticun/Btc`

## 1. Goal

Extend the existing production AI Analysis V1 pipeline from a working Top-1 production canary into a complete simulation/evaluation/alert/readiness system through Phase 9.

The milestone ends with software that can:

1. evaluate AI signal quality over time,
2. run deterministic paper trades with realistic costs and full account-level risk checks,
3. persist learning metrics without allowing self-modifying production rules,
4. create deduplicated material alerts,
5. continuously score production readiness,
6. generate fully validated dry-run order intents when every gate passes,
7. prove that live execution is blocked unless a later, explicit activation milestone enables it.

This milestone does **not** send real exchange orders. `TRADING_MODE=SIMULATION` remains the production mode, `DIRECT_AI_ORDER_ENABLED=false` remains invariant, and the new `LIVE_ORDER_EXECUTION_ENABLED=false` default prevents an execution path from becoming active accidentally.

## 2. Current Baseline

The current system already has:

- Binance USD-M scanner and realtime ingestion.
- News enrichment.
- AI Analysis V1 with bounded 4h/1h/15m snapshots.
- Gemini/Claude/OpenAI-compatible/DeepSeek/OpenRouter provider adapters.
- Production Gemini canary currently using `gemini-3.5-flash-lite`.
- `market_ai_analyses` persistence with RLS and sanitized reads.
- Deterministic signal precheck using `RiskPolicy`.
- Existing simulation primitives and user-owned simulation tables from the V1 foundation.
- Web cards for scanner + AI analysis.
- Production evidence that Gemini Flash-Lite can complete an analysis in low-single-digit seconds.

Current deterministic risk defaults remain authoritative:

- minimum confidence: 75
- minimum opportunity score: 75
- minimum risk/reward: 2.0
- maximum leverage: 5x
- maximum risk per trade: 1%
- maximum daily loss: 3%
- maximum open positions: 3
- high-impact event guard blocks new entries

## 3. Scope Boundaries

### In scope

- Phase 7 production validation metrics required before expanding AI canary.
- AI signal outcome evaluation at 1h, 4h, and 24h horizons.
- Deterministic simulation entry/exit matching.
- Account-level simulation risk context and sizing.
- Fees, slippage, and funding estimates.
- Strategy/model performance metrics.
- Rule experiment registry and simulation-only promotion workflow.
- In-app material alerts and optional Telegram/LINE/webhook delivery adapters.
- Provider health/degradation monitoring.
- Readiness evaluation with explicit blocking reasons.
- Dry-run order intents and audit trail.
- API and Web UI for Performance, Simulation, Alerts, and Readiness.
- Production migrations, worker deployment, CI, and rollout controls.

### Out of scope

- Real exchange order submission.
- Automatic promotion of learned rules into production.
- AI-controlled risk limits.
- AI-controlled leverage or position sizing.
- Hidden relaxation of risk thresholds to increase trade frequency.
- Automatic Binance API key creation or credential management.
- Any claim that past simulation performance guarantees future profit.

## 4. Safety Invariants

The following invariants are hard requirements, not configurable recommendations:

1. AI output never submits an exchange order directly.
2. `DIRECT_AI_ORDER_ENABLED` remains `false` throughout Phase 8–9.
3. `TRADING_MODE` remains `SIMULATION` throughout Phase 8–9 production rollout.
4. `LIVE_ORDER_EXECUTION_ENABLED` defaults to `false` and Phase 8–9 contains no live submission call.
5. Every actionable simulation trade must pass deterministic price geometry, static signal precheck, full account-level risk, event guard, and position sizing.
6. Missing risk context fails closed for order intent generation.
7. Outcome learning may measure and propose changes, but never edits thresholds, provider settings, prompts, or code automatically.
8. New strategy/rule variants must run in simulation and collect evidence before they can be marked `PROMOTABLE`.
9. Readiness status is evidence-based and can only become `LIVE_READY` when every mandatory check passes.
10. A `LIVE_READY` status still does not enable live order submission.
11. Provider, alert, evaluation, or learning failures must never invalidate scanner persistence or stop realtime ingestion.
12. Secrets remain server-side and are never returned in API responses, persisted in analytics payloads, or logged.

## 5. Target Architecture

### Existing `market-worker`

Responsibility remains narrow:

`Binance → Scanner → News Enrichment → AI Analysis → persist analysis → realtime ingestion`

Changes to `market-worker` should be limited to emitting/persisting the data needed by downstream evaluation. It must not become the simulation/accounting/alert worker.

### New `strategy-worker`

Add a separate long-running Railway service built from the same repository. It consumes persisted production data and performs all Phase 8–9 post-analysis work:

`market_ai_analyses → outcome evaluator → full simulation risk → paper matching → metrics → alerts → readiness → dry-run order intents`

The separation is intentional:

- scanner latency is isolated from evaluation workloads,
- provider failures cannot block paper accounting,
- simulation bugs cannot stop market ingestion,
- readiness logic can be tested independently,
- future execution activation can be isolated behind a different service/flag.

### API/Web

The API remains read-only for Phase 8–9 operational data. The Web/PWA adds four views or sections:

- Performance
- Simulation
- Alerts
- Readiness

No browser endpoint can enable live execution or set exchange secrets.

## 6. Phase 7 — Production Validation Gate

Before expanding AI from Top 1 to Top 3, collect rolling operational metrics from `market_ai_analyses`.

### Metrics

For the active provider/model and timeframe:

- attempts
- successes
- failures by `error_code`
- success rate
- median latency
- p95 latency
- invalid response rate
- scanner cycle failure rate
- candidate coverage

### Canary expansion policy

`AI_ANALYSIS_CANDIDATE_LIMIT` remains 1 until all are true over a minimum rolling sample of 20 attempted analyses:

- AI provider success rate >= 95%
- invalid response rate <= 2%
- p95 AI latency <= 10 seconds
- scanner cycles remain independent with no AI-caused cycle failures
- no secret/config leakage findings

After the gate passes, expand to:

- candidate limit: 3
- concurrency: 2

If the rolling 20-attempt success rate later falls below 90% or p95 latency exceeds 20 seconds, automatically mark provider health `DEGRADED`; alert the operator and recommend canary reduction, but do not silently change model/provider configuration.

## 7. Signal Outcome Evaluation

### Purpose

Measure AI signal quality regardless of whether the signal was eligible to become a simulated trade. This prevents survivorship bias and supports model comparison.

### Table: `market_ai_signal_outcomes`

One row per `(ai_analysis_id, horizon)`.

Fields:

- `id bigint identity primary key`
- `ai_analysis_id bigint not null references market_ai_analyses(id)`
- `scanner_candidate_id bigint not null`
- `symbol text not null`
- `timeframe text not null`
- `direction text not null`
- `horizon text check in ('1H','4H','24H')`
- `signal_created_at timestamptz not null`
- `evaluation_due_at timestamptz not null`
- `entry_reference numeric`
- `entry_touched boolean`
- `stop_touched boolean`
- `highest_tp_hit integer default 0`
- `mfe_percent numeric`
- `mae_percent numeric`
- `final_return_percent numeric`
- `outcome text check in ('PENDING','WIN','LOSS','NEUTRAL','NO_FILL','INVALIDATED')`
- `data_quality text check in ('FULL','PARTIAL','MISSING')`
- `evaluated_at timestamptz`
- unique `(ai_analysis_id, horizon)`

### Evaluation rules

- Evaluate all `SUCCESS` AI analyses, including signals later rejected by risk.
- `WAIT` signals are measured for calibration but never create simulated positions.
- LONG/SHORT entry uses the published entry range.
- `entry_touched=false` at horizon produces `NO_FILL`.
- MFE/MAE are computed from market price path after signal creation.
- TP/SL touch ordering uses the finest bounded market data available.
- If both SL and TP are touched inside the same unresolved candle, use a conservative stop-first assumption.
- Missing data never becomes a fabricated win/loss; mark `PARTIAL`/`MISSING` and exclude from readiness performance aggregates requiring full quality.

### Market data strategy

The evaluator first uses persisted candles. If required path coverage is missing, it may fetch bounded public Binance kline history for the exact symbol/window. It must not request private account endpoints.

## 8. Simulation/Paper Trade Engine

### Eligibility

A simulated trade may be created only when:

- AI analysis status is `SUCCESS`,
- direction is LONG or SHORT,
- static precheck status is `FULL_RISK_CONTEXT_PENDING`,
- entry geometry is valid,
- full account risk evaluation approves,
- event guard is not blocking,
- there is capacity under max open positions.

Signals with `PRECHECK_FAILED`, `WAIT`, provider failures, or incomplete geometry can still be evaluated for learning but cannot open a simulation trade.

### Production system simulation account

Do not reuse the user-owned V1 `simulation_accounts` row as the worker's implicit account. Add an explicit system-scoped paper ledger so the production worker does not need to impersonate an auth user.

### Table: `market_simulation_accounts`

- `id uuid primary key`
- `name text unique`
- `starting_balance numeric > 0`
- `balance numeric`
- `equity numeric`
- `realized_pnl numeric`
- `max_equity numeric`
- `max_drawdown_percent numeric`
- `daily_realized_loss numeric`
- `trading_date date`
- timestamps

Initial production account:

- name: `Production Canary`
- starting balance: 1000 USDT

### Table: `market_simulation_trades`

- unique reference to the originating AI analysis
- symbol / side
- status: `PENDING_ENTRY`, `OPEN`, `TP_EXIT`, `SL_EXIT`, `EXPIRED`, `CLOSED`
- planned entry range
- actual simulated entry
- quantity
- leverage
- risk amount
- stop loss
- TP array
- highest TP reached
- fees
- slippage
- funding
- realized PnL
- realized return percent
- opened/closed/expired timestamps
- exit reason
- full risk decision reasons

### Entry validity

Default 15m signal entry validity window: 60 minutes after analysis creation.

If price never enters the entry range during the validity window, mark `EXPIRED`; do not chase price.

### Position sizing

Use deterministic risk-based sizing, never AI sizing.

Defaults:

- target risk per trade: 0.5% of current simulation balance
- hard cap: `RiskPolicy.max_risk_percent` (1%)
- leverage: minimum required to support the bounded notional, capped at 5x
- maximum open positions: 3

Quantity is based on stop distance and risk amount, then capped by account balance × allowed leverage. Invalid or zero stop distance fails closed.

### Costs

Conservative configurable defaults:

- taker fee: 5 bps per fill
- slippage: 2 bps per fill

Funding uses the nearest stored funding-rate observation for funding timestamps crossed by the position. If funding data is unavailable, the trade is marked `funding_quality=PARTIAL`; readiness aggregates requiring full cost quality exclude it.

### Exit matching

- SL is authoritative and closes remaining quantity.
- TP ladder may support partial exits, but V1 Phase 8 defaults to deterministic equal thirds across TP1/TP2/TP3 when all three exist.
- If fewer TPs exist, split evenly across available TPs.
- Same-candle unresolved TP/SL ambiguity is resolved conservatively in favor of SL.
- All realized PnL includes fees, slippage, and funding.

## 9. Full Risk Context

Add a pure deterministic `FullRiskContext` + evaluator layered after the existing AI precheck.

Inputs:

- confidence
- opportunity score
- risk/reward
- requested leverage
- computed risk percent
- current daily realized loss percent
- number of open simulation positions
- event guard state
- account equity/balance
- data quality flags

The existing `RiskPolicy` remains the source of hard thresholds.

Missing required account/risk context returns rejected with explicit reasons such as:

- `account_context_missing`
- `position_size_invalid`
- `market_data_quality_insufficient`
- `event_context_missing`

For simulation, event-context missing is recorded and may block a trade when the configured policy requires event coverage. For `LIVE_READY`, event context is mandatory.

## 10. Learning and Strategy Metrics

### Principle

Learning is measurement + experiment management. It is **not** autonomous self-modification.

### Table: `market_strategy_metrics`

Aggregate by:

- provider
- model
- timeframe
- direction
- optional symbol
- rolling window (`24H`, `7D`, `30D`, `ALL`)

Metrics:

- analysis count
- eligible signal count
- simulated trade count
- no-fill count
- win/loss count
- win rate
- average net return
- median net return
- expectancy
- profit factor
- max drawdown
- average MFE/MAE
- TP1/TP2/TP3 hit rates
- SL hit rate
- provider success rate
- median/p95 latency
- sample/data-quality counts

### Table: `market_strategy_experiments`

Purpose: record proposed rule/model/prompt/threshold changes and force them through simulation evidence before promotion.

Lifecycle:

- `DRAFT`
- `SIMULATION`
- `PROMOTABLE`
- `REJECTED`
- `ARCHIVED`

Required fields include description, baseline identifier, variant configuration, start/end windows, sample count, metric deltas, and decision reason.

Hard rule: Phase 8–9 never automatically changes Railway variables, prompts, risk thresholds, or production code based on an experiment result.

## 11. Alert Engine

### Alert classes

Persist only material events:

- `TRADE_SETUP_READY` — full simulation risk approved and entry is still valid.
- `STRUCTURE_CHANGE` — material direction/regime change across scanner runs.
- `HIGH_IMPACT_NEWS` — high impact + sufficient credibility + relevant asset.
- `RISK_BLOCK` — otherwise-eligible setup blocked by daily loss/max positions/event guard.
- `PROVIDER_DEGRADED` — rolling AI health breaches operational limits.
- `READINESS_CHANGED` — readiness status changes.

Routine price moves and repeated unchanged conditions are not alerts.

### Table: `market_alert_events`

Fields:

- id
- alert type
- severity
- symbol nullable
- source analysis/run IDs
- title
- short summary
- dedupe key
- payload JSONB containing only sanitized operational fields
- first/last observed timestamps
- status: `NEW`, `ACKNOWLEDGED`, `EXPIRED`
- delivery state per configured channel

Unique/dedupe behavior prevents repeated notifications for the same signal/condition.

### Delivery

In-app persistence is always available.

Optional server-side adapters:

- Telegram Bot API
- LINE Messaging API
- generic webhook

External delivery is disabled unless its secret/config is present. Missing external delivery configuration never fails the worker and never causes scanner failure.

Proposed environment flags:

```text
ALERTS_V1_ENABLED=true
ALERT_CHANNELS=IN_APP
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
LINE_CHANNEL_ACCESS_TOKEN=
LINE_TARGET_ID=
ALERT_WEBHOOK_URL=
```

Secrets are never exposed through public config. Public API may only expose booleans such as `telegram_configured`.

## 12. Production Readiness Engine

### Table: `market_readiness_checks`

Each evaluation produces one immutable snapshot with:

- overall status
- mandatory checks JSONB
- evidence window
- metrics snapshot
- blocking reasons
- created_at

### Statuses

- `NOT_READY`
- `PAPER_READY`
- `LIVE_READY`
- `BLOCKED`

### PAPER_READY mandatory checks

- current provider/model configured and reachable
- rolling 20-attempt AI success >= 95%
- p95 AI latency <= 10 seconds
- scanner failure isolation proven by recent cycles
- migrations/RLS present
- simulation account healthy
- full risk evaluator enabled
- alert persistence healthy
- no critical data-integrity failures

### LIVE_READY mandatory checks

All PAPER_READY checks plus:

Operational evidence:

- at least 7 consecutive days of production validation
- at least 200 AI analysis attempts
- provider success rate >= 98% over readiness window
- invalid response rate <= 1%
- p95 AI latency <= 10 seconds

Simulation evidence:

- at least 100 closed, full-data-quality simulated trades
- positive net expectancy after fees/slippage/funding
- profit factor >= 1.20
- max drawdown <= 10%
- no unresolved accounting reconciliation errors

Risk/execution evidence:

- daily-loss guard verified
- max-position guard verified
- event guard data source healthy and verified
- kill switch verified
- 50 consecutive eligible dry-run order intents validate with zero schema/risk failures
- exchange execution eligibility/connectivity check is not blocked
- required private exchange credentials are reported configured, without exposing values

If evidence is insufficient, the system remains `PAPER_READY` or `NOT_READY`; it must not lower thresholds automatically.

## 13. Dry-Run Order Intent

### Purpose

Prove that the complete pre-order pipeline can produce deterministic, auditable exchange-shaped instructions without actually sending them.

### Table: `market_order_intents`

Fields:

- id
- source simulation trade / AI analysis
- mode fixed to `DRY_RUN` in Phase 9
- symbol
- side
- quantity
- leverage
- entry type/price
- stop loss
- take-profit instructions
- deterministic risk decision ID/snapshot
- client intent id / idempotency key
- validation status
- rejection reasons
- `exchange_submission_allowed boolean not null default false`
- timestamps

Phase 8–9 code must assert `exchange_submission_allowed=false` on every created row.

No HTTP call to a private Binance order endpoint exists in this milestone.

## 14. Kill Switch and Activation Boundary

Add production configuration:

```text
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
LIVE_ORDER_EXECUTION_ENABLED=false
STRATEGY_WORKER_ENABLED=true
OUTCOME_EVALUATION_ENABLED=true
SIMULATION_ENGINE_ENABLED=true
ALERTS_V1_ENABLED=true
READINESS_V1_ENABLED=true
ORDER_INTENT_DRY_RUN_ENABLED=true
```

A future live-execution milestone must require all of the following simultaneously before it can submit an order:

- `TRADING_MODE=LIVE`
- `LIVE_ORDER_EXECUTION_ENABLED=true`
- current readiness snapshot = `LIVE_READY`
- exchange credentials configured
- execution eligibility probe passes
- deterministic full risk passes at submission time

That future milestone requires separate explicit user authorization. It is not part of Phase 8–9.

## 15. Database and RLS

Add one migration for Phase 8–9 data structures, or split into narrowly ordered migrations if deployment safety requires it.

New system-owned market tables:

- `market_ai_signal_outcomes`
- `market_simulation_accounts`
- `market_simulation_trades`
- `market_strategy_metrics`
- `market_strategy_experiments`
- `market_alert_events`
- `market_readiness_checks`
- `market_order_intents`

RLS is enabled on every new table.

Policy shape:

- service role writes
- anon/authenticated read only for sanitized operational fields where appropriate
- no secret/config field is stored in these tables
- raw provider response bodies are not stored

Indexes must cover due outcome evaluations, open/pending simulation trades, recent alerts, readiness latest snapshot, and strategy metric windows.

Idempotency constraints prevent duplicate outcome rows, duplicate simulated trade creation from one analysis, and duplicate order intents.

## 16. Strategy Worker Cycle

Default cycle: 60 seconds, configurable between 30 and 300 seconds.

Order of work:

1. finalize due AI outcome horizons,
2. expire stale pending entries,
3. evaluate new eligible AI analyses for simulation,
4. update/open/close simulated trades from bounded market paths,
5. reconcile simulation account balance/equity/drawdown,
6. refresh strategy metrics,
7. derive material alerts,
8. evaluate provider operational health,
9. compute readiness snapshot when evidence changed,
10. create dry-run order intents only for fully approved eligible setups.

Each stage is independently fail-open with respect to later market scanning because it is in a separate worker. Inside `strategy-worker`, failures are isolated per stage and recorded without silently skipping accounting consistency checks.

## 17. API Contract

Add sanitized read endpoints:

- `GET /api/v1/performance/summary`
- `GET /api/v1/performance/outcomes`
- `GET /api/v1/simulation/account`
- `GET /api/v1/simulation/trades`
- `GET /api/v1/alerts`
- `GET /api/v1/readiness`
- `GET /api/v1/order-intents?mode=DRY_RUN`
- `GET /api/v1/experiments`

Limits and pagination are mandatory on list endpoints.

No endpoint in Phase 8–9 may:

- enable live execution,
- accept exchange API secrets,
- submit exchange orders,
- edit risk limits from browser input.

## 18. Web/PWA Design

### Performance

Show:

- provider/model
- sample size
- success/error rate
- median/p95 latency
- win rate
- expectancy
- profit factor
- drawdown
- TP/SL hit rates
- explicit `insufficient sample` state

### Simulation

Show:

- starting/current balance
- equity
- realized PnL
- max drawdown
- daily loss
- open positions
- pending entries
- recent closed trades
- fees/slippage/funding

### Alerts

Show only material events, severity, symbol, reason, source time, and delivery state.

### Readiness

Prominent status card:

- `NOT_READY`
- `PAPER_READY`
- `LIVE_READY`
- `BLOCKED`

Show every mandatory gate with PASS/FAIL/PENDING and evidence. If `LIVE_READY`, still display:

`Live execution remains disabled. LIVE_READY means readiness checks passed; it does not submit orders.`

### Dry-run Order Intents

Display generated intents with a fixed badge:

`DRY RUN — NOT SUBMITTED`

## 19. Testing Strategy

Use TDD for every implementation task.

### Pure unit tests

- horizon/outcome calculations LONG/SHORT/WAIT
- no-fill and expiry
- MFE/MAE
- same-candle conservative SL precedence
- simulation sizing
- fee/slippage/funding calculations
- daily-loss/max-position/event guards
- drawdown/account reconciliation
- strategy metrics
- readiness threshold evaluation
- alert dedupe/materiality
- order-intent idempotency and `exchange_submission_allowed=false`

### Repository/migration tests

- schema exists
- RLS enabled
- unique/idempotency constraints
- safe read columns
- service-role write patterns

### Worker tests

- stage failure isolation
- no duplicate processing
- restart/retry idempotency
- provider degradation does not corrupt simulation state
- market-worker remains independent

### API tests

- sanitized outputs
- pagination/limits
- secrets absent
- no write/live-execution endpoints

### Web contract/build tests

- new sections compile
- readiness warning text always present
- dry-run badge always present
- stale analysis/trade association protection

### CI safety tests

Explicitly grep/assert that:

- production defaults remain `TRADING_MODE=SIMULATION`
- `DIRECT_AI_ORDER_ENABLED=false`
- `LIVE_ORDER_EXECUTION_ENABLED=false`
- no production private-order submission call is introduced in Phase 8–9
- secrets are not embedded in Docker image/build args or frontend bundle

## 20. Production Rollout

### Step A — Schema + disabled code

Deploy migrations and strategy-worker code with Phase 8 feature flags off. Verify RLS, health, and no scanner regression.

### Step B — Outcomes only

Enable outcome evaluator. Verify 1h/4h/24h rows finalize idempotently.

### Step C — Simulation canary

Enable simulation for one qualifying signal at a time. Verify sizing/accounting and cost calculations.

### Step D — Alerts + metrics

Enable in-app alerts and metrics. Keep external channels off until their server-side configuration is supplied.

### Step E — Phase 7 Top-3 expansion

Only after operational canary gate passes, set AI candidate limit 3 / concurrency 2.

### Step F — Readiness + dry-run intents

Enable readiness computation and dry-run intents. Confirm every intent has `exchange_submission_allowed=false`.

### Step G — Observe readiness

System may reach `PAPER_READY` once operational checks pass. It may only reach `LIVE_READY` after minimum evidence windows and all external readiness requirements pass.

No Phase 8–9 rollout step changes `TRADING_MODE` away from `SIMULATION`.

## 21. Operational Defaults

Recommended production defaults:

```text
AI_ANALYSIS_CANDIDATE_LIMIT=1
AI_ANALYSIS_CONCURRENCY=1
AI_TIMEOUT_SECONDS=60
AI_MAX_RETRIES=0

STRATEGY_WORKER_ENABLED=true
STRATEGY_WORKER_INTERVAL_SECONDS=60
OUTCOME_EVALUATION_ENABLED=true
SIMULATION_ENGINE_ENABLED=true
SIM_STARTING_BALANCE_USDT=1000
SIM_TARGET_RISK_PERCENT=0.5
SIM_TAKER_FEE_BPS=5
SIM_SLIPPAGE_BPS=2
SIM_ENTRY_VALID_MINUTES=60

ALERTS_V1_ENABLED=true
ALERT_CHANNELS=IN_APP
READINESS_V1_ENABLED=true
ORDER_INTENT_DRY_RUN_ENABLED=true

TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
LIVE_ORDER_EXECUTION_ENABLED=false
```

Top-3 expansion is a later operational change after the Phase 7 evidence gate, not an initial Phase 8 deployment default.

## 22. Definition of Done

Phase 8–9 implementation is complete when all of the following are verified with fresh evidence:

1. full backend test suite passes,
2. web build passes,
3. migrations apply successfully to production and RLS is verified,
4. strategy-worker deploys successfully and can restart idempotently,
5. outcome rows are created/finalized from real production analyses,
6. at least one real production AI success can be evaluated through the simulation eligibility pipeline,
7. risk-rejected signals do not create simulated trades,
8. qualifying signals can create deterministic simulated trades when full risk approves,
9. account PnL/cost/drawdown reconciliation is verified,
10. performance metrics are exposed through API/UI,
11. material alerts are persisted and deduplicated,
12. readiness endpoint/UI shows evidence and blocking reasons,
13. dry-run order intents are produced only after full risk and always show `exchange_submission_allowed=false`,
14. market scanner/realtime continue operating if strategy-worker is down,
15. production remains `SIMULATION`, direct AI order remains disabled, and live execution remains disabled.

## 23. Meaning of “Ready to Use” at End of Phase 9

At the end of this milestone, the product is ready for continuous production **paper trading, outcome learning, material alerts, performance measurement, and live-readiness assessment**.

It is not automatically ready to risk real funds simply because the software milestone is complete. The runtime readiness state may remain `NOT_READY` or `PAPER_READY` until enough real production evidence exists. `LIVE_READY` is earned only by the deterministic evidence gates above.

Actual live order submission requires a separate activation milestone and explicit user authorization after `LIVE_READY`, exchange credential/eligibility verification, and a final preflight review.