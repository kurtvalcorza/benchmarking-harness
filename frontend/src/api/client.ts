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

export interface ArtifactReceipt {
  id: string
  sha256: string
  byte_count: number
  original_filename: string
  finalized_at: string
}

export interface ModelVersion {
  id: string
  model_id: string
  name: string
  model_class: ModelClass
  version: string
  framework: string
  status: ModelStatus
  submitted_at: string
  submitted_by: string
  artifact?: ArtifactReceipt | null
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

export interface GroundingEvidence {
  status: 'measured' | 'unavailable'
  method: string | null
  evaluator_version: string | null
  score: number | null
  sample_count: number
  target_ref: string | null
  evidence_ref: string | null
  evidence_digest: string | null
  unavailable_reason: string | null
}

export interface TierResult {
  tier: 'capability' | 'domain_stress' | 'operational_safety'
  condition: Condition | null
  metrics: Record<string, unknown> & {
    safety_critical?: Record<string, SafetyRow>
    grounding?: GroundingEvidence
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
  // US2 evaluation integrity (metric-evidence.md): prediction coverage +
  // reference-evaluator identity travel with every scored tier result.
  coverage?: PredictionCoverage | null
  evaluator?: EvaluatorProvenance | null
}

export interface PredictionCoverage {
  expected_count: number
  received_count: number
  scored_count: number
  missing_count: number
  duplicate_count: number
  unexpected_count: number
  valid: boolean
  issues?: { code: string; sample?: string[] }[]
}

export interface EvaluatorProvenance {
  name: string
  version?: string
  metric_contract?: string
  configuration?: Record<string, unknown>
  dataset_checksum?: string
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

import { clearToken, getToken } from '../auth/session'

const BASE = '/api'

export class AuthRequiredError extends Error {}
export class ForbiddenError extends Error {}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken()
  const headers = new Headers(init?.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    const body = await res.text()
    if (res.status === 401) {
      clearToken() // stale/absent token → force re-authentication
      throw new AuthRequiredError(body || 'authentication required')
    }
    if (res.status === 403) throw new ForbiddenError(body || 'not authorized')
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
    // the reviewer identity is the authenticated token subject (server-derived),
    // never a client field — the UI no longer sends one
    body: { decision: Decision; rationale: string },
  ): Promise<{
    run_id: string
    decision: Decision
    model_version_id: string
    status: ModelStatus
    reviewer: string
    decided_at: string
  }> {
    return req(`/adjudication/${runId}/decision`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },
}
