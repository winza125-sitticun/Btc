import { useMemo } from 'react'
import { useMultiAgentDashboard } from './multiAgentApi'
import type { AgentAttempt, AgentRole, RoleAssignmentSummary } from './multiAgentTypes'

const ROLE_ORDER: AgentRole[] = [
  'TECHNICAL',
  'MOMENTUM',
  'ORDER_FLOW',
  'NEWS',
  'CONTRARIAN',
  'RISK_REVIEW',
]

const ROLE_LABELS: Record<AgentRole, string> = {
  TECHNICAL: 'โครงสร้างราคา',
  MOMENTUM: 'โมเมนตัม',
  ORDER_FLOW: 'Order Flow',
  NEWS: 'ข่าวและมหภาค',
  CONTRARIAN: 'มุมมองสวนตลาด',
  RISK_REVIEW: 'ทบทวนความเสี่ยง',
}

function percent(value: number | null | undefined, scale = 1) {
  if (value == null) return '—'
  return `${(value * scale).toFixed(0)}%`
}

function roleCardClass(attempt: AgentAttempt | undefined) {
  if (!attempt) return 'role-card missing-role'
  if (attempt.status !== 'SUCCESS' || attempt.direction === 'WAIT') return 'role-card wait-evidence'
  return 'role-card'
}

function roleState(assignment: RoleAssignmentSummary | undefined, attempt: AgentAttempt | undefined) {
  if (!assignment?.enabled) return 'ปิดใช้งาน'
  if (!attempt) return 'ยังไม่มีหลักฐานจาก role นี้'
  return attempt.status
}

export function MultiAgentPanel({ timeframe }: { timeframe: string }) {
  const state = useMultiAgentDashboard(timeframe)
  const { config, run, events, runs, performance, loading, error, stale, lastSuccessfulRefresh } = state
  const consensus = run?.consensus ?? null
  const risk = run?.risk ?? null
  const hesitation = consensus?.hesitation ?? null
  const isAuthorized = Boolean(
    risk?.status === 'APPROVED'
    && risk.approved
    && consensus?.actionable
    && consensus.direction !== 'WAIT',
  )

  const chronologicalEvents = useMemo(
    () => [...events].sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at)),
    [events],
  )

  const factors = hesitation ? [
    { key: 'disagreement', label: 'Agent disagreement', value: hesitation.disagreement, contribution: hesitation.disagreement_contribution },
    { key: 'confidence_dispersion', label: 'Confidence dispersion', value: hesitation.confidence_dispersion, contribution: hesitation.confidence_dispersion_contribution },
    { key: 'timeframe_conflict', label: 'Timeframe conflict', value: hesitation.timeframe_conflict, contribution: hesitation.timeframe_conflict_contribution },
    { key: 'market_uncertainty', label: 'Market uncertainty', value: hesitation.market_uncertainty, contribution: hesitation.market_uncertainty_contribution },
  ] : []

  return (
    <section className="panel multi-agent-panel" aria-label="Multi-Agent Explainability">
      <div className="section-title multi-agent-title">
        <div>
          <p className="eyebrow">Multi-Agent Explainability</p>
          <h2>เหตุผลของ AI หลายบทบาท</h2>
          <p className="multi-agent-subtitle">วิเคราะห์และอธิบายผลเท่านั้น การอนุมัติเทรดเป็นหน้าที่ของ Deterministic Risk</p>
        </div>
        <div className="multi-agent-health">
          {run ? <span className={`run-status ${run.status.toLowerCase()}`}>{run.status}</span> : null}
          {stale ? <span className="stale-badge">ข้อมูลเกิน 30 วินาที</span> : null}
        </div>
      </div>

      {error ? <div className="error-box">Multi-agent API: {error}</div> : null}
      {loading && !run ? <div className="empty-state">กำลังโหลดสถานะ Multi-Agent…</div> : null}
      {!loading && !run ? <div className="empty-state">ยังไม่มี Multi-Agent run สำหรับกรอบเวลา {timeframe}</div> : null}

      {run ? (
        <>
          <div className="run-summary-strip">
            <div><span>Symbol</span><strong>{run.symbol}</strong></div>
            <div><span>Timeframe</span><strong>{run.timeframe}</strong></div>
            <div><span>Valid roles</span><strong>{run.valid_role_count}/{run.enabled_role_count}</strong></div>
            <div><span>Rollout</span><strong>{run.rollout_mode}</strong></div>
          </div>

          <div className="role-grid" aria-label="Six multi-agent roles">
            {ROLE_ORDER.map((role) => {
              const assignment = config?.roles.find((item) => item.role === role)
              const attempt = run.attempts.find((item) => item.role === role)
              const contribution = consensus?.role_contributions.find((item) => item.role === role)
              return (
                <article className={roleCardClass(attempt)} key={role}>
                  <div className="role-card-head">
                    <div><span className="role-code">{role}</span><strong>{ROLE_LABELS[role]}</strong></div>
                    <span className={`role-state ${attempt?.status.toLowerCase() ?? 'missing'}`}>{roleState(assignment, attempt)}</span>
                  </div>
                  <div className="role-provider">{assignment?.provider || attempt?.provider || '—'} · {assignment?.model || attempt?.model || '—'}</div>
                  <div className="role-metrics">
                    <div><span>Decision</span><strong>{attempt?.direction ?? '—'}</strong></div>
                    <div><span>Confidence</span><strong>{attempt?.confidence != null ? `${attempt.confidence.toFixed(0)}%` : '—'}</strong></div>
                    <div><span>Latency</span><strong>{attempt ? `${attempt.latency_ms} ms` : '—'}</strong></div>
                    <div><span>Weight</span><strong>{contribution?.participated ? contribution.effective_weight.toFixed(2) : 'ไม่เข้าร่วม'}</strong></div>
                  </div>
                  <p className="role-reason">{attempt?.reason_summary || (attempt?.error_code ? `Error: ${attempt.error_code}` : 'ยังไม่มีเหตุผลย่อจาก persisted evidence')}</p>
                </article>
              )
            })}
          </div>

          <div className="decision-grid">
            <article className={`consensus-card ${consensus?.direction === 'WAIT' || !consensus?.actionable ? 'wait-evidence' : ''}`}>
              <p className="eyebrow">Consensus</p>
              <h3>{consensus?.direction ?? 'รอหลักฐาน'}</h3>
              <div className="decision-metrics">
                <div><span>Confidence</span><strong>{consensus ? `${consensus.consensus_confidence.toFixed(0)}%` : '—'}</strong></div>
                <div><span>Agreement</span><strong>{percent(consensus?.winning_agreement, 100)}</strong></div>
                <div><span>Coverage</span><strong>{percent(consensus?.coverage, 100)}</strong></div>
              </div>
              <p>{consensus?.reason_codes.length ? consensus.reason_codes.join(' · ') : 'Consensus เป็นผลวิเคราะห์ ไม่ใช่สิทธิ์อนุมัติคำสั่ง'}</p>
            </article>

            <article className={`risk-card ${isAuthorized ? 'approved' : 'not-approved'}`}>
              <p className="eyebrow">Deterministic Risk</p>
              <h3>{risk?.status ?? 'PENDING'}</h3>
              <strong>{isAuthorized ? 'ผ่าน deterministic authorization gate' : 'ยังไม่อนุมัติการเทรด'}</strong>
              <p>{risk?.reason_codes.length ? risk.reason_codes.join(' · ') : 'รอ deterministic risk evidence'}</p>
            </article>
          </div>

          <section className="hesitation-section" aria-label="Hesitation factors">
            <div className="hesitation-head">
              <div><p className="eyebrow">Hesitation</p><h3>ความลังเล/ความไม่สอดคล้อง</h3></div>
              <strong>{hesitation ? `${hesitation.total.toFixed(1)}/100` : '—'}</strong>
            </div>
            <div className="hesitation-grid">
              {factors.length ? factors.map((factor) => (
                <article key={factor.key}>
                  <span>{factor.label}</span>
                  <strong>{percent(factor.value, 100)}</strong>
                  <small>contribution {factor.contribution.toFixed(1)}</small>
                </article>
              )) : <div className="empty-state">ยังไม่มี hesitation evidence</div>}
            </div>
          </section>

          <section className="event-section" aria-label="Event Timeline">
            <div className="event-head">
              <div><p className="eyebrow">Event Timeline</p><h3>เหตุการณ์ที่สัมพันธ์กับ run</h3></div>
              <span>{chronologicalEvents.length} events</span>
            </div>
            <div className="event-timeline">
              {chronologicalEvents.length ? chronologicalEvents.map((event) => (
                <article key={`${event.source}-${event.id}`}>
                  <span className="event-dot" aria-hidden="true" />
                  <div>
                    <div className="event-meta"><strong>{event.source}</strong><span>{event.event_type}</span><span>{new Date(event.created_at).toLocaleTimeString()}</span></div>
                    <p>{event.message || event.status}</p>
                  </div>
                </article>
              )) : <div className="empty-state">ยังไม่มี correlated events</div>}
            </div>
          </section>

          <div className="multi-agent-footnote">
            <span>{lastSuccessfulRefresh ? `Persisted state อัปเดต ${new Date(lastSuccessfulRefresh).toLocaleTimeString()}` : 'ยังไม่มี successful refresh'}</span>
            <span>Runs {runs.length} · performance rows {performance.length} · config {config?.config_version.slice(0, 8) ?? '—'}</span>
          </div>
        </>
      ) : null}
    </section>
  )
}
