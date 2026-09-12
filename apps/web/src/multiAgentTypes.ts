export type AgentRole = 'TECHNICAL' | 'MOMENTUM' | 'ORDER_FLOW' | 'NEWS' | 'CONTRARIAN' | 'RISK_REVIEW'
export type Direction = 'LONG' | 'SHORT' | 'WAIT' | 'EXIT'
export type AttemptStatus = 'SUCCESS' | 'FAILED' | 'INVALID_RESPONSE' | 'SKIPPED'
export type RunStatus = 'RUNNING' | 'COMPLETED' | 'PARTIAL' | 'INSUFFICIENT_EVIDENCE' | 'FAILED'
export type RiskStatus = 'APPROVED' | 'REJECTED' | 'PENDING'
export type EvaluationHorizon = '15M' | '1H' | '4H'
export type RolloutMode = 'OFF' | 'SHADOW' | 'PRIMARY'
export type DashboardEventSource = 'MULTI_AGENT' | 'ORDER_INTENT' | 'SIMULATION'

export type RoleAssignmentSummary = {
  role: AgentRole
  enabled: boolean
  provider: string
  model: string
  base_weight: number
  prompt_version: string
  prompt_digest: string
  secret_configured: boolean
}

export type MultiAgentConfigSummary = {
  config_version: string
  rollout_mode: RolloutMode
  min_valid_roles: number
  min_coverage: number
  min_agreement: number
  min_signed_score: number
  decision_contract_version: string
  consensus_algorithm_version: string
  hesitation_algorithm_version: string
  performance_algorithm_version: string
  roles: RoleAssignmentSummary[]
}

export type RoleContribution = {
  role: AgentRole
  provider: string
  model: string
  direction: Direction | null
  confidence: number | null
  base_weight: number
  historical_multiplier: number
  effective_weight: number
  unsigned_strength: number
  signed_contribution: number
  participated: boolean
  attempt_id: number | null
}

export type HesitationBreakdown = {
  total: number
  disagreement: number
  confidence_dispersion: number
  timeframe_conflict: number
  market_uncertainty: number
  disagreement_contribution: number
  confidence_dispersion_contribution: number
  timeframe_conflict_contribution: number
  market_uncertainty_contribution: number
  algorithm_version: string
}

export type VortexInputs = {
  trend_strength: number
  volatility: number
  momentum: number
  order_flow_imbalance: number
  liquidity: number
  consensus_direction: Direction
  winning_agreement: number
  hesitation_total: number
  observed_at: string
  snapshot_ref: string
  mapping_version: string
}

export type AgentAttempt = {
  id: number
  role: AgentRole
  provider: string
  model: string
  prompt_version: string
  prompt_digest: string
  status: AttemptStatus
  direction: Direction | null
  confidence: number | null
  entry_min: number | null
  entry_max: number | null
  stop_loss: number | null
  take_profits: number[]
  risk_reward: number | null
  reason_summary: string | null
  latency_ms: number
  error_code: string | null
  error_message: string | null
  snapshot_ref: string
  created_at: string
}

export type ConsensusDecision = {
  id: number
  direction: Direction
  consensus_confidence: number
  winning_agreement: number
  coverage: number
  signed_score: number
  actionable: boolean
  supporting_roles: AgentRole[]
  opposing_roles: AgentRole[]
  reason_codes: string[]
  role_contributions: RoleContribution[]
  config_version: string
  algorithm_version: string
  hesitation: HesitationBreakdown
  created_at: string
}

export type RiskResult = {
  status: RiskStatus
  approved: boolean
  reason_codes: string[]
  risk_policy_version: string
  created_at: string
}

export type MultiAgentRunSummary = {
  record_type: 'MULTI_AGENT'
  id: string
  scanner_candidate_id: number
  symbol: string
  timeframe: string
  started_at: string
  completed_at: string | null
  status: RunStatus
  config_version: string
  enabled_role_count: number
  valid_role_count: number
  rollout_mode: RolloutMode
  vortex_inputs: VortexInputs
  consensus: ConsensusDecision | null
  risk: RiskResult | null
}

export type MultiAgentRunDetail = MultiAgentRunSummary & {
  attempts: AgentAttempt[]
}

export type DashboardEvent = {
  id: number | string
  run_id: string
  source: DashboardEventSource
  event_type: string
  role: AgentRole | null
  status: string
  message: string
  metadata_safe: Record<string, unknown>
  created_at: string
}

export type PerformanceSummary = {
  role: AgentRole
  provider: string
  model: string
  symbol: string | null
  direction: Direction | null
  market_regime: string | null
  horizon: EvaluationHorizon
  sample_count: number
  hit_rate: number
  mean_signed_return_pct: number
  normalized_expectancy: number
  quality_score: number
  multiplier: number
  as_of: string
  algorithm_version: string
}
