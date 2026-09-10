from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "202609100002_phase_8_9_readiness.sql"
)


def test_phase_8_9_migration_creates_system_owned_strategy_tables():
    assert MIGRATION.exists(), "Phase 8–9 readiness migration must exist"
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    for table_name in (
        "market_ai_signal_outcomes",
        "market_simulation_accounts",
        "market_simulation_trades",
        "market_strategy_metrics",
        "market_strategy_experiments",
        "market_alert_events",
        "market_readiness_checks",
        "market_order_intents",
    ):
        assert f"create table if not exists public.{table_name}" in sql
        assert f"alter table public.{table_name} enable row level security" in sql


def test_phase_8_9_migration_preserves_idempotency_and_dry_run_boundary():
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "unique (ai_analysis_id, horizon)" in sql
    assert "unique (ai_analysis_id)" in sql
    assert "exchange_submission_allowed boolean not null default false" in sql
    assert "check (exchange_submission_allowed = false)" in sql
    assert "mode text not null default 'dry_run' check (mode in ('dry_run'))" in sql
    assert "unique (client_intent_id)" in sql


def test_phase_8_9_migration_has_safety_indexes_and_sanitized_read_grants():
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    for index_name in (
        "market_ai_signal_outcomes_due_idx",
        "market_simulation_trades_active_idx",
        "market_alert_events_recent_idx",
        "market_readiness_checks_latest_idx",
        "market_strategy_metrics_window_idx",
    ):
        assert index_name in sql

    assert "for select to anon, authenticated" in sql
    assert "grant select on public.market_strategy_metrics to anon, authenticated" in sql
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql


def test_phase_8_9_migration_seeds_the_system_canary_account():
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "'production canary'" in sql
    assert "1000" in sql
    assert "on conflict (name) do nothing" in sql
