from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "supabase"
    / "migrations"
    / "202609100001_market_ai_analysis_v1.sql"
)


def test_market_ai_analysis_migration_links_live_candidates_and_is_read_only_for_clients():
    assert MIGRATION.exists(), "AI Analysis V1 migration must exist"
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "references public.market_scanner_candidates(id)" in sql
    assert "unique(scanner_candidate_id, provider, model)" in sql.replace(" ", "") or (
        "unique (scanner_candidate_id, provider, model)" in sql
    )
    assert "alter table public.market_ai_analyses enable row level security" in sql
    assert "for select to anon, authenticated" in sql
    assert "grant select on public.market_ai_analyses to anon, authenticated" in sql
    assert "grant insert" not in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql
    assert "status in ('success','skipped','failed','invalid_response')" in sql


def test_market_ai_analysis_migration_has_lookup_indexes():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    assert "market_ai_analyses_timeframe_created_idx" in sql
    assert "market_ai_analyses_candidate_idx" in sql
    assert "market_ai_analyses_run_idx" in sql
