// T043 — review a flagged run: evidence + decision + rationale (FR-012/013)
import { FormEvent, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, Decision, RunDetail } from '../api/client'

export function Review() {
  const { runId } = useParams()
  const navigate = useNavigate()
  const [run, setRun] = useState<RunDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (runId) api.getRun(runId).then(setRun).catch((e) => setError(String(e)))
  }, [runId])

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!runId) return
    const form = new FormData(e.currentTarget)
    setBusy(true)
    setError(null)
    try {
      const out = await api.decide(runId, {
        reviewer: String(form.get('reviewer')),
        decision: String(form.get('decision')) as Decision,
        rationale: String(form.get('rationale')),
      })
      navigate(`/models/${out.model_version_id}`)
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  if (error && !run) return <p className="error">{error}</p>
  if (!run) return <p>Loading…</p>

  const breaches = run.tier_results
    .filter((t) => t.metrics.safety_critical)
    .flatMap((t) =>
      Object.entries(t.metrics.safety_critical!)
        .filter(([, r]) => !r.ok)
        .map(([cls, r]) => ({ condition: t.condition, cls, ...r })),
    )

  return (
    <>
      <h1>Review flagged run</h1>
      <p>
        Run <code>{run.id}</code> · trigger <code>{run.flag_trigger}</code> ·{' '}
        <Link to={`/models/${run.model_version_id}`}>model detail</Link>
      </p>

      <h3>Evidence</h3>
      {breaches.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Safety-critical class</th>
              <th>Condition</th>
              <th>Recall</th>
              <th>Floor</th>
            </tr>
          </thead>
          <tbody>
            {breaches.map((b, i) => (
              <tr key={i}>
                <td className="breach">{b.cls}</td>
                <td>{b.condition}</td>
                <td>{b.recall ?? 'n/a'}</td>
                <td>{b.floor ?? 'n/a'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ul>
        {run.tier_results.map((t, i) => (
          <li key={i} className="muted">
            {t.tier}
            {t.condition ? ` [${t.condition}]` : ''} — evidence: <code>{t.evidence_ref}</code>
          </li>
        ))}
      </ul>

      <h3>Decision</h3>
      <form className="stack" onSubmit={onSubmit}>
        <label>
          Reviewer
          <input name="reviewer" required placeholder="you@example.com" />
        </label>
        <label>
          Decision
          <select name="decision" defaultValue="reject">
            <option value="approve">approve</option>
            <option value="reject">reject</option>
            <option value="request_changes">request changes</option>
          </select>
        </label>
        <label>
          Rationale (required — becomes part of the permanent record)
          <textarea name="rationale" rows={3} required minLength={1} />
        </label>
        <button className="primary" disabled={busy}>
          {busy ? 'Recording…' : 'Record decision'}
        </button>
        {error && <p className="error">{error}</p>}
      </form>
    </>
  )
}
