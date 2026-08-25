import { useEffect, useRef, useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

const COLOR_HEX = {
  green: '#0ca30c',
  yellow: '#c98500',
  red: '#d03b3b',
}

function StatusBadge({ status }) {
  return <span className={`status-badge status-${status}`}>{status}</span>
}

function formatElapsed(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`
}

function ElapsedTimer({ status, elapsedMs }) {
  if (elapsedMs == null) return null
  const verb = status === 'done' ? 'completed in' : status === 'error' ? 'failed after' : 'running for'
  return (
    <span className="elapsed-timer">
      {verb} {formatElapsed(elapsedMs)}
    </span>
  )
}

function ClaimRow({ claim, selected, onClick }) {
  return (
    <li
      className={`claim-row claim-${claim.color} ${selected ? 'claim-selected' : ''} ${claim.published ? '' : 'claim-dropped'}`}
      onClick={() => onClick(claim.id)}
    >
      <span className="claim-dot" style={{ background: COLOR_HEX[claim.color] }} />
      <span className="claim-text">{claim.text}</span>
      <span className="claim-label">{claim.label || 'UNVERIFIED'}</span>
    </li>
  )
}

function EvidencePanel({ detail, onClose }) {
  if (!detail) return null
  return (
    <aside className="evidence-panel">
      <button className="close-btn" onClick={onClose}>
        ×
      </button>
      <h3>Claim</h3>
      <p className="claim-full-text">{detail.text}</p>

      {detail.verification && (
        <div className={`verdict verdict-${detail.verification.color}`}>
          <strong>{detail.verification.label}</strong>{' '}
          <span>confidence {detail.verification.confidence.toFixed(2)}</span>
          <div className="muted">rule: {detail.verification.aggregation_rule}</div>
        </div>
      )}

      <h3>Judgments</h3>
      {detail.judgments.length === 0 && <p className="muted">No evidence was available to judge.</p>}
      {detail.judgments.map((j, i) => (
        <div key={i} className="judgment">
          <div className="judgment-head">
            <span className={`pill pill-${j.grounded ? 'ok' : 'bad'}`}>
              {j.grounded ? 'grounded' : 'NOT GROUNDED'}
            </span>
            <span>{j.label}</span>
            <span className="muted">conf {j.confidence.toFixed(2)}</span>
            <span className="muted">via {j.backend}</span>
          </div>
          <p className="rationale">{j.rationale}</p>
        </div>
      ))}

      <h3>Source text checked against</h3>
      {detail.evidence.length === 0 && <p className="muted">No grounded evidence span.</p>}
      {detail.evidence.map((e, i) => (
        <div key={i} className="evidence-block">
          <div className="evidence-source">
            <a href={e.source_url} target="_blank" rel="noreferrer">
              {e.source_title || e.source_url}
            </a>
          </div>
          <p className="source-text">
            {e.source_raw_text ? (
              <>
                {e.source_raw_text.slice(0, e.char_start)}
                <mark>{e.source_raw_text.slice(e.char_start, e.char_end)}</mark>
                {e.source_raw_text.slice(e.char_end)}
              </>
            ) : (
              e.text
            )}
          </p>
        </div>
      ))}
    </aside>
  )
}

export default function App() {
  const [topic, setTopic] = useState('the James Webb Space Telescope')
  const [mode, setMode] = useState('full')
  const [runId, setRunId] = useState(null)
  const [run, setRun] = useState(null)
  const [selectedClaimId, setSelectedClaimId] = useState(null)
  const [claimDetail, setClaimDetail] = useState(null)
  const [error, setError] = useState(null)
  const [startedAt, setStartedAt] = useState(null)
  const [elapsedMs, setElapsedMs] = useState(null)
  const pollRef = useRef(null)
  const tickRef = useRef(null)

  async function startRun() {
    setError(null)
    setRun(null)
    setSelectedClaimId(null)
    setClaimDetail(null)
    setElapsedMs(null)
    try {
      const res = await fetch(`${API_BASE}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, mode }),
      })
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
      const data = await res.json()
      setStartedAt(Date.now())
      setRunId(data.run_id)
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    if (!runId) return
    clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE}/runs/${runId}`)
        const data = await res.json()
        setRun(data)
        if (data.status === 'done' || data.status === 'error') {
          clearInterval(pollRef.current)
        }
      } catch (e) {
        setError(String(e))
        clearInterval(pollRef.current)
      }
    }, 1500)
    return () => clearInterval(pollRef.current)
  }, [runId])

  useEffect(() => {
    if (!startedAt) return
    clearInterval(tickRef.current)
    const isSettled = run?.status === 'done' || run?.status === 'error'
    setElapsedMs(Date.now() - startedAt)
    if (isSettled) return
    tickRef.current = setInterval(() => setElapsedMs(Date.now() - startedAt), 1000)
    return () => clearInterval(tickRef.current)
  }, [startedAt, run?.status])

  async function selectClaim(claimId) {
    setSelectedClaimId(claimId)
    try {
      const res = await fetch(`${API_BASE}/runs/${runId}/claims/${claimId}`)
      setClaimDetail(await res.json())
    } catch (e) {
      setError(String(e))
    }
  }

  const claims = run?.claims || []
  const sections = {}
  for (const c of claims) {
    sections[c.section || 'Report'] = sections[c.section || 'Report'] || []
    sections[c.section || 'Report'].push(c)
  }

  const isBusy = run && (run.status === 'queued' || run.status === 'running')

  return (
    <div className="app">
      <header>
        <h1>VeriResearch</h1>
        <p className="tagline">Every claim, independently verified against its source.</p>
      </header>

      <div className="controls-card">
        <div className="controls">
          <label className="field">
            <span className="field-label">Research topic</span>
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="e.g. the James Webb Space Telescope"
            />
          </label>
          <label className="field field-mode">
            <span className="field-label">Mode</span>
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="full">full (verifier enforces)</option>
              <option value="baseline">baseline (measure only)</option>
            </select>
          </label>
          <button className="run-btn" onClick={startRun} disabled={isBusy}>
            {isBusy ? 'Running…' : 'Run'}
          </button>
        </div>

        {run && (
          <div className="run-status-row">
            <StatusBadge status={run.status} />
            <ElapsedTimer status={run.status} elapsedMs={elapsedMs} />
            {isBusy && (
              <span className="muted status-hint">
                Live research (real search + verification) typically takes 1–3 minutes.
              </span>
            )}
          </div>
        )}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {run?.error && <div className="error-banner">{run.error}</div>}

      {run?.verification_summary && (
        <div className="summary-bar">
          <span>
            <strong>{(run.verification_summary.supported_rate * 100).toFixed(0)}%</strong> SUPPORTED
          </span>
          <span>{run.verification_summary.claims_checked} claims checked</span>
          {run.report && (
            <span>
              {run.report.dropped_claim_ids.length} dropped, {run.report.flagged_claim_ids.length} flagged
            </span>
          )}
          <span className="muted">judge: {run.verification_summary.backend}</span>
        </div>
      )}

      <div className="main-layout">
        <div className="report-column">
          {Object.entries(sections).map(([heading, sectionClaims]) => (
            <div key={heading} className="section">
              <h2>{heading}</h2>
              <ul className="claim-list">
                {sectionClaims.map((c) => (
                  <ClaimRow key={c.id} claim={c} selected={c.id === selectedClaimId} onClick={selectClaim} />
                ))}
              </ul>
            </div>
          ))}
          {run?.status === 'done' && claims.length === 0 && <p className="muted">No claims in this report.</p>}
        </div>

        <EvidencePanel detail={claimDetail} onClose={() => setSelectedClaimId(null)} />
      </div>
    </div>
  )
}
