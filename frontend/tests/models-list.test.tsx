import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import { api, ModelListItem } from '../src/api/client'
import { ModelsList } from '../src/pages/ModelsList'

const ITEMS: ModelListItem[] = [
  {
    id: 'v-yolo',
    model_id: 'm-yolo',
    name: 'yolov8n',
    model_class: 'detection',
    version: 'v1',
    framework: 'pytorch',
    status: 'rejected',
    submitted_at: '2026-07-12T01:54:41Z',
    submitted_by: 'oidc|kurt',
    latest_verdict: 'fail',
    evaluated_at: '2026-07-12T01:55:11Z',
    infra_ok: true,
    infra_error: null,
    headline_metric: 'coco_ap_50_95',
    headline_value: 0.2022,
  },
  {
    id: 'v-cls',
    model_id: 'm-cls',
    name: 'broken-classifier',
    model_class: 'classification',
    version: 'v1',
    framework: 'pytorch',
    status: 'pending',
    submitted_at: '2026-07-12T01:42:30Z',
    submitted_by: 'oidc|kurt',
    latest_verdict: null,
    evaluated_at: null,
    infra_ok: false,
    infra_error:
      "infra: failed to load pytorch weights: 'dict' object has no attribute 'eval'",
    headline_metric: null,
    headline_value: null,
  },
]

beforeEach(() => vi.restoreAllMocks())

test('lists models with the gated capability metric and links to detail', async () => {
  vi.spyOn(api, 'listModels').mockResolvedValue(ITEMS)
  render(
    <MemoryRouter>
      <ModelsList />
    </MemoryRouter>,
  )
  await waitFor(() => screen.getByText('yolov8n'))
  expect(screen.getByText('coco_ap_50_95 = 0.2022')).toBeTruthy()
  const link = screen.getByRole('link', { name: 'yolov8n' })
  expect(link.getAttribute('href')).toBe('/models/v-yolo')
})

test('surfaces an infra-failure reason instead of a silent "pending"', async () => {
  vi.spyOn(api, 'listModels').mockResolvedValue(ITEMS)
  render(
    <MemoryRouter>
      <ModelsList />
    </MemoryRouter>,
  )
  await waitFor(() => screen.getByText('broken-classifier'))
  expect(screen.getByText(/not evaluated/)).toBeTruthy()
  expect(screen.getByText(/has no attribute 'eval'/)).toBeTruthy()
})

test('shows an empty state when no models exist', async () => {
  vi.spyOn(api, 'listModels').mockResolvedValue([])
  render(
    <MemoryRouter>
      <ModelsList />
    </MemoryRouter>,
  )
  await waitFor(() => screen.getByText(/No models submitted yet/))
})
