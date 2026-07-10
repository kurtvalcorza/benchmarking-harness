// T036/T047/T052/T055 — status, per-tier results, degradation curve,
// safety-critical per-class recall, history, and the Model Card (FR-021, SC-009)
import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, EvaluationRun, ModelDetail as Detail, RunDetail, TierResult } from '../api/client'

function Pill({ value }: { value: string | null }) {
  return <span className={`pill ${value ?? 'pending'}`}>{value ?? '—'}</span>
}

function primaryScore(t: TierResult): string {
  const key = t.threshold?.metric
  const v = key ? (t.metrics[key] as number | undefined) : undefined
  return key && v !== undefined && v !== null ? `${key} = ${v}` : '—'
}

function TierTable({ run }: { run: RunDetail }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Tier</th>
          <th>Condition</th>
          <th>Score</th>
          <th>Threshold</th>
          <th>Result</th>
        </tr>
      </thead>
      <tbody>
        {run.tier_results.map((t, i) => (
          <tr key={i}>
            <td>{t.tier}</td>
            <td>{t.condition ?? '—'}</td>
            <td>{primaryScore(t)}</td>
            <td>{t.threshold ? `≥ ${t.threshold.minimum}` : 'unratified'}</td>
            <td>
              <Pill value={t.passed === null ? 'pending_adjudication' : t.passed ? 'pass' : 'fail'} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function SafetyTable({ run }: { run: RunDetail }) {
  const rows = run.tier_results
    .filter((t) => t.tier === 'domain_stress' && t.metrics.safety_critical)
    .flatMap((t) =>
      Object.entries(t.metrics.safety_critical!).map(([cls, r]) => ({
        condition: t.condition ?? '—',
        cls,
        ...r,
      })),
    )
  if (!rows.length) return null
  return (
    <>
      <h3>Safety-critical per-class recall</h3>
      <table>
        <thead>
          <tr>
            <th>Class</th>
            <th>Condition</th>
            <th>Recall</th>
            <th>Floor</th>
            <th>OK</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td>{r.cls}</td>
              <td>{r.condition}</td>
              <td>{r.recall ?? 'n/a'}</td>
              <td>{r.floor ?? 'n/a'}</td>
              <td>{r.ok ? '✓' : <span className="breach">BELOW FLOOR</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function Degradation({ run }: { run: RunDetail }) {
  const clean = run.tier_results.find(
    (t) => t.tier === 'domain_stress' && t.condition === 'clean',
  )
  const wcd = clean?.metrics.worst_case_drop
  if (!wcd) return null
  const rows = run.tier_results.filter((t) => t.tier === 'domain_stress')
  const max = Math.max(...rows.map((t) => (t.metrics[wcd.metric] as number) ?? 0), 0.0001)
  return (
    <>
      <h3>Degradation curve ({wcd.metric})</h3>
      {rows.map((t) => {
        const v = (t.metrics[wcd.metric] as number) ?? 0
        return (
          <div key={t.condition} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ width: 90 }}>{t.condition}</span>
            <div
              style={{
                width: `${(v / max) * 60}%`,
                background: t.condition === 'clean' ? '#3556c9' : '#c98a1b',
                height: 14,
                borderRadius: 4,
              }}
            />
            <span className="muted">{v}</span>
          </div>
        )
      })}
      <p className="muted">
        Worst case: −{wcd.drop} under {wcd.worst_condition}
      </p>
    </>
  )
}

export function ModelDetail() {
  const { id } = useParams()
  const [detail, setDetail] = useState<Detail | null>(null)
  const [history, setHistory] = useState<EvaluationRun[]>([])
  const [run, setRun] = useState<RunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!id) return
    try {
      const d = await api.getModel(id)
      setDetail(d)
      const h = await api.getHistory(id)
      setHistory(h)
      const mine = h.filter((r) => r.model_version_id === d.id)
      if (mine.length) setRun(await api.getRun(mine[mine.length - 1].id))
    } catch (e) {
      setError(String(e))
    }
  }, [id])

  useEffect(() => {
    refresh()
    const t = setInterval(refresh, 4000)
    return () => clearInterval(t)
  }, [refresh])

  if (error) return <p className="error">{error}</p>
  if (!detail) return <p>Loading…</p>

  return (
    <>
      <h1>
        {detail.name} <span className="muted">{detail.version}</span> <Pill value={detail.status} />
      </h1>
      <p className="muted">
        {detail.model_class} · {detail.framework} · submitted {detail.submitted_at}
      </p>

      {run && (
        <>
          <h2>
            Latest run <Pill value={run.verdict} />
          </h2>
          {run.flag_trigger && (
            <p>
              Flag trigger: <code>{run.flag_trigger}</code>
            </p>
          )}
          {!run.infra_ok && (
            <p className="error">Infrastructure failure — not a model failure; resubmit or retry.</p>
          )}
          <TierTable run={run} />
          <Degradation run={run} />
          <SafetyTable run={run} />
        </>
      )}

      <h2>History (all versions)</h2>
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Verdict</th>
            <th>Golden set</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>
          {history.map((r) => (
            <tr key={r.id}>
              <td>{r.id.slice(0, 8)}</td>
              <td>
                <Pill value={r.verdict} />
              </td>
              <td className="muted">
                {r.golden_set.version ?? '—'} {r.golden_set.checksum?.slice(0, 8)}
              </td>
              <td className="muted">{r.started_at}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Model Card</h2>
      {detail.card_markdown ? (
        <pre className="card-markdown">{detail.card_markdown}</pre>
      ) : (
        <p className="muted">No card yet — generated when the evaluation completes.</p>
      )}
    </>
  )
}
