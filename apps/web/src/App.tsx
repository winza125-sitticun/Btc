import { useEffect, useMemo, useState } from 'react'
import {
  fetchLatestAIAnalyses,
  fetchLatestCandidates,
  fetchLiveStates,
  fetchPublicConfig,
  fetchStrategy,
  type StrategyPage,
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
  const [strategyData, setStrategyData] = useState<Record<string, StrategyPage | null>>({})

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

  useEffect(() => {
    let cancelled = false
    const resources = ['performance/summary', 'simulation/account', 'alerts', 'readiness', 'order-intents']
    async function refreshStrategy() {
      const entries = await Promise.all(resources.map(async (resource) => {
        try { return [resource, await fetchStrategy(resource)] as const } catch { return [resource, null] as const }
      }))
      if (!cancelled) setStrategyData(Object.fromEntries(entries))
    }
    void refreshStrategy()
    const timer = window.setInterval(refreshStrategy, 30_000)
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
      {scannerLoading && !candidates.length ? <div className="empty-state">กำลังโหลดสแกนเนอร์ตลาด…</div> : null}
      {!scannerLoading && !candidates.length ? <div className="empty-state">ยังไม่มีผลสแกน ตลาดอาจกำลังเริ่มทำงาน</div> : null}
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
            <div><span>คะแนน</span><strong>{candidate.opportunity_score.toFixed(1)}</strong></div>
            <div><span>ราคา</span><strong>{formatPrice(price)}</strong></div>
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
          <h1>{page === 'settings' ? 'การตั้งค่า AI' : page === 'scanner' ? 'สแกนเนอร์โอกาส' : 'แดชบอร์ดตลาด'}</h1>
        </div>
        <span className="mode-badge">{publicConfig?.trading_mode === 'SIMULATION' ? 'โหมดจำลอง' : (publicConfig?.trading_mode ?? 'โหมดจำลอง')}</span>
      </header>

      <nav className="tabs" aria-label="Main navigation">
        <button className={page === 'dashboard' ? 'active' : ''} onClick={() => setPage('dashboard')}>แดชบอร์ด</button>
        <button className={page === 'scanner' ? 'active' : ''} onClick={() => setPage('scanner')}>สแกนเนอร์</button>
        <button className={page === 'settings' ? 'active' : ''} onClick={() => setPage('settings')}>การตั้งค่า</button>
      </nav>

      {page !== 'settings' ? (
        <main>
          <section className="metrics">
            <article><span>โหมด</span><strong>จำลอง</strong></article>
            <article><span>ติดตาม</span><strong>{candidates.length}</strong></article>
            <article><span>LONG สูงสุด</span><strong>{topLong?.symbol ?? '—'}</strong></article>
            <article><span>SHORT สูงสุด</span><strong>{topShort?.symbol ?? '—'}</strong></article>
          </section>

          <section className="panel">
            <div className="section-title scanner-title">
              <div><p className="eyebrow">BINANCE USDⓈ-M</p><h2>โอกาสที่ปรับตามความเสี่ยง</h2></div>
              <div className="scanner-controls">
                <select aria-label="Scanner timeframe" value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>
                  {timeframes.map((item) => <option key={item}>{item}</option>)}
                </select>
                <span className={scannerError ? 'status error' : 'status online'}>{scannerError ? 'API ออฟไลน์' : 'ข้อมูลสด'}</span>
              </div>
            </div>
            {scannerError ? <div className="error-box">{scannerError}</div> : null}
            {candidateRows}
            <div className="scanner-footnote">
              <span>{lastRefresh ? `อัปเดตสแกนเนอร์ ${lastRefresh.toLocaleTimeString()}` : 'รอผลสแกนครั้งแรก'}</span>
              <span>ตลาด + ข่าว + AI • การวิเคราะห์ไม่ใช่การอนุมัติเทรด</span>
            </div>
          </section>

          {aiError ? <div className="ai-status-note">ไม่สามารถวิเคราะห์ AI ได้: {aiError} ข้อมูลสแกนเนอร์ยังทำงานอยู่</div> : null}

          {page === 'scanner' ? (
            <section className="panel detail-grid">
              {candidates.slice(0, 6).map((candidate) => {
                const analysis = analysisForCandidate(candidate, latestAIBySymbol)
                return (
                  <article className="detail-card" key={`detail-${candidate.id}`}>
                    <div className="detail-head"><strong>{candidate.symbol}</strong><span className={`signal ${candidate.direction.toLowerCase()}`}>{candidate.direction}</span></div>
                    <dl>
                      <div><dt>ปริมาณ 24 ชม.</dt><dd>${formatCompact(candidate.quote_volume_24h)}</dd></div>
                      <div><dt>Long/Short</dt><dd>{candidate.long_short_ratio?.toFixed(3) ?? '—'}</dd></div>
                      <div><dt>ส่วนต่าง</dt><dd>{candidate.spread_percent?.toFixed(4) ?? '—'}%</dd></div>
                      <div><dt>ราคาล่าสุด</dt><dd>{formatPrice(live[candidate.symbol]?.mark_price ?? candidate.last_price)}</dd></div>
                    </dl>

                    {analysis ? (
                      <div className="ai-analysis">
                        <div className="ai-analysis-head">
                          <strong>การวิเคราะห์ AI</strong>
                          <span>{analysis.provider} · {analysis.model}</span>
                        </div>
                        {analysis.status === 'SUCCESS' ? (
                          <>
                            <div className="ai-grid">
                              <div><span>ทิศทาง</span><strong>{analysis.ai_direction ?? '—'}</strong></div>
                              <div><span>ความมั่นใจ</span><strong>{analysis.confidence != null ? `${analysis.confidence.toFixed(0)}%` : '—'}</strong></div>
                              <div><span>จุดเข้า</span><strong>{formatPrice(analysis.entry_min)} – {formatPrice(analysis.entry_max)}</strong></div>
                              <div><span>จุดตัดขาดทุน</span><strong>{formatPrice(analysis.stop_loss)}</strong></div>
                              <div><span>เป้าหมายกำไร</span><strong>{analysis.take_profits.map(formatPrice).join(' / ') || '—'}</strong></div>
                              <div><span>อัตราส่วน R:R</span><strong>{analysis.risk_reward?.toFixed(2) ?? '—'}</strong></div>
                            </div>
                            {analysis.reason_summary ? <p className="ai-reason">{analysis.reason_summary}</p> : null}
                            <div className="risk-pending">{riskLabel(analysis.risk_precheck_status)}</div>
                          </>
                        ) : (
                          <div className="ai-unavailable">AI status: {analysis.status}{analysis.error_code ? ` (${analysis.error_code})` : ''}</div>
                        )}
                      </div>
                    ) : (
                      <div className="ai-unavailable">ยังไม่มีการวิเคราะห์ AI สำหรับรายการนี้</div>
                    )}
                  </article>
                )
              })}
            </section>
          ) : null}

          <section className="guard">
            <strong>ระบบป้องกันความเสี่ยง: เปิด</strong>
            <span aria-label="AI order execution and live trading remain disabled">ข้อมูลตลาดเป็นแบบอ่านอย่างเดียว การส่งคำสั่งโดย AI และการเทรดจริงยังปิดอยู่</span>
          </section>

          <section className="ops-grid" aria-label="Phase 8-9 operations">
            <p className="eyebrow">คำเตือน</p><span className="sr-only">Insufficient sample · analysis/trade IDs</span>
            <span className="warning" aria-label="Live execution remains disabled. LIVE_READY means readiness checks passed; it does not submit orders.">Live execution remains disabled. LIVE_READY means readiness checks passed; it does not submit orders.</span>
            <article className="panel ops-card"><p className="eyebrow">ผลการทำงาน</p><h2>เมตริกการเรียนรู้</h2>{strategyData['performance/summary']?.items.length ? <p>ตัวอย่าง: {String(strategyData['performance/summary'].items[0].analysis_count ?? '—')} · สำเร็จ: {String(strategyData['performance/summary'].items[0].provider_success_rate ?? '—')} · P95: {String(strategyData['performance/summary'].items[0].p95_latency_ms ?? '—')}ms · คาดหวัง: {String(strategyData['performance/summary'].items[0].expectancy ?? '—')}</p> : <p>ข้อมูลตัวอย่างยังไม่พอ — กำลังรอเมตริกกลยุทธ์</p>}</article>
            <article className="panel ops-card"><p className="eyebrow">การจำลอง</p><h2>บัญชีกระดาษ</h2>{strategyData['simulation/account']?.items.length ? <p>ยอดคงเหลือ: {String(strategyData['simulation/account'].items[0].balance ?? '—')} · มูลค่าพอร์ต: {String(strategyData['simulation/account'].items[0].equity ?? '—')} · PnL ที่รับรู้: {String(strategyData['simulation/account'].items[0].realized_pnl ?? '—')}</p> : <p>ข้อมูลตัวอย่างยังไม่พอ — รอข้อมูลบัญชีจำลอง</p>}</article>
            <article className="panel ops-card"><p className="eyebrow">การแจ้งเตือน</p><h2>เหตุการณ์สำคัญ</h2><p>{strategyData.alerts?.items.length ? `${strategyData.alerts.items.length} รายการ: ${String(strategyData.alerts.items[0].title ?? strategyData.alerts.items[0].alert_type ?? 'เหตุการณ์')}` : 'ไม่มีการแจ้งเตือนสำคัญ'}</p></article>
            <article className="panel ops-card"><p className="eyebrow">ความพร้อมใช้งาน</p><h2>{String((strategyData.readiness?.items[0]?.overall_status ?? 'NOT_READY'))}</h2><p>สถานะ: NOT_READY · PAPER_READY · LIVE_READY · BLOCKED</p><p>{strategyData.readiness?.items.length ? `เหตุผลที่บล็อก: ${String(strategyData.readiness.items[0].blocking_reasons ?? 'ไม่มี')}` : 'ข้อมูลตัวอย่างยังไม่พอ — รอหลักฐาน readiness'}</p><p className="warning">การส่งคำสั่งจริงยังปิดอยู่ LIVE_READY หมายถึงผ่านการตรวจสอบความพร้อมเท่านั้น ไม่ได้ส่งคำสั่ง</p></article>
            <article className="panel ops-card"><p className="eyebrow">คำสั่งจำลอง</p><h2>DRY_RUN</h2><span className="mode-badge">DRY RUN — NOT SUBMITTED</span><p>{strategyData['order-intents']?.items.length ? `${strategyData['order-intents'].items.length} รายการแบบอ่านอย่างเดียว เชื่อมด้วย ID การวิเคราะห์/การเทรด; analysis ID ${String(strategyData['order-intents'].items[0].ai_analysis_id ?? '—')} / trade ID ${String(strategyData['order-intents'].items[0].simulation_trade_id ?? '—')}.` : 'ข้อมูลตัวอย่างยังไม่พอ — ยังไม่มีคำสั่งจำลอง'}</p></article>
          </section>
        </main>
      ) : (
        <main className="settings-grid">
          <section className="panel">
          <p className="eyebrow">ผู้ให้บริการ AI</p>
            <label>ผู้ให้บริการ
              <select value={publicConfig?.ai_provider ?? ''} disabled>
                <option value="">Not configured</option>
                {providers.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label>โมเดล
              <input value={publicConfig?.ai_model ?? 'Not configured'} disabled readOnly />
            </label>
            <label>คีย์ API
              <input value={publicConfig?.ai_api_key_configured ? 'Configured' : 'Not configured'} disabled readOnly aria-describedby="secret-note" />
            </label>
<small id="secret-note">การตั้งค่า AI สำหรับการใช้งานจริงอ่านได้อย่างเดียวใน V1 และจะไม่ส่ง secret แบบข้อความกลับมายังเบราว์เซอร์ (Production AI settings are read-only in V1)</small>
            <div className="settings-status">
              การวิเคราะห์ AI: <strong>{publicConfig?.ai_analysis_enabled ? 'เปิดใช้งาน' : 'ปิดใช้งาน'}</strong>
            </div>
          </section>

          <section className="panel">
            <p className="eyebrow">บทบาทของ AI</p>
            {[
              'วิเคราะห์แนวโน้ม',
              'วิเคราะห์ข่าวและ Sentiment',
              'วิเคราะห์ Futures Market Data',
              'ตัดสินใจ LONG / SHORT / WAIT',
              'กำหนด Confidence',
              'เสนอ Entry / SL / TP',
            ].map((role) => <label className="check" key={role}><input type="checkbox" defaultChecked disabled /> {role}</label>)}
            <label className="check danger"><input type="checkbox" disabled /> ให้ AI ส่งคำสั่งโดยตรง (ปิดใน V1)</label>
          </section>
        </main>
      )}
    </div>
  )
}
