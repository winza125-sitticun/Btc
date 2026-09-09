# Koyeb News Intelligence Worker Production Rollout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Package the existing Phase 5A news worker for Koyeb, deploy it in Singapore, and record evidence that ingestion and safety invariants hold.

**Architecture:** Keep the existing `services.news_worker.app.main` process unchanged. Add only Koyeb buildpack discovery/runtime files, deploy a single worker from `main`, and validate the existing Supabase news and scanner tables with read-only queries.

**Tech Stack:** Python 3.12.14, Koyeb Python buildpack, Supabase PostgREST/Postgres, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-09-koyeb-news-worker-rollout-design.md`

## Global Constraints

- `TRADING_MODE=SIMULATION`.
- `DIRECT_AI_ORDER_ENABLED=false`.
- No AI provider keys or calls.
- No Binance authenticated execution or withdrawal capability.
- No scanner score or schema changes.
- `SUPABASE_SERVICE_ROLE_KEY` remains a Koyeb-only secret.
- No HTML scraping or silent source replacement.
- Near-duplicate window remains 24 hours, Jaccard threshold `0.82`, with no stemming.

## Tasks

1. Add and test `requirements.txt`, `.python-version`, and `.koyebignore`; run backend tests and web build; merge through PR and CI.
2. Create the Koyeb Worker service with the approved source, region, command, variables, secret, and one `eco-nano` instance.
3. Capture deployment SHA and `T0`; wait for two successful cycles; run the approved Supabase verification queries and inspect Koyeb configuration/logs.
4. Diagnose any recurring source failure without automatic disablement; use a separate tested PR only for a confirmed structural feed incompatibility.
5. Record all evidence in `docs/operations/news-worker-production-rollout.md` and merge it through a docs-only PR ignored by Koyeb autodeploy.
