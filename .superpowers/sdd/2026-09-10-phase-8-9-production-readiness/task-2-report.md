# Task 2 report — Phase 8–9 strategy data schema

## Result

Added the Phase 8–9 system-owned strategy schema as a migration. It supports
signal outcomes, the Production Canary paper ledger, simulated trades,
aggregate metrics, experiment records, material alerts, immutable readiness
snapshots, and dry-run order intents. The schema cannot record an intent that
permits exchange submission.

No production Supabase project, service, secret, or live-trading capability was
touched.

## Files changed

- `supabase/migrations/202609100002_phase_8_9_readiness.sql`
  - creates the eight required system-owned market tables;
  - enables RLS on every table;
  - revokes client write privileges and grants only sanitized operational
    `SELECT` access where it is needed;
  - adds outcome, simulated-trade, active-alert, and order-intent idempotency
    constraints and operational indexes;
  - constrains `market_order_intents` to `DRY_RUN` and
    `exchange_submission_allowed = false`;
  - seeds the `Production Canary` account with a 1000 USDT starting balance.
- `tests/test_phase_8_9_migration.py`
  - repository-level migration contract for tables, RLS, indexes, read-only
    client grants, idempotency, the dry-run boundary, and the canary seed.

## TDD evidence

The contract test was created while the migration was absent. Using the bundled
workspace Python runtime, the RED run failed with the expected missing-migration
assertion:

```powershell
& 'C:\Users\q739\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests/test_phase_8_9_migration.py
```

RED output: `4 failed`, beginning with
`AssertionError: Phase 8–9 readiness migration must exist`.

After adding the minimum migration, focused verification was:

```powershell
& 'C:\Users\q739\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest -q tests/test_phase_8_9_migration.py tests/test_ai_migration.py tests/test_news_migration.py
```

GREEN output: `7 passed in 0.13s`.

An additional PowerShell static contract check confirmed the required table,
RLS, index, idempotency, dry-run, grant, and canary-seed SQL fragments.

## SHA

- Task starting SHA: `80f717c57d1fee05ab048be93f992049d79893cc`
- Task commit: recorded in Git history immediately after this report is added.

## Concerns / follow-up

- This migration is intentionally un-applied. Production deployment and RLS
  runtime verification belong to the separately authorized rollout stage.
- Public-table Data API exposure may require an explicit project-level opt-in
  in newer Supabase projects. The migration still enforces RLS and grants at
  the database layer, and does not grant browser writes.
- `market_strategy_experiments` is service-role-only: it has RLS and no
  client-read policy because proposed configuration changes should not become a
  public operational surface.
