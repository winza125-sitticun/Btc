-- Correlate dry-run order intents and paper simulation trades with exactly
-- one analysis source: legacy single-provider analysis or multi-agent run.
-- This migration preserves simulation-only safety and introduces no live-order path.

alter table public.market_order_intents
  add column if not exists multi_agent_run_id uuid references public.ai_multi_agent_runs(id) on delete restrict;

alter table public.market_simulation_trades
  add column if not exists multi_agent_run_id uuid references public.ai_multi_agent_runs(id) on delete restrict;

-- Existing rows are legacy rows and already have ai_analysis_id populated.
-- Relax nullability only after the alternate FK exists.
alter table public.market_order_intents
  alter column ai_analysis_id drop not null;

alter table public.market_simulation_trades
  alter column ai_analysis_id drop not null;

-- Add fail-closed source constraints as NOT VALID first so PostgreSQL can add
-- them without rewriting the tables; validation then proves all existing rows.
alter table public.market_order_intents
  add constraint market_order_intents_analysis_source_xor
  check ((ai_analysis_id is not null) <> (multi_agent_run_id is not null)) not valid;

alter table public.market_order_intents
  validate constraint market_order_intents_analysis_source_xor;

alter table public.market_simulation_trades
  add constraint market_simulation_trades_analysis_source_xor
  check ((ai_analysis_id is not null) <> (multi_agent_run_id is not null)) not valid;

alter table public.market_simulation_trades
  validate constraint market_simulation_trades_analysis_source_xor;

-- A multi-agent run can create at most one paper trade, matching the existing
-- legacy unique(ai_analysis_id) lifecycle guarantee.
create unique index if not exists market_simulation_trades_multi_agent_run_uidx
  on public.market_simulation_trades(multi_agent_run_id)
  where multi_agent_run_id is not null;

create index if not exists market_order_intents_multi_agent_run_idx
  on public.market_order_intents(multi_agent_run_id, created_at desc)
  where multi_agent_run_id is not null;

-- Correlation IDs are safe operational metadata for later sanitized event reads.
grant select (multi_agent_run_id) on public.market_order_intents to anon, authenticated;
grant select (multi_agent_run_id) on public.market_simulation_trades to anon, authenticated;
