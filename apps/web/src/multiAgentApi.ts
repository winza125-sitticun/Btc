import { useEffect, useRef, useState } from 'react'
import type {
  DashboardEvent,
  MultiAgentConfigSummary,
  MultiAgentRunDetail,
  MultiAgentRunSummary,
  PerformanceSummary,
  RunStatus,
} from './multiAgentTypes'

export const ACTIVE_POLL_MS = 3000
export const TERMINAL_POLL_MS = 15000
export const HIDDEN_POLL_MS = 60000
export const STALE_AFTER_MS = 30000
export const RETRY_BACKOFF_MS = [2000, 5000, 10000, 30000] as const

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function fetchMultiAgentConfig() {
  return getJson<MultiAgentConfigSummary>('/api/v1/multi-agent/config')
}

export function fetchLatestMultiAgentRuns(timeframe: string, limit = 10) {
  const params = new URLSearchParams({ timeframe, limit: String(limit) })
  return getJson<MultiAgentRunSummary[]>(`/api/v1/multi-agent/latest?${params}`)
}

export function fetchMultiAgentRun(runId: string) {
  return getJson<MultiAgentRunDetail>(`/api/v1/multi-agent/runs/${encodeURIComponent(runId)}`)
}

export function fetchMultiAgentEvents(runId: string, limit = 100) {
  const params = new URLSearchParams({ run_id: runId, limit: String(limit) })
  return getJson<DashboardEvent[]>(`/api/v1/multi-agent/events?${params}`)
}

export function fetchMultiAgentPerformance(limit = 50) {
  const params = new URLSearchParams({ limit: String(limit) })
  return getJson<PerformanceSummary[]>(`/api/v1/multi-agent/performance?${params}`)
}

export type MultiAgentDashboardState = {
  config: MultiAgentConfigSummary | null
  runs: MultiAgentRunSummary[]
  run: MultiAgentRunDetail | null
  events: DashboardEvent[]
  performance: PerformanceSummary[]
  loading: boolean
  error: string | null
  stale: boolean
  lastSuccessfulRefresh: number | null
}

function pollDelay(status: RunStatus | undefined) {
  if (document.hidden) return HIDDEN_POLL_MS
  if (status === 'RUNNING' || status === 'PARTIAL') return ACTIVE_POLL_MS
  return TERMINAL_POLL_MS
}

export function useMultiAgentDashboard(timeframe: string): MultiAgentDashboardState {
  const [config, setConfig] = useState<MultiAgentConfigSummary | null>(null)
  const [runs, setRuns] = useState<MultiAgentRunSummary[]>([])
  const [run, setRun] = useState<MultiAgentRunDetail | null>(null)
  const [events, setEvents] = useState<DashboardEvent[]>([])
  const [performance, setPerformance] = useState<PerformanceSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const [lastSuccessfulRefresh, setLastSuccessfulRefresh] = useState<number | null>(null)
  const lastSuccessfulRefreshRef = useRef<number | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    let retryIndex = 0
    const startedAt = Date.now()

    function clearTimer() {
      if (timer !== undefined) window.clearTimeout(timer)
      timer = undefined
    }

    function schedule(delay: number) {
      clearTimer()
      timer = window.setTimeout(() => { void refresh() }, delay)
    }

    async function refresh() {
      let nextDelay = TERMINAL_POLL_MS
      try {
        const [nextConfig, nextRuns, nextPerformance] = await Promise.all([
          fetchMultiAgentConfig(),
          fetchLatestMultiAgentRuns(timeframe, 10),
          fetchMultiAgentPerformance(50),
        ])
        const latest = nextRuns[0] ?? null
        const [nextRun, nextEvents] = latest
          ? await Promise.all([fetchMultiAgentRun(latest.id), fetchMultiAgentEvents(latest.id, 100)])
          : [null, [] as DashboardEvent[]]
        if (cancelled) return

        setConfig(nextConfig)
        setRuns(nextRuns)
        setRun(nextRun)
        setEvents(nextEvents)
        setPerformance(nextPerformance)
        setError(null)
        setLoading(false)
        const successAt = Date.now()
        lastSuccessfulRefreshRef.current = successAt
        setLastSuccessfulRefresh(successAt)
        setStale(false)
        retryIndex = 0
        nextDelay = pollDelay(nextRun?.status ?? latest?.status)
      } catch (caught) {
        if (cancelled) return
        setLoading(false)
        setError(caught instanceof Error ? caught.message : 'Multi-agent API unavailable')
        nextDelay = RETRY_BACKOFF_MS[Math.min(retryIndex, RETRY_BACKOFF_MS.length - 1)]
        retryIndex = Math.min(retryIndex + 1, RETRY_BACKOFF_MS.length - 1)
      } finally {
        if (!cancelled) schedule(nextDelay)
      }
    }

    function onVisibilityChange() {
      clearTimer()
      void refresh()
    }

    document.addEventListener('visibilitychange', onVisibilityChange)
    void refresh()
    const staleTimer = window.setInterval(() => {
      const basis = lastSuccessfulRefreshRef.current ?? startedAt
      setStale(Date.now() - basis >= STALE_AFTER_MS)
    }, 1000)

    return () => {
      cancelled = true
      clearTimer()
      window.clearInterval(staleTimer)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [timeframe])

  return { config, runs, run, events, performance, loading, error, stale, lastSuccessfulRefresh }
}
