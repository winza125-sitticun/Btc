import { useState } from 'react'

type Candidate = {
  symbol: string
  direction: 'LONG' | 'SHORT' | 'WAIT'
  score: number
  confidence: number
  rr: number
}

const candidates: Candidate[] = [
  { symbol: 'SOLUSDT', direction: 'LONG', score: 88, confidence: 84, rr: 2.8 },
  { symbol: 'BTCUSDT', direction: 'LONG', score: 83, confidence: 80, rr: 2.3 },
  { symbol: 'XRPUSDT', direction: 'SHORT', score: 80, confidence: 78, rr: 2.2 },
]

const providers = ['Gemini', 'Claude', 'OpenAI-compatible API', 'DeepSeek API', 'OpenRouter']

export default function App() {
  const [page, setPage] = useState<'dashboard' | 'settings'>('dashboard')
  const [provider, setProvider] = useState('Gemini')
  const [model, setModel] = useState('')

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AI FUTURES TRADER</p>
          <h1>{page === 'dashboard' ? 'Opportunity Dashboard' : 'AI Settings'}</h1>
        </div>
        <span className="mode-badge">SIMULATION</span>
      </header>

      <nav className="tabs" aria-label="Main navigation">
        <button className={page === 'dashboard' ? 'active' : ''} onClick={() => setPage('dashboard')}>Dashboard</button>
        <button className={page === 'settings' ? 'active' : ''} onClick={() => setPage('settings')}>Settings</button>
      </nav>

      {page === 'dashboard' ? (
        <main>
          <section className="metrics">
            <article><span>Balance</span><strong>$1,000.00</strong></article>
            <article><span>Today PnL</span><strong>0.00%</strong></article>
            <article><span>Open Positions</span><strong>0</strong></article>
            <article><span>Scanner</span><strong>Mock / V1</strong></article>
          </section>

          <section className="panel">
            <div className="section-title">
              <div><p className="eyebrow">OPPORTUNITY SCANNER</p><h2>Top candidates</h2></div>
              <span className="muted">AI not connected yet</span>
            </div>
            <div className="candidate-list">
              {candidates.map((candidate, index) => (
                <article className="candidate" key={candidate.symbol}>
                  <div className="rank">#{index + 1}</div>
                  <div className="grow"><strong>{candidate.symbol}</strong><span>{candidate.direction}</span></div>
                  <div><span>Score</span><strong>{candidate.score}</strong></div>
                  <div><span>AI</span><strong>{candidate.confidence}%</strong></div>
                  <div><span>RR</span><strong>1:{candidate.rr}</strong></div>
                </article>
              ))}
            </div>
          </section>

          <section className="guard">
            <strong>Risk Guard: ON</strong>
            <span>AI cannot bypass deterministic risk rules. Live order execution is disabled.</span>
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
