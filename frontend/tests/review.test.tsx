import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, expect, test, vi } from 'vitest'
import { api, RunDetail } from '../src/api/client'
import { setToken } from '../src/auth/session'
import { Review } from '../src/pages/Review'

function token(sub: string, roles: string[]) {
  const b64url = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_')
  return `${b64url({ alg: 'HS256' })}.${b64url({
    sub,
    roles,
    exp: Math.floor(Date.now() / 1000) + 3600,
  })}.sig`
}

const RUN: RunDetail = {
  id: 'run1',
  model_version_id: 'v1',
  verdict: 'pending_adjudication',
  golden_set: { id: 'g', version: 'v1', checksum: 'abc' },
  started_at: '2026-01-01T00:00:00Z',
  finished_at: '2026-01-01T00:01:00Z',
  infra_ok: true,
  flag_trigger: 'safety_critical_recall_below_floor',
  tier_results: [],
}

beforeEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

test('review shows the signed-in identity and has NO free-text reviewer field', async () => {
  setToken(token('adjudicator@example.com', ['adjudicator']))
  vi.spyOn(api, 'getRun').mockResolvedValue(RUN)

  render(
    <MemoryRouter initialEntries={['/adjudication/run1']}>
      <Routes>
        <Route path="/adjudication/:runId" element={<Review />} />
      </Routes>
    </MemoryRouter>,
  )

  await waitFor(() => expect(screen.getByText(/Record decision/)).toBeDefined())
  // the verified identity is displayed...
  expect(screen.getByText('adjudicator@example.com')).toBeDefined()
  // ...and there is no client-supplied reviewer input (T076)
  expect(screen.queryByPlaceholderText('you@example.com')).toBeNull()
})
