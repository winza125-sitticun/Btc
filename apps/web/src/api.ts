export type ScannerCandidate = {
  id: number
  run_id: string
  rank: number
  symbol: string
  timeframe: string
  direction: 'LONG' | 'SHORT' | 'WAIT' | 'EXIT'
  opportunity_score: number
  last_price: number
  quote_volume_24h: number
  funding_rate: number | null
  open_interest_change_percent: number | null
  long_short_ratio: number | null
  spread_percent: number | null
  created_at: string
}

export type LiveMarketState = {
  symbol: string
  mark_price?: number | null
  index_price?: number | null
  funding_rate?: number | null
  best_bid?: number | null
  best_ask?: number | null
  spread_percent?: number | null
  candle_timeframe?: string | null
  candle_close?: number | null
  event_time?: string | null
  updated_at?: string | null
}

export type AIAnalysis = {
  scanner_candidate_id: number
  run_id: string
  symbol: string
  timeframe: string
  provider: string
  model: string
  scanner_direction: 'LONG' | 'SHORT' | 'WAIT' | 'EXIT'
  ai_direction: 'LONG' | 'SHORT' | 'WAIT' | 'EXIT' | null
  confidence: number | null
  entry_min: number | null
  entry_max: number | null
  stop_loss: number | null
  take_profits: number[]
  risk_reward: number | null
  reason_summary: string | null
  status: 'SUCCESS' | 'SKIPPED' | 'FAILED' | 'INVALID_RESPONSE'
  risk_precheck_status: string | null
  risk_precheck_reasons: string[]
  latency_ms: number | null
  attempt_count: number
  error_code: string | null
  created_at: string
  completed_at: string | null
}

export type PublicConfig = {
  trading_mode: 'SIMULATION' | 'TESTNET' | 'LIVE'
  direct_ai_order_enabled: boolean
  min_confidence: number
  min_opportunity_score: number
  max_leverage: number
  ai_analysis_enabled: boolean
  ai_provider: string | null
  ai_model: string | null
  ai_api_key_configured: boolean
}

export type Page<T> = { items: T[]; next_cursor: string | null }
export type PerformanceSummary = Record<string, unknown> & { full_data_count?: number; partial_data_count?: number; win_rate?: number | null; expectancy?: number | null; max_drawdown_percent?: number | null }
export type SimulationAccount = Record<string, unknown> & { balance?: number; equity?: number; realized_pnl?: number; max_drawdown_percent?: number }
export type SimulationTrade = Record<string, unknown> & { id: number; ai_analysis_id: number; scanner_candidate_id: number; symbol: string; status: string; realized_pnl?: number | null }
export type Alert = Record<string, unknown> & { id: number; alert_type: string; severity: string; title: string; short_summary: string; ai_analysis_id?: number | null; scanner_run_id?: string | null }
export type Readiness = { id: number; overall_status: 'NOT_READY' | 'PAPER_READY' | 'LIVE_READY' | 'BLOCKED'; blocking_reasons: string[]; created_at: string }
export type OrderIntent = Record<string, unknown> & { id: number; simulation_trade_id: number | null; ai_analysis_id: number | null; mode: 'DRY_RUN'; symbol: string; side: string; validation_status: string; exchange_submission_allowed: boolean }

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function fetchLatestCandidates(timeframe: string, limit = 10) {
  const params = new URLSearchParams({ timeframe, limit: String(limit) })
  return getJson<ScannerCandidate[]>(`/api/v1/scanner/latest?${params}`)
}

export function fetchLiveStates(symbols: string[]) {
  if (symbols.length === 0) return Promise.resolve([] as LiveMarketState[])
  const params = new URLSearchParams({ symbols: symbols.join(',') })
  return getJson<LiveMarketState[]>(`/api/v1/market/live?${params}`)
}

export function fetchLatestAIAnalyses(timeframe: string, limit = 10) {
  const params = new URLSearchParams({ timeframe, limit: String(limit) })
  return getJson<AIAnalysis[]>(`/api/v1/ai/latest?${params}`)
}

export function fetchPublicConfig() {
  return getJson<PublicConfig>('/api/v1/config/public')
}

export type StrategyPage = { items: Record<string, unknown>[]; next_cursor: string | null }
export function fetchStrategy(resource: string, limit = 20) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (resource === 'order-intents') params.set('mode', 'DRY_RUN')
  return getJson<StrategyPage>(`/api/v1/${resource}?${params}`)
}

function fetchPage<T>(path: string, limit = 50) { return getJson<Page<T>>(`${path}${path.includes('?') ? '&' : '?'}limit=${limit}`) }
export function fetchPerformanceSummary() { return fetchPage<PerformanceSummary>('/api/v1/performance/summary') }
export function fetchSimulationAccount() { return fetchPage<SimulationAccount>('/api/v1/simulation/account', 1) }
export function fetchSimulationTrades() { return fetchPage<SimulationTrade>('/api/v1/simulation/trades') }
export function fetchAlerts() { return fetchPage<Alert>('/api/v1/alerts') }
export function fetchReadiness() { return fetchPage<Readiness>('/api/v1/readiness', 1) }
export function fetchOrderIntents() { return fetchPage<OrderIntent>('/api/v1/order-intents?mode=DRY_RUN') }
