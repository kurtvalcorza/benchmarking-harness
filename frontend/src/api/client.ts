// Typed API client derived from specs/001-model-benchmarking-harness/contracts/openapi.yaml

export type ModelClass =
  | 'detection'
  | 'segmentation'
  | 'classification'
  | 'pose'
  | 'lane'
  | 'face'
export type Verdict = 'pass' | 'fail' | 'pending_adjudication'
export type ModelStatus =
  | 'pending'
  | 'evaluating'
  | 'pending_adjudication'
  | 'approved'
  | 'rejected'
export type Decision = 'approve' | 'reject' | 'request_changes'
export type Condition = 'clean' | 'rain' | 'low_light' | 'fog'

export interface ModelVersion {
  id: string
  model_id: string
  name: string
  model_class: ModelClass
  version: string
  framework: string
  status: ModelStatus
  submitted_at: string
}

export interface ModelDetail extends ModelVersion {
  declared_sources: string[]
  card_markdown: string | null
  missing_card_fields: string[]
}

export interface GoldenSetRef {
  id: string | null
  version: string | null
  checksum: string | null
}

export interface EvaluationRun {
  id: string
  model_version_id: string
  verdict: Verdict | null
  golden_set: GoldenSetRef
  started_at: string
  finished_at: string | null
  infra_ok: boolean
  flag_trigger: string | null
}

export interface SafetyRow {
  recall: number | null
  floor: number | null
  ok: boolean
}

export interface TierResult {
  tier: 'capability' | 'domain_stress' | 'operational_safety'
  condition: Condition | null
  metrics: Record<string, unknown> & {
    safety_critical?: Record<string, SafetyRow>
    worst_case_drop?: {
      metric: string
      clean: number
      worst_condition: string
      worst_score: number
      drop: number
    }
  }
  threshold: { metric: string; minimum: number; ratified: boolean } | null
  passed: boolean | null
  evidence_ref: string
  dataset_checksum: string
}

export interface RunDetail extends EvaluationRun {
  tier_results: TierResult[]
}

export interface AdjudicationItem {
  run_id: string
  trigger: string | null
  evidence_ref: string
  model_version_id: string
  model_name: string | null
  flagged_at: string | null
}

const BASE = '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`${res.status}: ${body}`)
  }
  return (await res.json()) as T
}

export const api = {
  submitModel(form: FormData): Promise<ModelVersion> {
    return req('/models', { method: 'POST', body: form })
  },
  getModel(id: string): Promise<ModelDetail> {
    return req(`/models/${id}`)
  },
  getHistory(id: string): Promise<EvaluationRun[]> {
    return req(`/models/${id}/history`)
  },
  getRun(runId: string): Promise<RunDetail> {
    return req(`/runs/${runId}`)
  },
  getQueue(): Promise<AdjudicationItem[]> {
    return req('/adjudication/queue')
  },
  decide(
    runId: string,
    body: { reviewer: string; decision: Decision; rationale: string },
  ): Promise<{ run_id: string; decision: Decision; model_version_id: string; status: ModelStatus }> {
    return req(`/adjudication/${runId}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },
}
