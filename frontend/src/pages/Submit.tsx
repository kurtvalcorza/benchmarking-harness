// T035 — submitter surface: upload weights, declare class/framework/provenance (FR-024a)
import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ModelClass } from '../api/client'

const CLASSES: ModelClass[] = ['detection', 'classification', 'segmentation', 'pose', 'lane', 'face']
const FRAMEWORKS = ['pytorch', 'onnx', 'stub']

export function Submit() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    const form = new FormData(e.currentTarget)
    // split the free-text provenance box into declared_sources entries
    const sources = String(form.get('sources') ?? '')
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
    form.delete('sources')
    sources.forEach((s) => form.append('declared_sources', s))
    try {
      const mv = await api.submitModel(form)
      navigate(`/models/${mv.id}`)
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <h1>Submit a model</h1>
      <p className="muted">
        Upload serialized weights and declare the model's class and training provenance.
        Evaluation starts automatically — capability, local-context stress, and
        operational safety, in order. Missing provenance routes the run to a human
        reviewer; it is never silently accepted.
      </p>
      <form className="stack" onSubmit={onSubmit}>
        <label>
          Model name
          <input name="name" required placeholder="e.g. cityscape-detector" />
        </label>
        <label>
          Version
          <input name="version" defaultValue="v1" required />
        </label>
        <label>
          Model class
          <select name="model_class" defaultValue="detection">
            {CLASSES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label>
          Framework
          <select name="framework" defaultValue="pytorch">
            {FRAMEWORKS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </label>
        <label>
          Weights file
          <input name="weights" type="file" required />
        </label>
        <label>
          Declared training sources (one per line)
          <textarea name="sources" rows={3} placeholder="dataset name / origin / license" />
        </label>
        <button className="primary" disabled={busy}>
          {busy ? 'Submitting…' : 'Submit for evaluation'}
        </button>
        {error && <p className="error">{error}</p>}
      </form>
    </>
  )
}
