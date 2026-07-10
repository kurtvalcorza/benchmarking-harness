import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Submit } from '../src/pages/Submit'

test('submit surface declares class, framework, weights and provenance', () => {
  render(
    <MemoryRouter>
      <Submit />
    </MemoryRouter>,
  )
  expect(screen.getByText(/Submit a model/)).toBeDefined()
  expect(screen.getByText(/Model class/)).toBeDefined()
  expect(screen.getByText(/Framework/)).toBeDefined()
  expect(screen.getByText(/Weights file/)).toBeDefined()
  expect(screen.getByText(/Declared training sources/)).toBeDefined()
})
