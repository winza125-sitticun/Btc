export type ScannerCandidate = {
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
