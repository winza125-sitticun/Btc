# Binance USD-M Market Engine V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only Binance USD-M market adapter and market-only opportunity scanner using real public futures data.

**Architecture:** Normalize Binance REST payloads into domain models, compute deterministic market features, then scan only the highest-volume USDT perpetual contracts with bounded concurrency. No authenticated endpoints or order code are introduced.

**Tech Stack:** Python 3.12+, httpx, Pydantic v2, asyncio, pytest, FastAPI foundation, Binance USD-M public REST API.

**Spec:** `docs/superpowers/specs/2026-09-08-binance-market-engine-v1-design.md`

## Global Constraints
- Public/read-only Binance endpoints only.
- No API key or exchange secret is accepted by the market client.
- Trading mode remains SIMULATION.
- AI cannot bypass the existing risk engine.
- Scanner requests are concurrency-bounded and one-symbol failures are isolated.

---

### Task 1: Binance market models and client
**Files:** `tests/test_binance_usdm_client.py`, `btc_core/market/models.py`, `btc_core/market/binance_usdm.py`
- [ ] Write failing normalization/filtering/error tests.
- [ ] Confirm RED.
- [ ] Implement minimal public REST client and normalized models.
- [ ] Confirm GREEN.

### Task 2: Deterministic market feature builder
**Files:** `tests/test_market_features.py`, `btc_core/market/features.py`
- [ ] Write failing LONG/SHORT/WAIT feature tests.
- [ ] Confirm RED.
- [ ] Implement dependency-free EMA/momentum/volume/taker/OI/funding/liquidity scoring.
- [ ] Confirm GREEN.

### Task 3: Opportunity scanner orchestration
**Files:** `tests/test_binance_market_scanner.py`, `btc_core/market/scanner.py`
- [ ] Write failing top-volume selection/ranking/failure-isolation tests.
- [ ] Confirm RED.
- [ ] Implement bounded-concurrency scanner.
- [ ] Confirm GREEN.

### Task 4: Worker entry point and package/deployment wiring
**Files:** `services/market_worker/__init__.py`, `services/market_worker/app/__init__.py`, `services/market_worker/app/main.py`, `pyproject.toml`, `.env.example`, `README.md`
- [ ] Add one-shot worker entry point and configuration.
- [ ] Verify full pytest suite and Python compile.
- [ ] Verify GitHub Actions backend and web jobs.
