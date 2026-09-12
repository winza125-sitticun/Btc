from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "202609120001_multi_agent_vortex.sql"

REQUIRED_TABLES = (
    "ai_multi_agent_configs", "ai_multi_agent_runs", "ai_agent_attempts",
    "ai_consensus_decisions", "ai_hesitation_snapshots", "ai_multi_agent_risk_results",
    "ai_decision_outcomes", "ai_agent_performance_snapshots", "ai_dashboard_events",
)


def _sql() -> str:
    assert MIGRATION.exists(), "multi-agent persistence migration must exist"
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_multi_agent_migration_creates_reproducible_evidence_schema():
    sql = _sql()
    for table in REQUIRED_TABLES:
        assert f"create table if not exists public.{table}" in sql
    for field in (
        "role_prompt_bundle jsonb", "sanitized_config jsonb", "market_context_summary jsonb",
        "prompt_digest text", "role_contributions jsonb", "consensus_algorithm_version text",
        "hesitation_algorithm_version text", "performance_algorithm_version text", "snapshot_ref text",
    ):
        assert field in sql


def test_multi_agent_run_lifecycle_is_guarded_and_finalizes_once():
    sql = _sql()
    assert "status text not null default 'running'" in sql
    assert "status in ('running', 'completed', 'partial', 'insufficient_evidence', 'failed')" in sql
    assert "create or replace function public.guard_ai_multi_agent_run_update" in sql
    assert "old.status <> 'running'" in sql
    assert "new.status not in ('completed', 'partial', 'insufficient_evidence', 'failed')" in sql
    assert "new.completed_at is null" in sql
    assert "immutable multi-agent run fields cannot change" in sql
    assert "create trigger ai_multi_agent_runs_guard_update" in sql
    assert "before update on public.ai_multi_agent_runs" in sql


def test_multi_agent_evidence_is_append_only_and_browser_read_only():
    sql = _sql()
    assert "create or replace function public.reject_ai_multi_agent_evidence_mutation" in sql
    for table in REQUIRED_TABLES:
        assert f"alter table public.{table} enable row level security" in sql
        assert f"revoke all on public.{table} from anon, authenticated" in sql
    assert "grant select on public.ai_multi_agent_configs" not in sql
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql


def test_multi_agent_browser_grants_use_explicit_safe_columns_only():
    sql = _sql()
    for table in REQUIRED_TABLES[1:]:
        assert f"on public.{table} to anon, authenticated" in sql
    grant_lines = "\n".join(line for line in sql.splitlines() if line.strip().startswith("grant select"))
    assert "prompt_text" not in grant_lines
    assert "role_prompt_bundle" not in grant_lines
    assert "sanitized_config" not in grant_lines
