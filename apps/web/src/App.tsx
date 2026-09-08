import { useEffect, useMemo, useState } from 'react'
import { fetchLatestCandidates, fetchLiveStates, type LiveMarketState, type ScannerCandidate } from './api'

const providers = ['Gemini', 'Claude', 'OpenAI-compatible API', 'DeepSeek API', 'OpenRouter']
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

export default function App() {
  const [page, setPage] = useState<'dashboard' | 'scanner' | 'settings'>('dashboard')
  const [provider, setProvider] = useState('Gemini')
  const [model, setModel] = useState('')
  const [timeframe, setTimeframe] = useState('15m')
  const [candidates, setCandidates] = useState<ScannerCandidate[]>([])
  const [live, setLive] = useState<Record<string, LiveMarketState>>({})
  const [scannerError, setScannerError] = useState('')
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

  const topLong = useMemo(() => candidates.find((item) => item.direction === 'LONG'), [candidates])
  const topShort = useMemo(() => candidates.find((item) => item.direction === 'SHORT'), [candidates])

  const candidateRows = (
    <div className="candidate-list">
      {scannerLoading && !candidates.length ? <div className="empty-state">Loading market scanner…</div> : null}
      {!scannerLoading && !candidates.length ? <div className="empty-state">No scanner results yet. Market worker may still be starting.</div> : null}
      {candidates.map((candidate) => {
        const realtime = live[candidate.symbol]
        const price = realtime?.mark_price ?? candidate.last_price
        return (
          <article className="candidate" key={candidate.symbol}>
            <div className="rank">#{candidate.rank}</div>
            <div className="grow">
              <strong>{candidate.symbol}</strong>
              <span className={`signal ${candidate.direction.toLowerCase()}`}>{candidate.direction}</span>
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
        <span className="mode-badge">SIMULATION</span>
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
              <span>Market-only score • News/AI enrichment comes next</span>
            </div>
          </section>

          {page === 'scanner' ? (
            <section className="panel detail-grid">
              {candidates.slice(0, 6).map((candidate) => (
                <article className="detail-card" key={`detail-${candidate.symbol}`}>
                  <div className="detail-head"><strong>{candidate.symbol}</strong><span className={`signal ${candidate.direction.toLowerCase()}`}>{candidate.direction}</span></div>
                  <dl>
                    <div><dt>24h volume</dt><dd>${formatCompact(candidate.quote_volume_24h)}</dd></div>
                    <div><dt>Long/Short</dt><dd>{candidate.long_short_ratio?.toFixed(3) ?? '—'}</dd></div>
                    <div><dt>Spread</dt><dd>{candidate.spread_percent?.toFixed(4) ?? '—'}%</dd></div>
                    <div><dt>Live mark</dt><dd>{formatPrice(live[candidate.symbol]?.mark_price ?? candidate.last_price)}</dd></div>
                  </dl>
                </article>
              ))}
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
              <select value={provider} onChange={(e) => setProvider(e.target.value)}>
                {providers.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            <label>Model
              <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="Enter model name" />
            </label>
            <label>API Key
              <input value="Not configured" disabled aria-describedby="secret-note" />
            </label>
            <small id="secret-note">Plaintext secrets are never stored in browser state.</small>
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
            ].map((role) => <label className="check" key={role}><input type="checkbox" defaultChecked /> {role}</label>)}
            <label className="check danger"><input type="checkbox" disabled /> ให้ AI ส่ง Order โดยตรง (ปิดใน V1)</label>
          </section>
        </main>
      )}
    </div>
  )
}
