create extension if not exists pgcrypto;

create type public.trading_mode as enum ('SIMULATION', 'TESTNET', 'LIVE');
create type public.ai_provider as enum ('GEMINI', 'CLAUDE', 'OPENAI_COMPATIBLE', 'DEEPSEEK', 'OPENROUTER');
create type public.trade_direction as enum ('LONG', 'SHORT', 'WAIT', 'EXIT');

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  timezone text not null default 'Asia/Bangkok',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.trading_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  trading_mode public.trading_mode not null default 'SIMULATION',
  direct_ai_order_enabled boolean not null default false,
  min_confidence numeric(5,2) not null default 75 check (min_confidence between 0 and 100),
  min_opportunity_score numeric(5,2) not null default 75 check (min_opportunity_score between 0 and 100),
  min_risk_reward numeric(8,3) not null default 2.0 check (min_risk_reward > 0),
  max_leverage numeric(8,3) not null default 5.0 check (max_leverage > 0),
  max_risk_percent numeric(5,2) not null default 1.0 check (max_risk_percent > 0),
  max_daily_loss_percent numeric(5,2) not null default 3.0 check (max_daily_loss_percent > 0),
  max_open_positions integer not null default 3 check (max_open_positions > 0),
  event_guard_before_minutes integer not null default 30 check (event_guard_before_minutes >= 0),
  event_guard_after_minutes integer not null default 15 check (event_guard_after_minutes >= 0),
  updated_at timestamptz not null default now()
);

create table public.ai_provider_configs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  provider public.ai_provider not null,
  model text not null,
  base_url text,
  secret_ref text,
  enabled boolean not null default true,
  is_primary boolean not null default false,
  role_trend boolean not null default true,
  role_news boolean not null default true,
  role_market boolean not null default true,
  role_signal boolean not null default true,
  role_entry boolean not null default true,
  role_sl_tp boolean not null default true,
  weight numeric(6,3) not null default 1.0 check (weight >= 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id, provider, model)
);

create table public.market_candles (
  symbol text not null,
  timeframe text not null,
  open_time timestamptz not null,
  open numeric not null,
  high numeric not null,
  low numeric not null,
  close numeric not null,
  volume numeric not null,
  quote_volume numeric,
  trade_count bigint,
  primary key(symbol, timeframe, open_time)
);
create index market_candles_lookup_idx on public.market_candles(symbol, timeframe, open_time desc);

create table public.derivatives_metrics (
  id bigint generated always as identity primary key,
  symbol text not null,
  observed_at timestamptz not null,
  mark_price numeric,
  index_price numeric,
  funding_rate numeric,
  open_interest numeric,
  open_interest_value numeric,
  long_short_ratio numeric,
  taker_buy_volume numeric,
  taker_sell_volume numeric,
  orderbook_imbalance numeric,
  spread_percent numeric
);
create index derivatives_metrics_lookup_idx on public.derivatives_metrics(symbol, observed_at desc);

create table public.news_articles (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  source_url text not null unique,
  title text not null,
  summary text,
  published_at timestamptz not null,
  sentiment numeric(6,3),
  impact_level text check (impact_level in ('LOW', 'MEDIUM', 'HIGH')),
  credibility_score numeric(5,2) check (credibility_score between 0 and 100),
  raw_data jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.news_assets (
  news_id uuid not null references public.news_articles(id) on delete cascade,
  symbol text not null,
  primary key(news_id, symbol)
);

create table public.macro_events (
  id uuid primary key default gen_random_uuid(),
  event_name text not null,
  country text,
  scheduled_at timestamptz not null,
  importance text not null check (importance in ('LOW', 'MEDIUM', 'HIGH')),
  forecast text,
  previous text,
  actual text,
  status text not null default 'SCHEDULED',
  created_at timestamptz not null default now()
);
create index macro_events_schedule_idx on public.macro_events(scheduled_at);

create table public.scanner_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  timeframe text not null,
  universe_size integer not null check (universe_size >= 0),
  started_at timestamptz not null default now(),
  completed_at timestamptz
);

create table public.scanner_candidates (
  id uuid primary key default gen_random_uuid(),
  scanner_run_id uuid not null references public.scanner_runs(id) on delete cascade,
  symbol text not null,
  direction public.trade_direction not null,
  technical_score numeric(5,2) not null,
  momentum_score numeric(5,2) not null,
  volume_score numeric(5,2) not null,
  orderflow_score numeric(5,2) not null,
  oi_score numeric(5,2) not null,
  funding_score numeric(5,2) not null,
  liquidity_score numeric(5,2) not null,
  news_score numeric(5,2) not null,
  macro_score numeric(5,2) not null,
  rr_score numeric(5,2) not null,
  opportunity_score numeric(5,2) not null,
  rank integer,
  created_at timestamptz not null default now()
);
create index scanner_candidates_rank_idx on public.scanner_candidates(scanner_run_id, rank, opportunity_score desc);

create table public.ai_decisions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  scanner_candidate_id uuid references public.scanner_candidates(id) on delete set null,
  symbol text not null,
  timeframe text not null,
  provider public.ai_provider not null,
  model text not null,
  direction public.trade_direction not null,
  confidence numeric(5,2) not null check (confidence between 0 and 100),
  entry_min numeric,
  entry_max numeric,
  stop_loss numeric,
  take_profits jsonb not null default '[]'::jsonb,
  risk_reward numeric,
  reason_summary text,
  input_snapshot jsonb not null default '{}'::jsonb,
  latency_ms integer,
  created_at timestamptz not null default now()
);
create index ai_decisions_user_created_idx on public.ai_decisions(user_id, created_at desc);

create table public.risk_decisions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  ai_decision_id uuid not null references public.ai_decisions(id) on delete cascade,
  approved boolean not null,
  reject_reasons text[] not null default '{}',
  risk_percent numeric,
  position_size numeric,
  leverage numeric,
  expected_loss numeric,
  expected_profit numeric,
  risk_reward numeric,
  created_at timestamptz not null default now()
);

create table public.simulation_accounts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null default 'Default Simulation',
  starting_balance numeric not null default 1000 check (starting_balance > 0),
  balance numeric not null default 1000,
  equity numeric not null default 1000,
  realized_pnl numeric not null default 0,
  max_drawdown numeric not null default 0,
  created_at timestamptz not null default now(),
  unique(user_id, name)
);

create table public.simulation_positions (
  id uuid primary key default gen_random_uuid(),
  account_id uuid not null references public.simulation_accounts(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null,
  side text not null check (side in ('LONG', 'SHORT')),
  entry_price numeric not null check (entry_price > 0),
  quantity numeric not null check (quantity > 0),
  leverage numeric not null check (leverage > 0),
  stop_loss numeric,
  take_profits jsonb not null default '[]'::jsonb,
  fees_paid numeric not null default 0,
  funding_paid numeric not null default 0,
  slippage_cost numeric not null default 0,
  realized_pnl numeric not null default 0,
  status text not null default 'OPEN' check (status in ('OPEN', 'CLOSED')),
  opened_at timestamptz not null default now(),
  closed_at timestamptz
);
create index simulation_positions_user_status_idx on public.simulation_positions(user_id, status, opened_at desc);

alter table public.profiles enable row level security;
alter table public.trading_settings enable row level security;
alter table public.ai_provider_configs enable row level security;
alter table public.scanner_runs enable row level security;
alter table public.ai_decisions enable row level security;
alter table public.risk_decisions enable row level security;
alter table public.simulation_accounts enable row level security;
alter table public.simulation_positions enable row level security;

create policy "profiles own row" on public.profiles for all using (auth.uid() = id) with check (auth.uid() = id);
create policy "trading settings own row" on public.trading_settings for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "ai configs own rows" on public.ai_provider_configs for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "scanner runs own rows" on public.scanner_runs for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "ai decisions own rows" on public.ai_decisions for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "risk decisions own rows" on public.risk_decisions for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "simulation accounts own rows" on public.simulation_accounts for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "simulation positions own rows" on public.simulation_positions for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
