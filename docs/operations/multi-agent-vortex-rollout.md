# Multi-Agent Trading Intelligence Rollout & Rollback Runbook

This runbook is the T012 release gate for the multi-agent trading-intelligence milestone. The feature remains simulation-first and read-only from the operator/browser perspective.

## Release safety invariants

- Trading posture remains `SIMULATION`.
- `DIRECT_AI_ORDER_ENABLED=false` remains mandatory for this milestone.
- Generated order intents remain `DRY_RUN` and `exchange_submission_allowed=false`.
- The deterministic risk engine remains the sole authorization gate after consensus.
- AI roles, providers, consensus, dashboard state, and event views cannot bypass deterministic risk.
- Missing account/portfolio risk context remains pending/not authorized.
- Provider/API credentials stay server-side and must not appear in public config, run detail, performance, dashboard event, or browser payloads.
- Existing single-provider data remains readable from `/api/v1/ai/latest` and is distinct from `/api/v1/multi-agent/*` records.
- No testnet or live-execution adapter is introduced by this rollout.

## Approved scope variance: T011 omitted

T011 — Pure Vortex Visual Mapping + Optional 3D/Fallback — was intentionally omitted by product decision before T012.

The approved final UI for this milestone is the non-3D explainability dashboard delivered by T010. It exposes role state, provider/model, confidence, consensus, agreement, coverage, hesitation factors, deterministic risk, and correlated events without introducing a visualization decision engine.

Because T011 is intentionally omitted:

- `SC-010` is **not applicable** to this release because no Vortex visual-state mapping is shipped.
- `SC-011` is **not applicable** to this release because no 3D view is shipped; the product already uses the non-3D dashboard as the primary and only explainability view.
- No Three.js, React Three Fiber, WebGL visualization, or Vortex rendering is a release dependency.
- Removing the optional visualization scope does not change scanner, agent, consensus, risk, performance, simulation, API, or polling behavior.

All remaining success criteria, especially SC-001 through SC-009 and SC-012, remain release-gating.

## Rollout sequence

Use the exact rollout progression:

`OFF -> SHADOW -> PRIMARY`

Never jump directly from an unknown/invalid configuration to an active mode.

### 1. OFF

Recommended initial state:

```bash
AI_MULTI_AGENT_ENABLED=false
AI_MULTI_AGENT_MODE=OFF
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

Expected behavior:

- Multi-agent orchestration is disabled.
- Legacy single-provider analysis remains available through `/api/v1/ai/latest`.
- Market scanner persistence and realtime market ingestion continue normally.
- Invalid, absent, or unsupported rollout mode must fail closed to OFF.

### 2. SHADOW

After database migrations and read APIs are verified:

```bash
AI_MULTI_AGENT_ENABLED=true
AI_MULTI_AGENT_MODE=SHADOW
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

Expected behavior:

- Multi-agent runs execute and persist evidence.
- Role attempts, consensus, hesitation, deterministic risk, performance inputs, and dashboard events are observable.
- Multi-agent results do not replace the operational legacy strategy path.
- Multi-agent order intent generation remains suppressed outside PRIMARY.
- Provider failure must not stop scanner persistence or realtime market ingestion.

Before promotion, verify at least:

1. Every persisted run references one scanner candidate and frozen config version.
2. Agent attempts share the frozen snapshot reference.
3. Replaying the same validated decisions/config reproduces consensus exactly.
4. Hesitation total reconstructs from its stored factor contributions.
5. Deterministic risk can reject an actionable consensus.
6. Public responses contain no API key, token, authorization header, credential, service-role secret, prompt text, or raw provider body.
7. Performance weighting excludes outcomes that mature after the decision timestamp.
8. Cold-start agents remain unproven until the documented sample threshold is reached.
9. `/api/v1/ai/latest` remains readable for legacy records.
10. Browser polling and stale/retry behavior matches the fixed contract below.

### 3. PRIMARY

Promote only after SHADOW evidence is healthy:

```bash
AI_MULTI_AGENT_ENABLED=true
AI_MULTI_AGENT_MODE=PRIMARY
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

Expected behavior:

- Healthy multi-agent analysis may become the primary analysis source for newly eligible candidates.
- Existing legacy records remain readable and distinguishable.
- Multi-agent operational order intents are allowed only after deterministic full-risk approval, remain DRY_RUN, and still have `exchange_submission_allowed=false`.
- Any unhealthy multi-agent execution path must preserve market ingestion and use the existing fail-open/fallback behavior documented by the market-worker integration.

PRIMARY does not mean live trading.

## Fixed dashboard polling contract

Persisted backend state is always the source of truth.

- Visible in-progress run: refresh every `3s`.
- Visible terminal/list view: refresh every `15s`.
- Hidden browser tab: refresh every `60s`.
- Mark dashboard data stale after `30s` without a successful refresh.
- Failed refresh retry schedule: `2s -> 5s -> 10s -> 30s`, then remain capped at 30s until recovery.
- A successful refresh resets retry backoff.

Browser reconnects must reconstruct state from persisted APIs; client memory or realtime messages are never the only evidence copy.

## Correlation and compatibility checks

For a multi-agent-originated simulated trade, the same `multi_agent_run_id` must remain traceable through:

1. multi-agent run,
2. deterministic risk evidence,
3. DRY_RUN order intent,
4. simulation trade lifecycle,
5. `/api/v1/multi-agent/events`.

The event stream must preserve sanitized source identity across `MULTI_AGENT`, `ORDER_INTENT`, and `SIMULATION` events.

Legacy compatibility is mandatory: `/api/v1/ai/latest` remains the single-provider read path and multi-agent records use their separate `/api/v1/multi-agent/*` surface. Do not rewrite legacy IDs or migrate legacy rows into multi-agent records.

## No-live-execution regression evidence

The release is blocked if any of these conditions are false:

- `TRADING_MODE=SIMULATION`
- `DIRECT_AI_ORDER_ENABLED=false`
- Order-intent mode is `DRY_RUN`.
- `exchange_submission_allowed=false`.
- Multi-agent agent/provider code has no direct exchange-submission authority.
- Testnet/live execution remains a separate future specification and approval gate.

## Rollback

The preferred rollback is configuration-only and non-destructive:

```bash
AI_MULTI_AGENT_ENABLED=false
AI_MULTI_AGENT_MODE=OFF
TRADING_MODE=SIMULATION
DIRECT_AI_ORDER_ENABLED=false
```

Rollback means **OFF**. Use **no destructive migration rollback**.

Do not drop multi-agent evidence tables, delete audit records, rewrite legacy rows, or remove correlation columns merely to disable the feature. Persisted historical evidence must remain readable for audit and reproducibility.

After rollback verify:

- scanner persistence continues,
- realtime ingestion continues,
- `/api/v1/ai/latest` remains readable,
- multi-agent public read endpoints may remain available for historical inspection,
- no new multi-agent orchestration starts while globally disabled,
- simulation and legacy analysis data remain intact.

## Verification commands

Backend:

```bash
pytest -q
```

Web production build:

```bash
cd apps/web
npm ci
npm run build
```

The release gate is complete only when both commands succeed on the same branch HEAD and CI reports success for both backend and web jobs.
