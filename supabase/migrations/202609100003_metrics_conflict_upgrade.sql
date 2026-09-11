-- Forward-only upgrade for installations that already applied 202609100002.
-- PostgREST on_conflict requires a matching literal-column unique index.
drop index if exists public.market_strategy_metrics_snapshot_key_idx;

create unique index if not exists market_strategy_metrics_snapshot_key_idx
  on public.market_strategy_metrics(provider, model, timeframe, direction, symbol, rolling_window, window_ended_at);
