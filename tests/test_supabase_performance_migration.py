from pathlib import Path


MIGRATION = Path("supabase/migrations/202609080005_performance_hardening.sql")


def test_performance_hardening_migration_covers_advisor_findings():
    assert MIGRATION.exists(), "performance hardening migration must exist"

    sql = MIGRATION.read_text(encoding="utf-8").lower()

    required_indexes = (
        "ai_decisions_scanner_candidate_idx",
        "risk_decisions_ai_decision_idx",
        "risk_decisions_user_idx",
        "scanner_runs_user_idx",
        "simulation_positions_account_idx",
    )
    for index_name in required_indexes:
        assert f"create index if not exists {index_name}" in sql

    policy_names = (
        "profiles own row",
        "trading settings own row",
        "ai configs own rows",
        "scanner runs own rows",
        "ai decisions own rows",
        "risk decisions own rows",
        "simulation accounts own rows",
        "simulation positions own rows",
    )
    for policy_name in policy_names:
        assert f'drop policy if exists "{policy_name}"' in sql

    assert sql.count("(select auth.uid())") >= 16
