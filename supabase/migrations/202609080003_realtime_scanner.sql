-- System-wide realtime market state and scanner snapshots.
-- Market data is public; writes are reserved for the server-side service role.

alter table public.market_candles
  add column if not exists close_time timestamptz;

create table if not exists public.market_live_state (
  symbol text primary key,
  mark_price numeric,
  index_price numeric,
  funding_rate numeric,
  best_bid numeric,
  best_ask numeric,
  spread_percent numeric,
  candle_timeframe text,
  candle_open numeric,
  candle_high numeric,
  candle_low numeric,
  candle_close numeric,
  candle_volume numeric,
  event_time timestamptz,
  updated_at timestamptz not null default now()
);
create index if not exists market_live_state_updated_idx
  on public.market_live_state(updated_at desc);

create table if not exists public.market_scanner_runs (
  id uuid primary key default gen_random_uuid(),
  timeframe text not null,
  universe_size integer not null check (universe_size >= 0),
  candidate_count integer not null default 0 check (candidate_count >= 0),
  failure_count integer not null default 0 check (failure_count >= 0),
  source text not null default 'BINANCE_USDM',
  started_at timestamptz not null default now(),
  completed_at timestamptz
);
create index if not exists market_scanner_runs_latest_idx
  on public.market_scanner_runs(timeframe, completed_at desc);

create table if not exists public.market_scanner_candidates (
  id bigint generated always as identity primary key,
  run_id uuid not null references public.market_scanner_runs(id) on delete cascade,
  rank integer not null check (rank >= 1),
  symbol text not null,
  timeframe text not null,
  direction public.trade_direction not null,
  opportunity_score numeric(6,3) not null check (opportunity_score between 0 and 100),
  directional_signal numeric(7,6) not null check (directional_signal between -1 and 1),
  technical_score numeric(6,3) not null,
  momentum_score numeric(6,3) not null,
  volume_score numeric(6,3) not null,
  orderflow_score numeric(6,3) not null,
  oi_score numeric(6,3) not null,
  funding_score numeric(6,3) not null,
  liquidity_score numeric(6,3) not null,
  news_score numeric(6,3) not null,
  macro_score numeric(6,3) not null,
  rr_score numeric(6,3) not null,
  last_price numeric not null,
  quote_volume_24h numeric not null default 0,
  funding_rate numeric,
  open_interest_change_percent numeric,
  long_short_ratio numeric,
  spread_percent numeric,
  created_at timestamptz not null default now(),
  unique(run_id, symbol)
);
create index if not exists market_scanner_candidates_rank_idx
  on public.market_scanner_candidates(run_id, rank, opportunity_score desc);

alter table public.market_live_state enable row level security;
alter table public.market_scanner_runs enable row level security;
alter table public.market_scanner_candidates enable row level security;

create policy "public market live state readable"
  on public.market_live_state for select to anon, authenticated using (true);
create policy "public scanner runs readable"
  on public.market_scanner_runs for select to anon, authenticated using (true);
create policy "public scanner candidates readable"
  on public.market_scanner_candidates for select to anon, authenticated using (true);

grant select on public.market_live_state to anon, authenticated;
grant select on public.market_scanner_runs to anon, authenticated;
grant select on public.market_scanner_candidates to anon, authenticated;
