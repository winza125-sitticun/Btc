# REZ Analysis Engine Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the tested Phase 1 structure primitives into the canonical repo and add a deterministic 15m trigger engine for breakout, reclaim, retest, liquidity sweep, rejection, and volume confirmation.

**Architecture:** Add an isolated `btc_core.analysis` package. Keep detection pure and deterministic over closed `Candle` data. Do not wire Phase 2 into order creation, execution, or production alert behavior in this branch.

**Tech Stack:** Python 3.12+, Pydantic market models, pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-rez-analysis-phase2-design.md`

## Global Constraints

- Analysis-only; no direct order placement.
- Existing Risk Engine remains final safety authority.
- SIMULATION/SHADOW behavior remains unchanged.
- Closed candles only.
- No lookahead.
- Malformed or insufficient data fails closed.
- Do not modify existing order-intent, execution, or portfolio-risk behavior.

---

### Task 1: Port Phase 1 Structure Primitives

**Files:**
- Create: `btc_core/analysis/__init__.py`
- Create: `btc_core/analysis/structure.py`
- Test: `tests/test_analysis_structure.py`

**Interfaces:**
- Consumes: `btc_core.market.models.Candle` or candle-like mappings.
- Produces: `find_confirmed_swings()`, `label_swing_sequence()`, `classify_structure_state()`, `detect_structure_break()`, `analyze_market_structure()`.

- [ ] Write failing tests covering no-lookahead swing confirmation, HH/HL/LH/LL labels, close-only BOS/CHoCH, wick rejection, malformed-data fail-closed.
- [ ] Run the new test file and confirm RED because `btc_core.analysis.structure` does not exist.
- [ ] Port the already validated Phase 1 implementation into the package without adding production runtime wiring.
- [ ] Run `pytest tests/test_analysis_structure.py -q` and confirm GREEN.

### Task 2: Add Breakout, Reclaim, Sweep, Rejection, and Volume Primitives

**Files:**
- Create: `btc_core/analysis/triggers.py`
- Test: `tests/test_analysis_triggers.py`

**Interfaces:**
- Consumes: closed 15m `Candle` sequence, explicit structural level, configurable buffers/ratios.
- Produces: `detect_breakout()`, `detect_reclaim()`, `detect_liquidity_sweep()`, `detect_rejection()`, `volume_is_confirmed()`.

- [ ] Write RED tests proving wick-only penetration is not a breakout and close-confirmed breaks respect `break_buffer`.
- [ ] Add RED tests proving reclaim requires a prior opposite-side close.
- [ ] Add RED tests for bullish/bearish liquidity sweeps.
- [ ] Add RED tests for rejection wick/body threshold.
- [ ] Add RED tests proving volume SMA excludes current candle and requires sufficient prior bars.
- [ ] Implement minimal pure functions to make these tests GREEN.
- [ ] Run `pytest tests/test_analysis_triggers.py -q`.

### Task 3: Add Retest State Evaluation

**Files:**
- Modify: `btc_core/analysis/triggers.py`
- Modify: `tests/test_analysis_triggers.py`

**Interfaces:**
- Consumes: originating breakout/reclaim event index, level, direction, closed candles, retest window.
- Produces: `evaluate_retest()` result with `RETEST_CONFIRMED`, `RETEST_FAILED`, or no event.

- [ ] Write RED tests for successful bullish and bearish retests.
- [ ] Write RED tests for close-confirmed failed retest.
- [ ] Write RED tests proving candles before the origin event are ignored and events outside the 1-6 bar window do not qualify.
- [ ] Implement minimal deterministic retest logic.
- [ ] Run `pytest tests/test_analysis_triggers.py -q`.

### Task 4: Add Unified 15m Trigger Analyzer

**Files:**
- Modify: `btc_core/analysis/triggers.py`
- Modify: `tests/test_analysis_triggers.py`

**Interfaces:**
- Consumes: candles, level, level role (`SUPPORT`/`RESISTANCE`), optional origin event, buffers and volume settings.
- Produces: `analyze_15m_trigger()` bounded result with `trigger_type`, `direction`, `status`, `level`, `candle_index`, `candle_time`, `volume_confirmed`, and `evidence`.

- [ ] Write RED tests for priority and status behavior.
- [ ] Ensure a liquidity sweep alone is evidence and does not masquerade as breakout confirmation.
- [ ] Ensure malformed/insufficient input returns `status="NONE"`.
- [ ] Implement the unified analyzer.
- [ ] Run both Phase 1 and Phase 2 test files together.

### Task 5: Regression Verification and PR

**Files:**
- No production wiring changes.

- [ ] Run full backend pytest suite in CI.
- [ ] Confirm no imports were added to execution/order modules.
- [ ] Confirm branch diff touches only analysis package, tests, and docs.
- [ ] Open a PR to `main` with explicit note that Phase 2 is analysis-only and not runtime-wired.
