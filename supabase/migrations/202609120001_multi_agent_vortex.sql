-- Multi-Agent Trading Intelligence persistence and immutable audit evidence.
-- Service-role writes only; browser roles receive explicit safe read columns.

create table if not exists public.ai_multi_agent_configs (
  config_version text primary key,
  sanitized_config jsonb not null,
  role_prompt_bundle jsonb not null,
  decision_contract_version text not null,
  consensus_algorithm_version text not null,
  hesitation_algorithm_version text not null,
  performance_algorithm_version text not null,
  market_context_mapping_version text not null,
  created_at timestamptz not null default now()
);

create table if not exists public.ai_multi_agent_runs (
  id uuid primary key default gen_random_uuid(),
  scanner_candidate_id bigint not null references public.market_scanner_candidates(id) on delete restrict,
  scanner_run_id uuid not null references public.market_scanner_runs(id) on delete restrict,
  symbol text not null,
  timeframe text not null,
  started_at timestamptz not null,
  completed_at timestamptz,
  status text not null default 'RUNNING' check (status in ('RUNNING', 'COMPLETED', 'PARTIAL', 'INSUFFICIENT_EVIDENCE', 'FAILED')),
  snapshot_ref text not null,
  snapshot_observed_at timestamptz not null,
  config_version text not null references public.ai_multi_agent_configs(config_version) on delete restrict,
  enabled_role_count integer not null check (enabled_role_count between 0 and 6),
  valid_role_count integer not null default 0 check (valid_role_count between 0 and 6 and valid_role_count <= enabled_role_count),
  rollout_mode text not null check (rollout_mode in ('OFF', 'SHADOW', 'PRIMARY')),
  market_context_summary jsonb not null,
  legacy_analysis_ref bigint references public.market_ai_analyses(id) on delete set null
);
create index if not exists ai_multi_agent_runs_candidate_idx on public.ai_multi_agent_runs(scanner_candidate_id, started_at desc);
create index if not exists ai_multi_agent_runs_latest_idx on public.ai_multi_agent_runs(timeframe, started_at desc);
create index if not exists ai_multi_agent_runs_config_idx on public.ai_multi_agent_runs(config_version, started_at desc);

create table if not exists public.ai_agent_attempts (
  id bigint generated always as identity primary key,
  multi_agent_run_id uuid not null references public.ai_multi_agent_runs(id) on delete restrict,
  role text not null check (role in ('TECHNICAL', 'MOMENTUM', 'ORDER_FLOW', 'NEWS', 'CONTRARIAN', 'RISK_REVIEW')),
  provider text not null,
  model text not null,
  prompt_version text not null,
  prompt_digest text not null,
  status text not null check (status in ('SUCCESS', 'FAILED', 'INVALID_RESPONSE', 'SKIPPED')),
  direction text check (direction is null or direction in ('LONG', 'SHORT', 'WAIT', 'EXIT')),
  confidence numeric(9,6) check (confidence is null or confidence between 0 and 100),
  entry_min numeric check (entry_min is null or entry_min > 0),
  entry_max numeric check (entry_max is null or entry_max > 0),
  stop_loss numeric check (stop_loss is null or stop_loss > 0),
  take_profits jsonb not null default '[]'::jsonb,
  risk_reward numeric check (risk_reward is null or risk_reward > 0),
  reason_summary text,
  latency_ms integer check (latency_ms is null or latency_ms >= 0),
  error_code text,
  error_message text,
  snapshot_ref text not null,
  created_at timestamptz not null default now(),
  unique (multi_agent_run_id, role),
  check (entry_min is null or entry_max is null or entry_max >= entry_min)
);
create index if not exists ai_agent_attempts_run_idx on public.ai_agent_attempts(multi_agent_run_id, id);

create table if not exists public.ai_consensus_decisions (
  id bigint generated always as identity primary key,
  multi_agent_run_id uuid not null references public.ai_multi_agent_runs(id) on delete restrict,
  direction text not null check (direction in ('LONG', 'SHORT', 'WAIT', 'EXIT')),
  consensus_confidence numeric(9,6) not null check (consensus_confidence between 0 and 100),
  winning_agreement numeric(9,6) not null check (winning_agreement between 0 and 1),
  coverage numeric(9,6) not null check (coverage between 0 and 1),
  signed_score numeric(9,6) not null check (signed_score between -1 and 1),
  actionable boolean not null,
  supporting_roles text[] not null default '{}',
  opposing_roles text[] not null default '{}',
  reason_codes text[] not null default '{}',
  role_contributions jsonb not null,
  config_version text not null references public.ai_multi_agent_configs(config_version) on delete restrict,
  consensus_algorithm_version text not null,
  created_at timestamptz not null default now()
);
create index if not exists ai_consensus_decisions_run_idx on public.ai_consensus_decisions(multi_agent_run_id, id);

create table if not exists public.ai_hesitation_snapshots (
  id bigint generated always as identity primary key,
  multi_agent_run_id uuid not null references public.ai_multi_agent_runs(id) on delete restrict,
  consensus_id bigint not null references public.ai_consensus_decisions(id) on delete restrict,
  total numeric(9,6) not null check (total between 0 and 100),
  disagreement numeric(9,6) not null check (disagreement between 0 and 1),
  confidence_dispersion numeric(9,6) not null check (confidence_dispersion between 0 and 1),
  timeframe_conflict numeric(9,6) not null check (timeframe_conflict between 0 and 1),
  market_uncertainty numeric(9,6) not null check (market_uncertainty between 0 and 1),
  disagreement_contribution numeric(9,6) not null check (disagreement_contribution between 0 and 100),
  confidence_dispersion_contribution numeric(9,6) not null check (confidence_dispersion_contribution between 0 and 100),
  timeframe_conflict_contribution numeric(9,6) not null check (timeframe_conflict_contribution between 0 and 100),
  market_uncertainty_contribution numeric(9,6) not null check (market_uncertainty_contribution between 0 and 100),
  hesitation_algorithm_version text not null,
  created_at timestamptz not null default now()
);
create index if not exists ai_hesitation_snapshots_run_idx on public.ai_hesitation_snapshots(multi_agent_run_id, id);

create table if not exists public.ai_multi_agent_risk_results (
  id bigint generated always as identity primary key,
  multi_agent_run_id uuid not null references public.ai_multi_agent_runs(id) on delete restrict,
  consensus_id bigint not null references public.ai_consensus_decisions(id) on delete restrict,
  status text not null check (status in ('APPROVED', 'REJECTED', 'PENDING')),
  approved boolean not null,
  reason_codes text[] not null default '{}',
  risk_policy_version text not null,
  created_at timestamptz not null default now(),
  check ((status = 'APPROVED' and approved = true) or (status <> 'APPROVED' and approved = false))
);
create index if not exists ai_multi_agent_risk_results_run_idx on public.ai_multi_agent_risk_results(multi_agent_run_id, id);

create table if not exists public.ai_decision_outcomes (
  id bigint generated always as identity primary key,
  multi_agent_run_id uuid not null references public.ai_multi_agent_runs(id) on delete restrict,
  agent_attempt_id bigint references public.ai_agent_attempts(id) on delete restrict,
  horizon text not null check (horizon in ('15M', '1H', '4H')),
  state text not null check (state in ('PENDING', 'EVALUABLE', 'EVALUATED', 'INVALID_DATA')),
  reference_price numeric not null check (reference_price > 0),
  horizon_price numeric check (horizon_price is null or horizon_price > 0),
  matured_at timestamptz not null,
  evaluated_at timestamptz,
  directional_hit boolean,
  signed_return_pct numeric,
  mfe_pct numeric,
  mae_pct numeric,
  market_regime text not null,
  data_quality text not null check (data_quality in ('FULL', 'PARTIAL', 'MISSING')),
  invalid_reason text,
  created_at timestamptz not null default now()
);
create index if not exists ai_decision_outcomes_run_idx on public.ai_decision_outcomes(multi_agent_run_id, horizon, created_at desc);
create unique index if not exists ai_decision_outcomes_identity_idx
  on public.ai_decision_outcomes(multi_agent_run_id, agent_attempt_id, horizon) nulls not distinct;

create table if not exists public.ai_agent_performance_snapshots (
  id bigint generated always as identity primary key,
  role text not null check (role in ('TECHNICAL', 'MOMENTUM', 'ORDER_FLOW', 'NEWS', 'CONTRARIAN', 'RISK_REVIEW')),
  provider text not null,
  model text not null,
  as_of timestamptz not null,
  horizon text not null check (horizon in ('15M', '1H', '4H')),
  sample_count integer not null check (sample_count >= 0),
  hit_rate numeric(9,6) check (hit_rate is null or hit_rate between 0 and 1),
  mean_signed_return_pct numeric,
  normalized_expectancy numeric(9,6),
  quality_score numeric(9,6) not null check (quality_score between 0 and 1),
  multiplier numeric(9,6) not null check (multiplier >= 0),
  performance_algorithm_version text not null,
  created_at timestamptz not null default now()
);
create index if not exists ai_agent_performance_point_in_time_idx
  on public.ai_agent_performance_snapshots(role, provider, model, horizon, as_of desc);

create table if not exists public.ai_dashboard_events (
  id bigint generated always as identity primary key,
  multi_agent_run_id uuid not null references public.ai_multi_agent_runs(id) on delete restrict,
  sequence integer not null check (sequence >= 1),
  event_type text not null,
  role text check (role is null or role in ('TECHNICAL', 'MOMENTUM', 'ORDER_FLOW', 'NEWS', 'CONTRARIAN', 'RISK_REVIEW')),
  status text not null,
  message text not null,
  metadata_safe jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (multi_agent_run_id, sequence)
);
create index if not exists ai_dashboard_events_run_idx on public.ai_dashboard_events(multi_agent_run_id, sequence, id);

create or replace function public.enforce_ai_multi_agent_run_insert()
returns trigger
language plpgsql
as $$
begin
  if new.status <> 'RUNNING' or new.completed_at is not null or new.valid_role_count <> 0 then
    raise exception 'multi-agent runs must start RUNNING and unfinished';
  end if;
  return new;
end;
$$;

create or replace function public.guard_ai_multi_agent_run_update()
returns trigger
language plpgsql
as $$
begin
  if old.status <> 'RUNNING' then
    raise exception 'multi-agent run is already terminal';
  end if;
  if new.status not in ('COMPLETED', 'PARTIAL', 'INSUFFICIENT_EVIDENCE', 'FAILED') then
    raise exception 'multi-agent run must finalize to a terminal status';
  end if;
  if new.completed_at is null then
    raise exception 'terminal multi-agent run requires completed_at';
  end if;
  if new.id is distinct from old.id
     or new.scanner_candidate_id is distinct from old.scanner_candidate_id
     or new.scanner_run_id is distinct from old.scanner_run_id
     or new.symbol is distinct from old.symbol
     or new.timeframe is distinct from old.timeframe
     or new.started_at is distinct from old.started_at
     or new.snapshot_ref is distinct from old.snapshot_ref
     or new.snapshot_observed_at is distinct from old.snapshot_observed_at
     or new.config_version is distinct from old.config_version
     or new.enabled_role_count is distinct from old.enabled_role_count
     or new.rollout_mode is distinct from old.rollout_mode
     or new.market_context_summary is distinct from old.market_context_summary
     or new.legacy_analysis_ref is distinct from old.legacy_analysis_ref then
    raise exception 'immutable multi-agent run fields cannot change';
  end if;
  return new;
end;
$$;

create or replace function public.reject_ai_multi_agent_evidence_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'multi-agent audit evidence is append-only';
end;
$$;

drop trigger if exists ai_multi_agent_runs_enforce_insert on public.ai_multi_agent_runs;
create trigger ai_multi_agent_runs_enforce_insert
before insert on public.ai_multi_agent_runs
for each row execute function public.enforce_ai_multi_agent_run_insert();

drop trigger if exists ai_multi_agent_runs_guard_update on public.ai_multi_agent_runs;
create trigger ai_multi_agent_runs_guard_update
before update on public.ai_multi_agent_runs
for each row execute function public.guard_ai_multi_agent_run_update();

drop trigger if exists ai_multi_agent_runs_reject_delete on public.ai_multi_agent_runs;
create trigger ai_multi_agent_runs_reject_delete
before delete on public.ai_multi_agent_runs
for each row execute function public.reject_ai_multi_agent_evidence_mutation();

-- Every evidence row other than the controlled run envelope is immutable.
drop trigger if exists ai_multi_agent_configs_append_only on public.ai_multi_agent_configs;
create trigger ai_multi_agent_configs_append_only before update or delete on public.ai_multi_agent_configs for each row execute function public.reject_ai_multi_agent_evidence_mutation();
drop trigger if exists ai_agent_attempts_append_only on public.ai_agent_attempts;
create trigger ai_agent_attempts_append_only before update or delete on public.ai_agent_attempts for each row execute function public.reject_ai_multi_agent_evidence_mutation();
drop trigger if exists ai_consensus_decisions_append_only on public.ai_consensus_decisions;
create trigger ai_consensus_decisions_append_only before update or delete on public.ai_consensus_decisions for each row execute function public.reject_ai_multi_agent_evidence_mutation();
drop trigger if exists ai_hesitation_snapshots_append_only on public.ai_hesitation_snapshots;
create trigger ai_hesitation_snapshots_append_only before update or delete on public.ai_hesitation_snapshots for each row execute function public.reject_ai_multi_agent_evidence_mutation();
drop trigger if exists ai_multi_agent_risk_results_append_only on public.ai_multi_agent_risk_results;
create trigger ai_multi_agent_risk_results_append_only before update or delete on public.ai_multi_agent_risk_results for each row execute function public.reject_ai_multi_agent_evidence_mutation();
drop trigger if exists ai_decision_outcomes_append_only on public.ai_decision_outcomes;
create trigger ai_decision_outcomes_append_only before update or delete on public.ai_decision_outcomes for each row execute function public.reject_ai_multi_agent_evidence_mutation();
drop trigger if exists ai_agent_performance_snapshots_append_only on public.ai_agent_performance_snapshots;
create trigger ai_agent_performance_snapshots_append_only before update or delete on public.ai_agent_performance_snapshots for each row execute function public.reject_ai_multi_agent_evidence_mutation();
drop trigger if exists ai_dashboard_events_append_only on public.ai_dashboard_events;
create trigger ai_dashboard_events_append_only before update or delete on public.ai_dashboard_events for each row execute function public.reject_ai_multi_agent_evidence_mutation();

alter table public.ai_multi_agent_configs enable row level security;
alter table public.ai_multi_agent_runs enable row level security;
alter table public.ai_agent_attempts enable row level security;
alter table public.ai_consensus_decisions enable row level security;
alter table public.ai_hesitation_snapshots enable row level security;
alter table public.ai_multi_agent_risk_results enable row level security;
alter table public.ai_decision_outcomes enable row level security;
alter table public.ai_agent_performance_snapshots enable row level security;
alter table public.ai_dashboard_events enable row level security;

create policy "public multi agent runs readable" on public.ai_multi_agent_runs for select to anon, authenticated using (true);
create policy "public agent attempts readable" on public.ai_agent_attempts for select to anon, authenticated using (true);
create policy "public consensus readable" on public.ai_consensus_decisions for select to anon, authenticated using (true);
create policy "public hesitation readable" on public.ai_hesitation_snapshots for select to anon, authenticated using (true);
create policy "public multi agent risk readable" on public.ai_multi_agent_risk_results for select to anon, authenticated using (true);
create policy "public decision outcomes readable" on public.ai_decision_outcomes for select to anon, authenticated using (true);
create policy "public agent performance readable" on public.ai_agent_performance_snapshots for select to anon, authenticated using (true);
create policy "public dashboard events readable" on public.ai_dashboard_events for select to anon, authenticated using (true);

revoke all on public.ai_multi_agent_configs from anon, authenticated;
revoke all on public.ai_multi_agent_runs from anon, authenticated;
revoke all on public.ai_agent_attempts from anon, authenticated;
revoke all on public.ai_consensus_decisions from anon, authenticated;
revoke all on public.ai_hesitation_snapshots from anon, authenticated;
revoke all on public.ai_multi_agent_risk_results from anon, authenticated;
revoke all on public.ai_decision_outcomes from anon, authenticated;
revoke all on public.ai_agent_performance_snapshots from anon, authenticated;
revoke all on public.ai_dashboard_events from anon, authenticated;

grant select (id, scanner_candidate_id, scanner_run_id, symbol, timeframe, started_at, completed_at, status, snapshot_ref, snapshot_observed_at, config_version, enabled_role_count, valid_role_count, rollout_mode, market_context_summary, legacy_analysis_ref) on public.ai_multi_agent_runs to anon, authenticated;
grant select (id, multi_agent_run_id, role, provider, model, prompt_version, prompt_digest, status, direction, confidence, entry_min, entry_max, stop_loss, take_profits, risk_reward, reason_summary, latency_ms, error_code, snapshot_ref, created_at) on public.ai_agent_attempts to anon, authenticated;
grant select (id, multi_agent_run_id, direction, consensus_confidence, winning_agreement, coverage, signed_score, actionable, supporting_roles, opposing_roles, reason_codes, role_contributions, config_version, consensus_algorithm_version, created_at) on public.ai_consensus_decisions to anon, authenticated;
grant select (id, multi_agent_run_id, consensus_id, total, disagreement, confidence_dispersion, timeframe_conflict, market_uncertainty, disagreement_contribution, confidence_dispersion_contribution, timeframe_conflict_contribution, market_uncertainty_contribution, hesitation_algorithm_version, created_at) on public.ai_hesitation_snapshots to anon, authenticated;
grant select (id, multi_agent_run_id, consensus_id, status, approved, reason_codes, risk_policy_version, created_at) on public.ai_multi_agent_risk_results to anon, authenticated;
grant select (id, multi_agent_run_id, agent_attempt_id, horizon, state, reference_price, horizon_price, matured_at, evaluated_at, directional_hit, signed_return_pct, mfe_pct, mae_pct, market_regime, data_quality, invalid_reason, created_at) on public.ai_decision_outcomes to anon, authenticated;
grant select (id, role, provider, model, as_of, horizon, sample_count, hit_rate, mean_signed_return_pct, normalized_expectancy, quality_score, multiplier, performance_algorithm_version, created_at) on public.ai_agent_performance_snapshots to anon, authenticated;
grant select (id, multi_agent_run_id, sequence, event_type, role, status, message, metadata_safe, created_at) on public.ai_dashboard_events to anon, authenticated;
