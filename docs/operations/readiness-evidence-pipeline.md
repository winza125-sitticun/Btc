# Strategy Readiness Evidence Pipeline

## Purpose

The strategy worker must be able to evaluate and persist readiness without an externally injected evidence callback. Missing or unreadable operational evidence must fail closed as `NOT_READY` rather than aborting the readiness stage.

## Production contract

`ReadinessEvidenceRepository` collects only bounded, sanitized operational fields from Supabase. It does not select raw AI responses, prompt text, reason summaries, API keys, credentials, authorization headers, or other secret-bearing payloads.

The collector currently derives only evidence that can be supported directly by persisted operational rows:

- multi-agent attempt count, success rate, invalid-schema rate, and p95 latency;
- scanner completion/failure health;
- Production Canary simulation-account health;
- presence of persisted alert evidence;
- order-intent integrity (`DRY_RUN` only and `exchange_submission_allowed=false`).

The following checks remain conservative until they have a separately verifiable source:

- `migrations_rls_healthy=false` — service-role PostgREST access does not prove RLS policy correctness;
- `full_risk_enabled=false` — SHADOW/precheck risk rows do not prove full account-context risk is enabled;
- `exchange_eligibility_blocked=true`;
- `private_credentials_configured=false`.

Therefore this change cannot promote readiness by itself. Its purpose is to replace a missing-evidence exception with an immutable, auditable, fail-closed readiness snapshot.

## Rollout safety

For the first production strategy-worker rollout, use readiness-only mode:

- `STRATEGY_WORKER_ENABLED=true`
- `READINESS_V1_ENABLED=true`
- `OUTCOME_EVALUATION_ENABLED=false`
- `SIMULATION_ENGINE_ENABLED=false`
- `ALERTS_V1_ENABLED=false`
- `ORDER_INTENT_DRY_RUN_ENABLED=false`
- `LIVE_ORDER_EXECUTION_ENABLED=false`
- Multi-Agent remains `SHADOW`

Do not enable PRIMARY or any exchange execution path as part of this rollout.
