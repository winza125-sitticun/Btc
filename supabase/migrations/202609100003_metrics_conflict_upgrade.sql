-- Forward-only upgrade for installations that already applied 202609100002.
-- PostgREST on_conflict requires a matching literal-column unique index.
drop index if exists public.market_strategy_metrics_snapshot_key_idx;

update public.market_strategy_metrics
set provider = coalesce(provider, ''),
    model = coalesce(model, ''),
    timeframe = coalesce(timeframe, ''),
    direction = coalesce(direction, ''),
    symbol = coalesce(symbol, '')
where provider is null or model is null or timeframe is null or direction is null or symbol is null;

alter table public.market_strategy_metrics
  alter column provider set default '', alter column provider set not null,
  alter column model set default '', alter column model set not null,
  alter column timeframe set default '', alter column timeframe set not null,
  alter column direction set default '', alter column direction set not null,
  alter column symbol set default '', alter column symbol set not null;

create unique index if not exists market_strategy_metrics_snapshot_key_idx
  on public.market_strategy_metrics(provider, model, timeframe, direction, symbol, rolling_window, window_ended_at);
