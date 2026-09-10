-- Phase 8–9: system-owned outcome, simulation, readiness, and dry-run data.
-- These tables deliberately contain only sanitized operational information.

create table if not exists public.market_ai_signal_outcomes (
  id bigint generated always as identity primary key,
  ai_analysis_id bigint not null references public.market_ai_analyses(id) on delete cascade,
  scanner_candidate_id bigint not null references public.market_scanner_candidates(id) on delete cascade,
  symbol text not null,
  timeframe text not null,
  direction text not null check (direction in ('LONG', 'SHORT', 'WAIT', 'EXIT')),
  horizon text not null check (horizon in ('1H', '4H', '24H')),
  signal_created_at timestamptz not null,
  evaluation_due_at timestamptz not null,
  entry_reference numeric check (entry_reference is null or entry_reference > 0),
  entry_touched boolean,
  stop_touched boolean,
  highest_tp_hit integer not null default 0 check (highest_tp_hit between 0 and 3),
  mfe_percent numeric,
  mae_percent numeric,
  final_return_percent numeric,
  outcome text not null default 'PENDING' check (outcome in ('PENDING', 'WIN', 'LOSS', 'NEUTRAL', 'NO_FILL', 'INVALIDATED')),
  data_quality text not null default 'MISSING' check (data_quality in ('FULL', 'PARTIAL', 'MISSING')),
  evaluated_at timestamptz,
  created_at timestamptz not null default now(),
  unique (ai_analysis_id, horizon)
);

create index if not exists market_ai_signal_outcomes_due_idx
  on public.market_ai_signal_outcomes(evaluation_due_at)
  where outcome = 'PENDING';

create table if not exists public.market_simulation_accounts (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  currency text not null default 'USDT' check (currency = 'USDT'),
  starting_balance numeric not null check (starting_balance > 0),
  balance numeric not null check (balance >= 0),
  equity numeric not null check (equity >= 0),
  realized_pnl numeric not null default 0,
  max_equity numeric not null check (max_equity >= 0),
  max_drawdown_percent numeric not null default 0 check (max_drawdown_percent >= 0),
  daily_realized_loss numeric not null default 0,
  trading_date date not null default current_date,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.market_simulation_trades (
  id bigint generated always as identity primary key,
  account_id uuid not null references public.market_simulation_accounts(id) on delete restrict,
  ai_analysis_id bigint not null references public.market_ai_analyses(id) on delete restrict,
  scanner_candidate_id bigint references public.market_scanner_candidates(id) on delete set null,
  symbol text not null,
  side text not null check (side in ('LONG', 'SHORT')),
  status text not null default 'PENDING_ENTRY' check (status in ('PENDING_ENTRY', 'OPEN', 'TP_EXIT', 'SL_EXIT', 'EXPIRED', 'CLOSED')),
  planned_entry_min numeric not null check (planned_entry_min > 0),
  planned_entry_max numeric not null check (planned_entry_max > 0 and planned_entry_max >= planned_entry_min),
  simulated_entry_price numeric check (simulated_entry_price is null or simulated_entry_price > 0),
  quantity numeric not null check (quantity > 0),
  leverage numeric not null check (leverage > 0 and leverage <= 5),
  risk_amount numeric not null check (risk_amount > 0),
  stop_loss numeric not null check (stop_loss > 0),
  take_profits jsonb not null default '[]'::jsonb,
  highest_tp_reached integer not null default 0 check (highest_tp_reached between 0 and 3),
  fees_paid numeric not null default 0,
  slippage_cost numeric not null default 0,
  funding_paid numeric not null default 0,
  funding_quality text not null default 'MISSING' check (funding_quality in ('FULL', 'PARTIAL', 'MISSING')),
  realized_pnl numeric not null default 0,
  realized_return_percent numeric,
  opened_at timestamptz,
  closed_at timestamptz,
  expires_at timestamptz not null,
  exit_reason text,
  full_risk_approved boolean not null default false,
  full_risk_reasons text[] not null default '{}',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (ai_analysis_id)
);

create index if not exists market_simulation_trades_active_idx
  on public.market_simulation_trades(account_id, status, created_at desc)
  where status in ('PENDING_ENTRY', 'OPEN', 'TP_EXIT', 'SL_EXIT');

create table if not exists public.market_strategy_metrics (
  id bigint generated always as identity primary key,
  provider text,
  model text,
  timeframe text,
  direction text check (direction is null or direction in ('LONG', 'SHORT', 'WAIT', 'EXIT')),
  symbol text,
  rolling_window text not null check (rolling_window in ('24H', '7D', '30D', 'ALL')),
  window_started_at timestamptz,
  window_ended_at timestamptz not null,
  analysis_count integer not null default 0 check (analysis_count >= 0),
  eligible_signal_count integer not null default 0 check (eligible_signal_count >= 0),
  simulated_trade_count integer not null default 0 check (simulated_trade_count >= 0),
  no_fill_count integer not null default 0 check (no_fill_count >= 0),
  win_count integer not null default 0 check (win_count >= 0),
  loss_count integer not null default 0 check (loss_count >= 0),
  win_rate numeric,
  average_net_return numeric,
  median_net_return numeric,
  expectancy numeric,
  profit_factor numeric,
  max_drawdown_percent numeric,
  average_mfe_percent numeric,
  average_mae_percent numeric,
  tp1_hit_rate numeric,
  tp2_hit_rate numeric,
  tp3_hit_rate numeric,
  sl_hit_rate numeric,
  provider_success_rate numeric,
  median_latency_ms numeric,
  p95_latency_ms numeric,
  full_data_count integer not null default 0 check (full_data_count >= 0),
  partial_data_count integer not null default 0 check (partial_data_count >= 0),
  created_at timestamptz not null default now()
);

create index if not exists market_strategy_metrics_window_idx
  on public.market_strategy_metrics(rolling_window, window_ended_at desc, provider, model, timeframe);

create table if not exists public.market_strategy_experiments (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  description text not null,
  baseline_identifier text not null,
  variant_configuration jsonb not null default '{}'::jsonb,
  status text not null default 'DRAFT' check (status in ('DRAFT', 'SIMULATION', 'PROMOTABLE', 'REJECTED', 'ARCHIVED')),
  started_at timestamptz,
  ended_at timestamptz,
  sample_count integer not null default 0 check (sample_count >= 0),
  metric_deltas jsonb not null default '{}'::jsonb,
  decision_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.market_alert_events (
  id bigint generated always as identity primary key,
  alert_type text not null check (alert_type in ('TRADE_SETUP_READY', 'STRUCTURE_CHANGE', 'HIGH_IMPACT_NEWS', 'RISK_BLOCK', 'PROVIDER_DEGRADED', 'READINESS_CHANGED')),
  severity text not null check (severity in ('INFO', 'WARNING', 'CRITICAL')),
  symbol text,
  ai_analysis_id bigint references public.market_ai_analyses(id) on delete set null,
  scanner_run_id uuid references public.market_scanner_runs(id) on delete set null,
  title text not null,
  short_summary text not null,
  dedupe_key text not null,
  payload jsonb not null default '{}'::jsonb,
  first_observed_at timestamptz not null default now(),
  last_observed_at timestamptz not null default now(),
  status text not null default 'NEW' check (status in ('NEW', 'ACKNOWLEDGED', 'EXPIRED')),
  delivery_state jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists market_alert_events_active_dedupe_key_idx
  on public.market_alert_events(dedupe_key)
  where status in ('NEW', 'ACKNOWLEDGED');
create index if not exists market_alert_events_recent_idx
  on public.market_alert_events(created_at desc, severity, status);

create table if not exists public.market_readiness_checks (
  id bigint generated always as identity primary key,
  overall_status text not null check (overall_status in ('NOT_READY', 'PAPER_READY', 'LIVE_READY', 'BLOCKED')),
  mandatory_checks jsonb not null default '{}'::jsonb,
  evidence_window jsonb not null default '{}'::jsonb,
  metrics_snapshot jsonb not null default '{}'::jsonb,
  blocking_reasons text[] not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists market_readiness_checks_latest_idx
  on public.market_readiness_checks(created_at desc);

create table if not exists public.market_order_intents (
  id bigint generated always as identity primary key,
  simulation_trade_id bigint references public.market_simulation_trades(id) on delete set null,
  ai_analysis_id bigint not null references public.market_ai_analyses(id) on delete restrict,
  mode text not null default 'DRY_RUN' check (mode in ('DRY_RUN')),
  symbol text not null,
  side text not null check (side in ('LONG', 'SHORT')),
  quantity numeric not null check (quantity > 0),
  leverage numeric not null check (leverage > 0 and leverage <= 5),
  entry_type text not null check (entry_type in ('MARKET', 'LIMIT')),
  entry_price numeric check (entry_price is null or entry_price > 0),
  stop_loss numeric not null check (stop_loss > 0),
  take_profit_instructions jsonb not null default '[]'::jsonb,
  risk_decision_snapshot jsonb not null default '{}'::jsonb,
  client_intent_id text not null,
  idempotency_key text not null,
  validation_status text not null check (validation_status in ('PENDING', 'VALID', 'REJECTED')),
  rejection_reasons text[] not null default '{}',
  exchange_submission_allowed boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (client_intent_id),
  unique (idempotency_key),
  check (exchange_submission_allowed = false)
);

alter table public.market_ai_signal_outcomes enable row level security;
alter table public.market_simulation_accounts enable row level security;
alter table public.market_simulation_trades enable row level security;
alter table public.market_strategy_metrics enable row level security;
alter table public.market_strategy_experiments enable row level security;
alter table public.market_alert_events enable row level security;
alter table public.market_readiness_checks enable row level security;
alter table public.market_order_intents enable row level security;

-- Browser roles are intentionally read-only. Service-role writes bypass RLS.
create policy "public market signal outcomes readable"
  on public.market_ai_signal_outcomes for select to anon, authenticated using (true);
create policy "public market simulation accounts readable"
  on public.market_simulation_accounts for select to anon, authenticated using (true);
create policy "public market simulation trades readable"
  on public.market_simulation_trades for select to anon, authenticated using (true);
create policy "public market strategy metrics readable"
  on public.market_strategy_metrics for select to anon, authenticated using (true);
create policy "public market alert events readable"
  on public.market_alert_events for select to anon, authenticated using (true);
create policy "public market readiness checks readable"
  on public.market_readiness_checks for select to anon, authenticated using (true);
create policy "public market order intents readable"
  on public.market_order_intents for select to anon, authenticated using (true);

revoke all on public.market_ai_signal_outcomes from anon, authenticated;
revoke all on public.market_simulation_accounts from anon, authenticated;
revoke all on public.market_simulation_trades from anon, authenticated;
revoke all on public.market_strategy_metrics from anon, authenticated;
revoke all on public.market_strategy_experiments from anon, authenticated;
revoke all on public.market_alert_events from anon, authenticated;
revoke all on public.market_readiness_checks from anon, authenticated;
revoke all on public.market_order_intents from anon, authenticated;
grant select on public.market_ai_signal_outcomes to anon, authenticated;
grant select on public.market_simulation_accounts to anon, authenticated;
grant select on public.market_simulation_trades to anon, authenticated;
grant select on public.market_strategy_metrics to anon, authenticated;
grant select on public.market_alert_events to anon, authenticated;
grant select on public.market_readiness_checks to anon, authenticated;
grant select on public.market_order_intents to anon, authenticated;

insert into public.market_simulation_accounts (
  name, currency, starting_balance, balance, equity, realized_pnl, max_equity, max_drawdown_percent, daily_realized_loss
) values (
  'Production Canary', 'USDT', 1000, 1000, 1000, 0, 1000, 0, 0
) on conflict (name) do nothing;
