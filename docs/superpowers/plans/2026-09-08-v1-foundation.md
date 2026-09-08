# AI Futures Trader V1 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a testable cloud-first foundation for the AI crypto futures trader without enabling live trading.

**Architecture:** Shared Python domain modules define AI, scanner, risk, and simulation contracts. FastAPI exposes health/config endpoints. Supabase migration defines persistent data. A React/Vite PWA provides the initial operator shell. Railway hosts Python services and Cloudflare hosts static web assets.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic v2, pytest, PostgreSQL/Supabase, React, TypeScript, Vite, Cloudflare Workers Static Assets, Railway.

**Spec:** `docs/superpowers/specs/2026-09-08-v1-foundation-design.md`

## Global Constraints
- Default trading mode is SIMULATION.
- AI cannot bypass the deterministic risk engine.
- No local AI runtime is required.
- Browser code never receives plaintext AI or exchange secrets.
- Live order execution is outside this milestone.

---

### Task 1: Domain contracts and scanner scoring
**Files:** `tests/test_ai_models.py`, `tests/test_scoring.py`, `btc_core/ai/models.py`, `btc_core/scanner/scoring.py`
- [ ] Write failing tests for AI structured validation and weighted opportunity scoring.
- [ ] Run tests and confirm RED due to missing modules.
- [ ] Implement minimal Pydantic contracts and scoring function.
- [ ] Run tests and confirm GREEN.

### Task 2: Deterministic risk gate
**Files:** `tests/test_risk_engine.py`, `btc_core/risk/engine.py`
- [ ] Write failing approval/rejection tests for confidence, score, RR, leverage, daily loss, position count, and event guard.
- [ ] Run tests and confirm RED.
- [ ] Implement deterministic policy evaluation.
- [ ] Run tests and confirm GREEN.

### Task 3: Simulation position accounting
**Files:** `tests/test_simulation.py`, `btc_core/simulation/models.py`
- [ ] Write failing LONG/SHORT PnL tests including costs.
- [ ] Run tests and confirm RED.
- [ ] Implement mark-to-market PnL calculations.
- [ ] Run tests and confirm GREEN.

### Task 4: FastAPI service
**Files:** `tests/test_api.py`, `services/api/app/main.py`, `services/api/app/config.py`
- [ ] Write failing health and safe-public-config API tests.
- [ ] Run tests and confirm RED.
- [ ] Implement the endpoints with SIMULATION as default mode.
- [ ] Run tests and confirm GREEN.

### Task 5: Database and deployment foundation
**Files:** `supabase/migrations/202609080001_v1_foundation.sql`, `.env.example`, `railway.toml`, `wrangler.jsonc`, `.github/workflows/ci.yml`
- [ ] Define tables, RLS, indexes, and environment variable contract.
- [ ] Add CI that runs the Python suite and web build.

### Task 6: React PWA operator shell
**Files:** `apps/web/package.json`, `apps/web/vite.config.ts`, `apps/web/src/*`, `apps/web/index.html`
- [ ] Build Dashboard and Settings shells using mock data and mobile-first responsive layout.
- [ ] Keep secret values out of frontend state contracts.
- [ ] Verify TypeScript/Vite build in CI where dependencies can be installed.
