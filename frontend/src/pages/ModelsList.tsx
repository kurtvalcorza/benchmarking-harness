// Models list / evaluation history — every submission the caller is authorized
// to see, with its latest-run verdict, the gated capability metric, and — the
// point of the page — an infra-failure reason when a model could not be
// evaluated, so a submission is never silently stuck at "pending".
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ModelListItem, api } from '../api/client'

export function ModelsList() {
  const [items, setItems] = useState<ModelListItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .listModels()
      .then(setItems)
      .catch((e) => setError(String(e)))
  }, [])

  if (error) return <p className="error">{error}</p>
  if (!items) return <p>Loading…</p>

  return (
    <>
      <h1>Models</h1>
      <p className="muted">
        Every model submission you're authorized to see, newest first, with its
        latest evaluation outcome. A model that could not be evaluated (e.g.
        weights that failed to load) shows the reason instead of sitting silently
        at “pending”.
      </p>
      {items.length === 0 ? (
        <p>No models submitted yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Model</th>
              <th>Class</th>
              <th>Framework</th>
              <th>Status</th>
              <th>Result</th>
              <th>Submitted</th>
            </tr>
          </thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.id}>
                <td>
                  <Link to={`/models/${m.id}`}>{m.name}</Link>{' '}
                  <span className="muted">{m.version}</span>
                </td>
                <td>{m.model_class}</td>
                <td>{m.framework}</td>
                <td>
                  <span className={`status status-${m.status}`}>{m.status}</span>
                </td>
                <td>
                  {!m.infra_ok ? (
                    <span className="error" title={m.infra_error ?? ''}>
                      ⚠ not evaluated — {m.infra_error ?? 'infrastructure failure'}
                    </span>
                  ) : m.headline_metric && m.headline_value != null ? (
                    <>
                      {m.latest_verdict && <code>{m.latest_verdict}</code>}{' '}
                      <span className="muted">{`${m.headline_metric} = ${m.headline_value.toFixed(4)}`}</span>
                    </>
                  ) : m.latest_verdict ? (
                    <code>{m.latest_verdict}</code>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="muted">
                  {m.submitted_by}
                  <br />
                  {m.submitted_at}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
