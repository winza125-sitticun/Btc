# REZ Analysis Layer V1 — Design Specification

Date: 2026-09-16
Status: Approved design, pending user review of written spec
Branch: `deploy/v6-shadow`

## 1. Goal

Add the REZUSDT-style multi-timeframe analysis method as a deterministic Analysis Layer on top of Scanner V6 without replacing or weakening the existing system.

The existing V6 remains authoritative for:

- market-provider selection and provider lock per scan cycle
- TradingView 4H/1H/15m recommendations
- EMA200 / ADX / DI / funding filters
- TradingView/provider price-basis guard
- structure-based Entry / SL / TP planning
- minimum structure R:R
- deterministic Setup Score 0–100
- `SETUP_MIN_SCORE=75`
- Astra as Devil's Advocate only
- Telegram delivery and cooldown
- Shadow Evaluation and fail-closed behavior
- decision-support only; no live or testnet order execution

REZ V1 adds context and timing. It must not invent a new LONG/SHORT direction, lower existing risk thresholds, override Astra, or place orders.

## 2. Selected Architecture

The Analysis Layer is inserted after the existing Structure Trade Plan and before Setup Score.

```text
Market Data Session
    |
    v
Existing V6 deterministic filters
    |
    v
Existing Structure Trade Plan
    |
    v
REZ Analysis Layer V1
    |-- PASS
    |-- WAIT
    `-- REJECT
    |
    v
Existing Setup Score
    |
    v
Score >= 75
    |
    v
Astra Devil's Advocate
    |
    v
Telegram
```

When `REZ_ANALYSIS_ENABLED=false`, the current V6 flow must remain behaviorally unchanged.

When enabled, REZ V1 runs in the approved HYBRID behavior: deterministic context/timing gate first, unchanged V6 Setup Score second.

## 3. Inputs and Data Discipline

REZ V1 uses only closed candles from the market provider already locked for the current scan cycle.

Required inputs per candidate:

- existing V6 side: `LONG` or `SHORT`
- existing 4H / 1H / 15m TradingView context
- closed 1H candles
- closed 15m candles
- existing 1H/4H structure plan
- existing ATR configuration
- current provider identity

Rules:

1. Never use an unfinished candle for BOS, CHoCH, retest, reclaim, sweep, or rejection confirmation.
2. Never mix Binance and Bybit candles inside one candidate evaluation.
3. Missing or malformed required candle data is fail-closed.
4. REZ V1 never changes the side chosen by existing V6 logic.

## 4. 1H Structure Classification

Output enum:

```text
CONTINUATION
PULLBACK
REVERSAL
RANGE
UNKNOWN
```

V1 reuses the existing confirmed-swing concept and current structure settings:

- swing window: `STRUCTURE_SWING_WINDOW`
- ATR period: `STRUCTURE_ATR_PERIOD`
- 1H confirmation buffer: `STRUCTURE_ATR_BUFFER_MULT * ATR(1H)`

### 4.1 Confirmed BOS

For a LONG-side context:

```text
1H close > last confirmed swing high + 1H ATR buffer
```

For a SHORT-side context:

```text
1H close < last confirmed swing low - 1H ATR buffer
```

A wick-only breach is not a BOS.

### 4.2 Protected swing and invalidation

After a directional BOS, the most recent confirmed opposite swing becomes the protected swing for that structure leg.

- LONG protected swing: last confirmed swing low
- SHORT protected swing: last confirmed swing high

A closed 1H candle beyond the protected swing plus the same 1H ATR buffer invalidates that structure leg.

### 4.3 Classification rules

`CONTINUATION`
- existing side remains structurally valid
- latest confirmed BOS is in the same direction as V6 side
- protected swing remains intact

`PULLBACK`
- prior same-side BOS is confirmed
- protected swing remains intact
- current price has retraced back toward the breakout / swing zone but has not closed through invalidation

`REVERSAL`
- the prior structure is invalidated by a closed 1H candle beyond its protected swing plus 1H ATR buffer
- a new confirmed BOS then forms in the same direction as the current V6 side
- a single CHoCH or wick is insufficient

`RANGE`
- no directional BOS can be confirmed for the current side
- protected directional structure is not clearly established
- recent confirmed swings overlap or alternate without a valid directional break

`UNKNOWN`
- candle history, ATR, or confirmed swings are insufficient to classify deterministically

`UNKNOWN` is fail-closed and becomes `REJECT` at the Analysis Layer.

## 5. 15m Trigger Classification

Output may contain one primary trigger plus supporting trigger tags:

```text
BREAKOUT
RETEST
RECLAIM
LIQUIDITY_SWEEP
REJECTION
NO_TRIGGER
```

V1 uses:

- ATR period: `STRUCTURE_ATR_PERIOD`
- 15m confirmation buffer: `STRUCTURE_ATR_BUFFER_MULT * ATR(15m)`

This reuses the same configuration values as V6 but calculates ATR on the trigger timeframe itself.

### 5.1 Trigger reference level

The trigger level is deterministic:

- `CONTINUATION`: the most recent same-side 1H BOS level
- `PULLBACK`: the most recent same-side 1H BOS level being retested
- `REVERSAL`: the newly confirmed same-side 1H BOS level
- `RANGE`: the nearest confirmed 1H range boundary relevant to the current V6 side; RANGE can only produce `WAIT` in V1

The trigger zone is `trigger_level ± 15m ATR buffer`.

### 5.2 BREAKOUT

For LONG:

```text
closed 15m close > trigger level + 15m ATR buffer
```

For SHORT:

```text
closed 15m close < trigger level - 15m ATR buffer
```

### 5.3 RETEST

A prior same-side 15m breakout must already be confirmed. A later closed 15m candle must trade into the trigger zone and close back on the valid side of the trigger level.

### 5.4 RECLAIM

Price trades through the trigger level, then a later closed 15m candle closes back on the valid side of that level. Reclaim is valid only if the 1H protected swing is still intact.

### 5.5 LIQUIDITY_SWEEP

Use the latest confirmed 15m local swing against the intended side, found with `STRUCTURE_SWING_WINDOW`.

- LONG: wick breaches the latest confirmed 15m swing low, then the same candle closes back above that swing level
- SHORT: wick breaches the latest confirmed 15m swing high, then the same candle closes back below that swing level

A sweep is a supporting trigger tag in V1. `LIQUIDITY_SWEEP` alone never changes the Analysis state to PASS. It must accompany a valid `REJECTION`, `RECLAIM`, or `RETEST` condition allowed by the decision matrix.

### 5.6 REJECTION

A closed 15m candle must trade into the trigger zone and close back on the valid side of the trigger level.

For LONG:

```text
lower_wick = min(open, close) - low
body       = abs(close - open)
lower_wick >= body
close > trigger_level
```

For SHORT:

```text
upper_wick = high - max(open, close)
body       = abs(close - open)
upper_wick >= body
close < trigger_level
```

A zero-body candle is not sufficient by itself.

### 5.7 NO_TRIGGER

None of the deterministic trigger conditions above are confirmed on closed candles.

### 5.8 Explicit opposite-side trigger

An opposite-side trigger is present when a closed 15m candle confirms a breakout against the V6 side beyond the latest confirmed 15m opposite swing by the 15m ATR buffer.

- LONG candidate: close below confirmed 15m swing low minus buffer
- SHORT candidate: close above confirmed 15m swing high plus buffer

This produces `REJECT`.

## 6. Hybrid Decision Matrix

REZ V1 returns one of:

```text
PASS
WAIT
REJECT
```

Rules:

```text
CONTINUATION + BREAKOUT/RETEST/REJECTION       -> PASS
PULLBACK     + RETEST/REJECTION/RECLAIM        -> PASS
REVERSAL     + confirmed RECLAIM/BREAKOUT      -> PASS

CONTINUATION + NO_TRIGGER                       -> WAIT
PULLBACK     + NO_TRIGGER                       -> WAIT
RANGE        + any non-opposite trigger         -> WAIT
REVERSAL without confirmed RECLAIM/BREAKOUT     -> WAIT

Explicit opposite-side trigger                  -> REJECT
1H protected structure invalidated              -> REJECT
UNKNOWN / insufficient required candle data     -> REJECT
```

`LIQUIDITY_SWEEP` may strengthen the context as a supporting tag but does not override the matrix.

`WAIT` is a first-class state, not a failure. It is re-evaluated on later scan cycles.

## 7. Watch State and Re-evaluation

A candidate that returns `WAIT` enters a persistent watch state in the existing Shadow SQLite database.

State progression:

```text
NEW
  -> ANALYSIS_WAIT
  -> ANALYSIS_PASS
  -> SCORE_WAIT / SCORE_PASS
  -> ASTRA_WAIT / APPROVED / REJECTED
  -> ALERT_SENT
```

### 7.1 Stable watch identity

A watch must not be recreated every five minutes. The stable key is derived from:

```text
symbol + side + protected_swing_timestamp + trigger_level_kind + analysis_version
```

The protected swing timestamp is used instead of raw floating-point price so the identity is deterministic.

### 7.2 Re-evaluation

- scanner continues on the existing schedule
- a watch is re-evaluated only when a newer closed 15m candle is available
- unchanged closed-candle timestamp does not create a duplicate analysis event
- `WAIT -> PASS` is allowed when a valid trigger later appears
- opposite structure invalidation immediately closes the watch as invalidated

### 7.3 TTL

Default:

```text
REZ_WATCH_TTL_HOURS=12
```

If the watch has not reached `PASS` within 12 hours, it becomes `EXPIRED` and is no longer re-evaluated.

## 8. Persistence Design

Do not rewrite the existing Shadow outcome schema. Add REZ-specific tables in the same SQLite database so V6 evaluation remains backward compatible.

### 8.1 `rez_watch_state`

Minimum fields:

```text
id
watch_key UNIQUE
symbol
side
analysis_version
analysis_state
structure_1h
trigger_15m
wait_reason
protected_swing_timestamp
protected_swing_price
trigger_level_kind
trigger_level_price
first_seen_at_ms
last_checked_at_ms
last_closed_15m_at_ms
expires_at_ms
invalidated_at_ms NULL
```

### 8.2 `rez_analysis_events`

Append-only audit events:

```text
id
watch_id
shadow_snapshot_id NULL
created_at_ms
structure_1h
trigger_15m
analysis_state
analysis_reason
provider
closed_1h_at_ms
closed_15m_at_ms
```

Rules:

- `WAIT_ANALYSIS` events may exist without a Shadow snapshot because score calculation has not run yet
- after `PASS`, if the existing V6 path creates a Shadow snapshot, the corresponding REZ event is updated once with that `shadow_snapshot_id`
- existing Shadow snapshot tables do not require new columns for REZ V1

The existing V6 Shadow snapshot remains the source for score, Astra verdict, alert state, MFE/MAE, TP/SL outcome, and R-multiple evaluation.

## 9. Setup Score Integration

V1 does not change `setup_score_v6.py` weights or the minimum score.

```text
REZ PASS + Setup Score < 75  -> WAIT_SCORE
REZ PASS + Setup Score >=75  -> Astra
REZ WAIT                     -> WAIT_ANALYSIS
REZ REJECT                   -> REJECT_ANALYSIS
```

This preserves a clean calibration baseline. Any future score bonus or penalty for REZ patterns requires a separate reviewed version.

## 10. Astra Integration

Astra remains Devil's Advocate only.

Astra is called only when:

```text
REZ Analysis = PASS
AND
existing Setup Score >= SETUP_MIN_SCORE
```

Add the following deterministic metadata to the Astra prompt:

- `analysis_version`
- `structure_1h`
- `trigger_15m`
- supporting trigger tags such as `LIQUIDITY_SWEEP`
- `analysis_reason`

Astra may return only the existing outcomes:

```text
APPROVED
WAIT
REJECT
```

Astra cannot:

- change LONG to SHORT or SHORT to LONG
- bypass deterministic invalidation
- lower score threshold
- generate an order

AI failure remains fail-closed.

## 11. Telegram Output

Only an existing V6 signal that passes REZ, score, Astra, and cooldown is sent.

Add compact REZ context to the existing alert:

```text
1H Structure: PULLBACK
15m Trigger: RETEST + REJECTION
Analysis: REZ_V1
```

Entry, SL, TP1–TP3, R:R, BTC bias, score, Astra confidence, provider, and invalidation remain sourced from existing V6 components.

`WAIT_ANALYSIS`, `WAIT_SCORE`, `WAIT_ASTRA`, `REJECT_ANALYSIS`, and expired watches do not send signal alerts in V1.

## 12. Configuration

New configuration:

```text
REZ_ANALYSIS_ENABLED=false
REZ_ANALYSIS_VERSION=REZ_V1
REZ_WATCH_TTL_HOURS=12
```

V1 intentionally reuses the existing swing and ATR configuration instead of introducing additional sensitivity knobs.

Rollout rule: deploy code with `REZ_ANALYSIS_ENABLED=false`, verify V6 regression behavior, then enable the approved HYBRID behavior after verification.

## 13. Failure Handling

Fail-closed conditions:

- missing required closed candle history
- invalid ATR
- no confirmed swing where one is required
- provider mismatch
- malformed persistence record
- REZ database write failure when REZ is enabled

A REZ failure must never be converted into a synthetic PASS.

When REZ is disabled, none of these new paths may affect the existing V6 scan.

## 14. Calibration Metrics

Shadow reporting must be able to calculate, by analysis version, structure type, and trigger type:

- `WAIT -> PASS` conversion rate
- `PASS -> score >= 75` rate
- `PASS -> Astra APPROVED` rate
- sample count
- TP1 / TP2 / TP3 hit rate
- SL rate
- ambiguous same-candle outcome count
- average and median MFE in R
- average and median MAE in R
- average realized R where available
- expiry rate
- invalidation rate

No automatic threshold tuning is allowed in V1.

## 15. Observability

Each scan cycle should expose compact counts without logging secrets:

```text
REZ: pass=N wait=N reject=N expired=N promoted=N
```

Per-candidate logs should explain deterministic state transitions, for example:

```text
REZUSDT: 1H=PULLBACK 15m=NO_TRIGGER -> WAIT_ANALYSIS
REZUSDT: WAIT_ANALYSIS -> PASS (RETEST + REJECTION)
```

Do not print raw API keys, Telegram tokens, or secret-bearing payloads.

## 16. Implementation Boundaries

Expected new modules:

```text
scanner_v6/rez_analysis_v1.py
scanner_v6/rez_watch_v1.py
scanner_v6/rez_report_v1.py
```

Expected integration points:

```text
scanner_v6/auto_scanner_v6.part*.py
scanner_v6/shadow_eval_v6.part*.py   # schema/bootstrap integration only where needed
```

Tests must be added for the new modules rather than placing all behavior into the scanner loop.

Unrelated refactoring is out of scope.

## 17. Test Strategy

Implementation follows TDD.

Required deterministic coverage:

1. confirmed LONG and SHORT BOS require close plus 1H ATR buffer
2. wick-only BOS is rejected
3. continuation classification
4. pullback classification while protected swing remains intact
5. reversal requires invalidation plus new confirmed BOS
6. range classification
7. unknown/missing data fails closed
8. breakout uses 15m ATR buffer and a closed 15m candle
9. retest requires prior breakout
10. reclaim requires close back onto valid side
11. liquidity sweep requires confirmed 15m swing wick breach plus close back inside
12. liquidity sweep alone cannot PASS
13. rejection wick/body rule
14. no unfinished candle can confirm a trigger
15. explicit opposite-side trigger rejects
16. Hybrid PASS matrix
17. Hybrid WAIT matrix
18. watch-key duplicate protection
19. unchanged closed 15m timestamp does not create duplicate event
20. WAIT can promote to PASS
21. protected-structure break invalidates a watch
22. 12-hour expiry
23. disabled flag preserves existing V6 behavior
24. REZ WAIT does not call Astra
25. REZ PASS with score <75 does not call Astra
26. REZ PASS with score >=75 can call Astra
27. AI failure remains fail-closed
28. existing score weights remain unchanged
29. existing Shadow outcome evaluation remains unchanged
30. REZ event links to Shadow snapshot after PASS without changing Shadow schema
31. Telegram is not sent for WAIT/REJECT states
32. existing scanner tests remain green

External market and AI calls are mocked in unit tests.

## 18. Rollout

### Phase A — code deployed disabled

```text
REZ_ANALYSIS_ENABLED=false
```

Verify build, tests, scanner cadence, 80-symbol universe, provider lock, volume mount, Gemini health, Telegram health, and unchanged V6 decisions.

### Phase B — Hybrid canary

Enable:

```text
REZ_ANALYSIS_ENABLED=true
```

Keep:

```text
SETUP_MIN_SCORE=75
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

Observe REZ state counts and watch transitions before making any scoring changes.

### Phase C — calibration

Accumulate sufficient Shadow samples and compare outcome metrics by structure/trigger type. Any changes to score weights, thresholds, TTL, or trigger sensitivity require separate evidence and review.

## 19. Out of Scope

REZ Analysis Layer V1 does not include:

- live or testnet order execution
- automatic order placement
- automatic score-weight tuning
- lowering `SETUP_MIN_SCORE`
- lowering minimum structure R:R
- changing market-provider failover behavior
- changing the 80-symbol universe selection logic
- replacing TradingView recommendations
- AI-generated direction changes
- AI-generated Entry/SL/TP geometry
- automatic promotion of calibration findings into production rules

## 20. Success Criteria

REZ V1 succeeds when:

1. disabling REZ leaves V6 behavior unchanged
2. enabled HYBRID behavior deterministically classifies 1H structure and 15m trigger from closed provider candles
3. WAIT setups persist and can promote to PASS without duplicate watches
4. invalidated and expired watches stop re-evaluating
5. REZ does not alter the existing Setup Score formula or threshold
6. Astra is called only after REZ PASS and score >=75
7. Telegram remains final-output only after all existing approvals
8. existing Shadow outcome metrics remain valid and REZ-specific calibration is measurable
9. missing/invalid REZ data fails closed
10. decision-support-only safety remains intact
