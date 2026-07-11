// T042 — the single-reviewer adjudication queue (FR-024b)
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AdjudicationItem, api } from '../api/client'

export function AdjudicationQueue() {
  const [items, setItems] = useState<AdjudicationItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getQueue().then(setItems).catch((e) => setError(String(e)))
  }, [])

  if (error) return <p className="error">{error}</p>
  if (!items) return <p>Loading…</p>

  return (
    <>
      <h1>Adjudication queue</h1>
      <p className="muted">
        Flagged runs wait here for a recorded human decision — no model leaves this
        state automatically (Constitution I).
      </p>
      {items.length === 0 ? (
        <p>Queue is empty. 🎉</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Model</th>
              <th>Trigger</th>
              <th>Flagged</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.run_id}>
                <td>
                  <Link to={`/models/${it.model_version_id}`}>{it.model_name ?? it.model_version_id}</Link>
                </td>
                <td>
                  <code>{it.trigger}</code>
                </td>
                <td className="muted">{it.flagged_at}</td>
                <td>
                  <Link to={`/adjudication/${it.run_id}`}>Review →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
