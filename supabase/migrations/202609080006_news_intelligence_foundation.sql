alter table public.news_articles
  add column if not exists content_fingerprint text;

create index if not exists news_articles_published_at_idx
  on public.news_articles(published_at desc);

create index if not exists news_articles_fingerprint_published_idx
  on public.news_articles(content_fingerprint, published_at desc);

create index if not exists news_assets_symbol_news_idx
  on public.news_assets(symbol, news_id);
