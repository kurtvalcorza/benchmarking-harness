import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import { api, ModelDetail as Detail, EvaluationRun, RunDetail } from '../src/api/client'
import { ModelDetail } from '../src/pages/ModelDetail'

const DETAIL: Detail = {
  id: 'v1',
  model_id: 'm1',
  name: 'det-model',
  version: 'v1',
  model_class: 'detection',
  framework: 'stub',
  status: 'approved',
  submitted_at: '2026-01-01T00:00:00Z',
  submitted_by: 'oidc|alice',
  declared_sources: ['owned set'],
  card_markdown: null,
  missing_card_fields: [],
}

const HISTORY: EvaluationRun[] = [
  {
    id: 'run1',
    model_version_id: 'v1',
    verdict: 'pass',
    golden_set: { id: 'g', version: 'v1', checksum: 'abcdef01' },
    started_at: '2026-01-01T00:00:00Z',
    finished_at: '2026-01-01T00:01:00Z',
    infra_ok: true,
    flag_trigger: null,
  },
]

const RUN: RunDetail = {
  ...HISTORY[0],
  tier_results: [
    {
      tier: 'capability',
      condition: null,
      metrics: { coco_ap_50_95: 0.42 },
      threshold: { metric: 'coco_ap_50_95', minimum: 0.25, ratified: true },
      passed: true,
      evidence_ref: '/x',
      dataset_checksum: 'abcdef01',
      coverage: {
        expected_count: 100,
        received_count: 98,
        scored_count: 98,
        missing_count: 2,
        duplicate_count: 0,
        unexpected_count: 0,
        valid: true,
        issues: [],
      },
      evaluator: {
        name: 'pycocotools.cocoeval',
        version: '0.1.0',
        metric_contract: 'harness-metrics/1',
        configuration: { standard: 'coco' },
        dataset_checksum: 'abcdef01',
      },
    },
  ],
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getModel').mockResolvedValue(DETAIL)
  vi.spyOn(api, 'getHistory').mockResolvedValue(HISTORY)
  vi.spyOn(api, 'getRun').mockResolvedValue(RUN)
})

test('model detail surfaces prediction coverage and the reference evaluator identity', async () => {
  render(
    <MemoryRouter initialEntries={['/models/v1']}>
      <Routes>
        <Route path="/models/:id" element={<ModelDetail />} />
      </Routes>
    </MemoryRouter>,
  )

  await waitFor(() => expect(screen.getByText(/Evaluation integrity/)).toBeDefined())
  // the reference evaluator identity is shown (never an anonymous number)
  expect(screen.getByText(/pycocotools\.cocoeval/)).toBeDefined()
  // a coverage discrepancy (2 missing) is surfaced as an incomplete verdict
  expect(screen.getByText(/incomplete/)).toBeDefined()
})
