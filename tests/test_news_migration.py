from pathlib import Path


MIGRATION = Path("supabase/migrations/202609080006_news_intelligence_foundation.sql")


def test_news_migration_is_minimal_and_fail_closed():
    assert MIGRATION.exists(), "news intelligence migration must exist"
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "add column if not exists content_fingerprint text" in sql
    assert "create index if not exists news_articles_published_at_idx" in sql
    assert "create index if not exists news_articles_fingerprint_published_idx" in sql
    assert "create index if not exists news_assets_symbol_news_idx" in sql
    assert "create policy" not in sql
    assert "disable row level security" not in sql
    assert "grant " not in sql
