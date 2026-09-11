# Phase 8–9 production rollout

This rollout extends the existing market canary with isolated, read-only strategy bookkeeping. It remains simulation-only: `LIVE_READY` means readiness checks passed; it does not submit orders.

## Safety defaults

Keep `TRADING_MODE=SIMULATION`, `DIRECT_AI_ORDER_ENABLED=false`, and `LIVE_ORDER_EXECUTION_ENABLED=false`. Strategy stages are disabled by default and are enabled incrementally only after their predecessor is verified. DRY_RUN intents always carry `exchange_submission_allowed=false`.

## Ordered rollout

1. Apply the Phase 8–9 schema migration and verify RLS, grants, indexes, and the canary account.
2. Deploy the isolated strategy worker with all feature flags off; verify scanner health and independent startup.
3. Enable outcomes, then simulation, then reconcile/accounting, validating idempotency after each step.
4. Enable alerts with `ALERT_CHANNELS=IN_APP`, then readiness, then DRY_RUN intents only after paper gates are healthy.
5. Keep live execution disabled. Expand AI candidate limit/concurrency only after the 20-attempt canary gate passes.

Rollback disables strategy feature flags without changing market-worker or realtime ingestion. Never delete production data automatically; stop the strategy worker and investigate failed safety checks.

## Evidence checklist

Record deployment commit and UTC start time, migration/index/RLS checks, scanner and worker cycle evidence, outcome/simulation reconciliation, alert deduplication, readiness state, and DRY_RUN intent counts. Do not record service-role keys, provider credentials, webhook URLs, or raw provider bodies.
