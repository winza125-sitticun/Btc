-- Performance hardening from Supabase Performance Advisor.
-- Preserve existing access semantics; optimize auth.uid() evaluation and add FK indexes.

create index if not exists ai_decisions_scanner_candidate_idx
  on public.ai_decisions(scanner_candidate_id);

create index if not exists risk_decisions_ai_decision_idx
  on public.risk_decisions(ai_decision_id);

create index if not exists risk_decisions_user_idx
  on public.risk_decisions(user_id);

create index if not exists scanner_runs_user_idx
  on public.scanner_runs(user_id);

create index if not exists simulation_positions_account_idx
  on public.simulation_positions(account_id);

drop policy if exists "profiles own row" on public.profiles;
create policy "profiles own row" on public.profiles
  for all
  using ((select auth.uid()) = id)
  with check ((select auth.uid()) = id);

drop policy if exists "trading settings own row" on public.trading_settings;
create policy "trading settings own row" on public.trading_settings
  for all
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "ai configs own rows" on public.ai_provider_configs;
create policy "ai configs own rows" on public.ai_provider_configs
  for all
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "scanner runs own rows" on public.scanner_runs;
create policy "scanner runs own rows" on public.scanner_runs
  for all
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "ai decisions own rows" on public.ai_decisions;
create policy "ai decisions own rows" on public.ai_decisions
  for all
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "risk decisions own rows" on public.risk_decisions;
create policy "risk decisions own rows" on public.risk_decisions
  for all
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "simulation accounts own rows" on public.simulation_accounts;
create policy "simulation accounts own rows" on public.simulation_accounts
  for all
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "simulation positions own rows" on public.simulation_positions;
create policy "simulation positions own rows" on public.simulation_positions
  for all
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
