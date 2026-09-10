-- AI Analysis V1: system-wide, sanitized analysis linked to the live market scanner.
-- Browser roles are read-only; service-role writes bypass RLS server-side.

create table if not exists public.market_ai_analyses (
  id bigint generated always as identity primary key,
  scanner_candidate_id bigint not null references public.market_scanner_candidates(id) on delete cascade,
  run_id uuid not null references public.market_scanner_runs(id) on delete cascade,
  symbol text not null,
  timeframe text not null,
  provider public.ai_provider not null,
  model text not null,
  scanner_direction public.trade_direction not null,
  ai_direction public.trade_direction,
  confidence numeric(5,2) check (confidence between 0 and 100),
  entry_min numeric check (entry_min is null or entry_min > 0),
  entry_max numeric check (entry_max is null or entry_max > 0),
  stop_loss numeric check (stop_loss is null or stop_loss > 0),
  take_profits jsonb not null default '[]'::jsonb,
  risk_reward numeric check (risk_reward is null or risk_reward > 0),
  reason_summary text,
  input_snapshot jsonb not null default '{}'::jsonb,
  status text not null check (status in ('SUCCESS','SKIPPED','FAILED','INVALID_RESPONSE')),
  risk_precheck_status text,
  risk_precheck_reasons text[] not null default '{}',
  latency_ms integer check (latency_ms is null or latency_ms >= 0),
  attempt_count integer not null default 0 check (attempt_count >= 0),
  error_code text,
  error_message text,
  created_at timestamptz not null default now(),
  completed_at timestamptz,
  unique (scanner_candidate_id, provider, model)
);

create index if not exists market_ai_analyses_timeframe_created_idx
  on public.market_ai_analyses(timeframe, created_at desc);
create index if not exists market_ai_analyses_candidate_idx
  on public.market_ai_analyses(scanner_candidate_id);
create index if not exists market_ai_analyses_run_idx
  on public.market_ai_analyses(run_id);

alter table public.market_ai_analyses enable row level security;

drop policy if exists "public market ai analyses readable" on public.market_ai_analyses;
create policy "public market ai analyses readable"
  on public.market_ai_analyses for select to anon, authenticated using (true);

revoke all on public.market_ai_analyses from anon, authenticated;
grant select on public.market_ai_analyses to anon, authenticated;
