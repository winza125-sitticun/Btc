# REZ Analysis Engine Phase 2 Design

**Project:** BTC AI Futures Trader  
**Scope:** deterministic 15m trigger analysis built on the approved REZ workflow  
**Branch:** `feature/rez-analysis-phase2-triggers`  
**Safety:** analysis-only; SIMULATION/SHADOW safety remains unchanged

## Goal

Convert the manual REZUSDT trigger-reading workflow into deterministic, replayable rules for closed 15-minute candles:

`4H direction -> 1H structure -> 15m trigger -> structural risk candidate -> Astra`

Phase 2 implements the 15m trigger layer only. It does not place orders, change portfolio risk limits, enable PRIMARY/LIVE/TESTNET execution, or allow AI to override deterministic safety gates.

## Dependency

The Phase 1 structure engine was developed and tested outside the canonical repository. Because Phase 2 depends on confirmed swings and close-confirmed BOS/CHoCH, Phase 1 primitives are first ported into `btc_core/analysis/structure.py` without wiring them into production runtime.

## Components

### `btc_core/analysis/structure.py`

Provides deterministic Phase 1 primitives:

- confirmed swing highs/lows with left/right confirmation bars
- HH/HL/LH/LL/EQH/EQL labeling
- structure state classification
- close-confirmed BOS/CHoCH
- no-lookahead behavior

### `btc_core/analysis/triggers.py`

Provides deterministic Phase 2 primitives:

- breakout/breakdown confirmation by candle close
- reclaim confirmation after a prior penetration/break
- successful and failed retest evaluation
- liquidity sweep detection
- rejection detection using configurable wick/body ratio
- volume confirmation using SMA of prior closed bars
- bounded unified trigger result

## Trigger Rules

### Breakout / Breakdown

A resistance breakout is confirmed only when a closed candle finishes above:

`level + break_buffer`

A support breakdown is symmetric. Wick-only penetration never confirms a breakout or breakdown.

### Reclaim

A bullish reclaim requires a prior candle to close below the protected level and a later closed candle to close back above `level + reclaim_buffer`. Bearish reclaim is symmetric.

### Retest

Default retest window is 1 to 6 closed 15m bars after a confirmed breakout/reclaim.

A bullish retest succeeds when a later candle tests the protected level/zone and closes back above the protected side without a close-confirmed invalidation. A bullish retest fails when a closed candle finishes below `level - break_buffer`. Bearish logic is symmetric.

### Liquidity Sweep

Bullish support sweep:

`low < support - sweep_buffer AND close >= support`

Bearish resistance sweep:

`high > resistance + sweep_buffer AND close <= resistance`

A sweep is evidence only and is never sufficient by itself to create an actionable entry.

### Rejection

A rejection requires a level test plus a close away from the level and a configurable minimum wick/body ratio. Zero-body candles use a small deterministic epsilon to avoid division by zero.

### Volume Confirmation

Elevated volume default:

`current_volume >= 1.20 * SMA(previous 20 closed bars)`

The current candle is excluded from the SMA baseline. Volume strengthens another trigger but cannot replace close confirmation.

## Output Contract

Trigger functions return deterministic dictionaries or `None`. The unified analyzer returns:

- `trigger_type`
- `direction`
- `status`: `NONE`, `CLOSED_CONFIRMED`, or `INVALIDATED`
- `level`
- `candle_index`
- `candle_time`
- `volume_confirmed`
- `evidence`

No LLM-generated field is part of deterministic trigger detection.

## Failure Handling

Malformed candles, negative buffers, invalid windows, insufficient volume history, or missing required prior events fail closed to no trigger / false confirmation. Functions do not infer missing market data.

## Testing Requirements

Tests must prove:

1. wick-only penetration does not confirm breakout/breakdown;
2. close-confirmed breakout/breakdown respects configured buffers;
3. reclaim requires a prior opposite-side close;
4. retest is evaluated only after its originating event and within the configured window;
5. failed retest is distinguishable from successful retest;
6. liquidity sweep does not become a breakout;
7. rejection respects wick/body threshold;
8. volume SMA excludes the current candle and requires sufficient prior history;
9. malformed/insufficient data fails closed;
10. no Phase 2 module has order-placement capability.

## Integration Boundary

This phase deliberately stops before production orchestration. A later phase will combine:

- 4H regime
- 1H structure context
- 15m trigger result
- Entry/SL/TP/R:R candidate
- Astra synthesis
- deterministic Risk Engine gating

That later integration must remain SIMULATION/SHADOW first and preserve existing safety authority.
