import { useEffect, useMemo, useState } from 'react'
import {
  fetchLatestAIAnalyses,
  fetchLatestCandidates,
  fetchLiveStates,
  fetchPublicConfig,
  type AIAnalysis,
  type LiveMarketState,
  type PublicConfig,
  type ScannerCandidate,
} from './api'

const providers = [
  { value: 'GEMINI', label: 'Gemini' },
  { value: 'CLAUDE', label: 'Claude' },
  { value: 'OPENAI_COMPATIBLE', label: 'OpenAI-compatible API' },
  { value: 'DEEPSEEK', label: 'DeepSeek API' },
  { value: 'OPENROUTER', label: 'OpenRouter' },
]
const timeframes = ['5m', '15m', '1h', '4h']

function formatPrice(value: number | null | undefined) {
  if (value == null) return '—'
  if (value >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  if (value >= 1) return value.toLocaleString(undefined, { maximumFractionDigits: 4 })
  return value.toLocaleString(undefined, { maximumFractionDigits: 8 })
}

function formatCompact(value: number) {
  return Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function riskLabel(status: string | null) {
  if (status === 'FULL_RISK_CONTEXT_PENDING') return 'Pending — not trade-authorized'
  if (status === 'PRECHECK_FAILED') return 'Precheck failed — not trade-authorized'
  if (status) return `${status} — not trade-authorized`
  return 'Not trade-authorized'
}

function analysisForCandidate(
  candidate: ScannerCandidate,
  latest: Record<string, AIAnalysis>,
) {
  const analysis = latest[candidate.symbol]
  if (
    !analysis
    || analysis.scanner_candidate_id !== candidate.id
    || analysis.run_id !== candidate.run_id
    || analysis.timeframe !== candidate.timeframe
  ) return undefined
  return analysis
}

export default function App() {
  const [page, setPage] = useState<'dashboard' | 'scanner' | 'settings'>('dashboard')
  const [timeframe, setTimeframe] = useState('15m')
  const [candidates, setCandidates] = useState<ScannerCandidate[]>([])
  const [live, setLive] = useState<Record<string, LiveMarketState>>({})
  const [analyses, setAnalyses] = useState<AIAnalysis[]>([])
  const [publicConfig, setPublicConfig] = useState<PublicConfig | null>(null)
  const [scannerError, setScannerError] = useState('')
  const [aiError, setAiError] = useState('')
  const [scannerLoading, setScannerLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)

  useEffect(() => {
    let cancelled = false
    async function refreshScanner() {
      try {
        const next = await fetchLatestCandidates(timeframe, 10)
        if (cancelled) return
        setCandidates(next)
        setScannerError('')
        setLastRefresh(new Date())
      } catch (error) {
        if (!cancelled) setScannerError(error instanceof Error ? error.message : 'Scanner API unavailable')
      } finally {
        if (!cancelled) setScannerLoading(false)
      }
    }
    setScannerLoading(true)
    void refreshScanner()
    const timer = window.setInterval(refreshScanner, 15_000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [timeframe])

  useEffect(() => {
    const symbols = candidates.map((candidate) => candidate.symbol)
    if (!symbols.length) {
      setLive({})
      return
    }
    let cancelled = false
    async function refreshLive() {
      try {
        const rows = await fetchLiveStates(symbols)
        if (!cancelled) setLive(Object.fromEntries(rows.map((row) => [row.symbol, row])))
      } catch {
        // Scanner snapshot remains usable if the realtime endpoint is temporarily unavailable.
      }
    }
    void refreshLive()
    const timer = window.setInterval(refreshLive, 3_000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [candidates])

  useEffect(() => {
    let cancelled = false
    async function refreshAI() {
      try {
        const rows = await fetchLatestAIAnalyses(timeframe, 20)
        if (cancelled) return
        setAnalyses(rows)
        setAiError('')
      } catch (error) {
        if (!cancelled) setAiError(error instanceof Error ? error.message : 'AI analysis unavailable')
      }
    }
    void refreshAI()
    const timer = window.setInterval(refreshAI, 15_000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [timeframe])

  useEffect(() => {
    let cancelled = false
    async function refreshConfig() {
      try {
        const next = await fetchPublicConfig()
        if (!cancelled) setPublicConfig(next)
      } catch {
        if (!cancelled) setPublicConfig(null)
      }
    }
    void refreshConfig()
    const timer = window.setInterval(refreshConfig, 30_000)
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [])

  const latestAIBySymbol = useMemo(() => {
    const latest: Record<string, AIAnalysis> = {}
    for (const analysis of analyses) {
      if (!latest[analysis.symbol]) latest[analysis.symbol] = analysis
    }
    return latest
  }, [analyses])

  const topLong = useMemo(() => candidates.find((item) => item.direction === 'LONG'), [candidates])
  const topShort = useMemo(() => candidates.find((item) => item.direction === 'SHORT'), [candidates])

  const candidateRows = (
    <div className="candidate-list">
      {scannerLoading && !candidates.length ? <div className="empty-state">Loading market scanner…</div> : null}
      {!scannerLoading && !candidates.length ? <div className="empty-state">No scanner results yet. Market worker may still be starting.</div> : null}
      {candidates.map((candidate) => {
        const realtime = live[candidate.symbol]
        const price = realtime?.mark_price ?? candidate.last_price
        const analysis = analysisForCandidate(candidate, latestAIBySymbol)
        return (
          <article className="candidate" key={candidate.id}>
            <div className="rank">#{candidate.rank}</div>
            <div className="grow">
              <strong>{candidate.symbol}</strong>
              <span className={`signal ${candidate.direction.toLowerCase()}`}>{candidate.direction}</span>
              {analysis?.status === 'SUCCESS' && analysis.ai_direction ? (
                <span className={`signal ai-signal ${analysis.ai_direction.toLowerCase()}`}>
                  AI {analysis.ai_direction} {analysis.confidence != null ? `${analysis.confidence.toFixed(0)}%` : ''}
                </span>
              ) : null}
            </div>
            <div><span>Score</span><strong>{candidate.opportunity_score.toFixed(1)}</strong></div>
            <div><span>Price</span><strong>{formatPrice(price)}</strong></div>
            <div><span>OI Δ</span><strong>{candidate.open_interest_change_percent?.toFixed(2) ?? '—'}%</strong></div>
            <div><span>Funding</span><strong>{candidate.funding_rate != null ? `${(candidate.funding_rate * 100).toFixed(4)}%` : '—'}</strong></div>
          </article>
        )
      })}
    </div>
  )

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AI FUTURES TRADER</p>
          <h1>{page === 'settings' ? 'AI Settings' : page === 'scanner' ? 'Opportunity Scanner' : 'Market Dashboard'}</h1>
        </div>
        <span className="mode-badge">{publicConfig?.trading_mode ?? 'SIMULATION'}</span>
      </header>

      <nav className="tabs" aria-label="Main navigation">
        <button className={page === 'dashboard' ? 'active' : ''} onClick={() => setPage('dashboard')}>Dashboard</button>
        <button className={page === 'scanner' ? 'active' : ''} onClick={() => setPage('scanner')}>Scanner</button>
        <button className={page === 'settings' ? 'active' : ''} onClick={() => setPage('settings')}>Settings</button>
      </nav>

      {page !== 'settings' ? (
        <main>
          <section className="metrics">
            <article><span>Mode</span><strong>Paper</strong></article>
            <article><span>Tracked</span><strong>{candidates.length}</strong></article>
            <article><span>Top LONG</span><strong>{topLong?.symbol ?? '—'}</strong></article>
            <article><span>Top SHORT</span><strong>{topShort?.symbol ?? '—'}</strong></article>
          </section>

          <section className="panel">
            <div className="section-title scanner-title">
              <div><p className="eyebrow">BINANCE USDⓈ-M</p><h2>Risk-adjusted opportunities</h2></div>
              <div className="scanner-controls">
                <select aria-label="Scanner timeframe" value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
                  {timeframes.map((item) => <option key={item}>{item}</option>)}
                </select>
                <span className={scannerError ? 'status error' : 'status online'}>{scannerError ? 'API OFFLINE' : 'LIVE DATA'}</span>
              </div>
            </div>
            {scannerError ? <div className="error-box">{scannerError}</div> : null}
            {candidateRows}
            <div className="scanner-footnote">
              <span>{lastRefresh ? `Scanner refreshed ${lastRefresh.toLocaleTimeString()}` : 'Waiting for first scanner result'}</span>
              <span>Market + News + AI enrichment • Analysis is not trade authorization</span>
            </div>
          </section>

          {aiError ? <div className="ai-status-note">AI analysis unavailable: {aiError}. Scanner data remains active.</div> : null}

          {page === 'scanner' ? (
            <section className="panel detail-grid">
              {candidates.slice(0, 6).map((candidate) => {
                const analysis = analysisForCandidate(candidate, latestAIBySymbol)
                return (
                  <article className="detail-card" key={`detail-${candidate.id}`}>
                    <div className="detail-head"><strong>{candidate.symbol}</strong><span className={`signal ${candidate.direction.toLowerCase()}`}>{candidate.direction}</span></div>
                    <dl>
                      <div><dt>24h volume</dt><dd>${formatCompact(candidate.quote_volume_24h)}</dd></div>
                      <div><dt>Long/Short</dt><dd>{candidate.long_short_ratio?.toFixed(3) ?? '—'}</dd></div>
                      <div><dt>Spread</dt><dd>{candidate.spread_percent?.toFixed(4) ?? '—'}%</dd></div>
                      <div><dt>Live mark</dt><dd>{formatPrice(live[candidate.symbol]?.mark_price ?? candidate.last_price)}</dd></div>
                    </dl>

                    {analysis ? (
                      <div className="ai-analysis">
                        <div className="ai-analysis-head">
                          <strong>AI Analysis</strong>
                          <span>{analysis.provider} · {analysis.model}</span>
                        </div>
                        {analysis.status === 'SUCCESS' ? (
                          <>
                            <div className="ai-grid">
                              <div><span>Direction</span><strong>{analysis.ai_direction ?? '—'}</strong></div>
                              <div><span>Confidence</span><strong>{analysis.confidence != null ? `${analysis.confidence.toFixed(0)}%` : '—'}</strong></div>
                              <div><span>Entry</span><strong>{formatPrice(analysis.entry_min)} – {formatPrice(analysis.entry_max)}</strong></div>
                              <div><span>SL</span><strong>{formatPrice(analysis.stop_loss)}</strong></div>
                              <div><span>TP</span><strong>{analysis.take_profits.map(formatPrice).join(' / ') || '—'}</strong></div>
                              <div><span>R:R</span><strong>{analysis.risk_reward?.toFixed(2) ?? '—'}</strong></div>
                            </div>
                            {analysis.reason_summary ? <p className="ai-reason">{analysis.reason_summary}</p> : null}
                            <div className="risk-pending">{riskLabel(analysis.risk_precheck_status)}</div>
                          </>
                        ) : (
                          <div className="ai-unavailable">AI status: {analysis.status}{analysis.error_code ? ` (${analysis.error_code})` : ''}</div>
                        )}
                      </div>
                    ) : (
                      <div className="ai-unavailable">No AI analysis for this candidate yet.</div>
                    )}
                  </article>
                )
              })}
            </section>
          ) : null}

          <section className="guard">
            <strong>Risk Guard: ON</strong>
            <span>Realtime market data is read-only. AI order execution and live trading remain disabled.</span>
          </section>
        </main>
      ) : (
        <main className="settings-grid">
          <section className="panel">
            <p className="eyebrow">AI PROVIDER</p>
            <label>Provider
              <select value={publicConfig?.ai_provider ?? ''} disabled>
                <option value="">Not configured</option>
                {providers.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label>Model
              <input value={publicConfig?.ai_model ?? 'Not configured'} disabled readOnly />
            </label>
            <label>API Key
              <input value={publicConfig?.ai_api_key_configured ? 'Configured' : 'Not configured'} disabled readOnly aria-describedby="secret-note" />
            </label>
            <small id="secret-note">Production AI settings are read-only in V1. Plaintext secrets are never returned to the browser.</small>
            <div className="settings-status">
              AI Analysis: <strong>{publicConfig?.ai_analysis_enabled ? 'Enabled' : 'Disabled'}</strong>
            </div>
          </section>

          <section className="panel">
            <p className="eyebrow">AI ROLE</p>
            {[
              'วิเคราะห์แนวโน้ม',
              'วิเคราะห์ข่าวและ Sentiment',
              'วิเคราะห์ Futures Market Data',
              'ตัดสินใจ LONG / SHORT / WAIT',
              'กำหนด Confidence',
              'เสนอ Entry / SL / TP',
            ].map((role) => <label className="check" key={role}><input type="checkbox" defaultChecked disabled /> {role}</label>)}
            <label className="check danger"><input type="checkbox" disabled /> ให้ AI ส่ง Order โดยตรง (ปิดใน V1)</label>
          </section>
        </main>
      )}
    </div>
  )
}
