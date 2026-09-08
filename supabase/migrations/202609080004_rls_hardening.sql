-- Security hardening for public-schema tables exposed through PostgREST.
-- Fail closed: enable RLS without adding client read/write policies.

alter table public.market_candles enable row level security;
alter table public.derivatives_metrics enable row level security;
alter table public.news_articles enable row level security;
alter table public.news_assets enable row level security;
alter table public.macro_events enable row level security;
alter table public.scanner_candidates enable row level security;
