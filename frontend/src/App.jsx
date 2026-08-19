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
  const pollRef = useRef(null)

  async function startRun() {
    setError(null)
    setRun(null)
    setSelectedClaimId(null)
    setClaimDetail(null)
    try {
      const res = await fetch(`${API_BASE}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, mode }),
      })
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
      const data = await res.json()
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
    }, 500)
    return () => clearInterval(pollRef.current)
  }, [runId])

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

  return (
    <div className="app">
      <header>
        <h1>VeriResearch</h1>
        <p className="tagline">Every claim, independently verified against its source.</p>
      </header>

      <div className="controls">
        <input
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="Research topic..."
        />
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="full">full (verifier enforces)</option>
          <option value="baseline">baseline (measure only)</option>
        </select>
        <button onClick={startRun} disabled={run && (run.status === 'queued' || run.status === 'running')}>
          Run
        </button>
        {run && <StatusBadge status={run.status} />}
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
