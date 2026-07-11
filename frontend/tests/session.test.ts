import { beforeEach, expect, test } from 'vitest'
import { clearToken, currentPrincipal, decode, hasRole, setToken } from '../src/auth/session'

function makeToken(payload: Record<string, unknown>): string {
  const b64url = (o: unknown) =>
    btoa(JSON.stringify(o)).replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_')
  return `${b64url({ alg: 'HS256' })}.${b64url(payload)}.sig`
}

const future = Math.floor(Date.now() / 1000) + 3600

beforeEach(() => clearToken())

test('decodes subject and known roles', () => {
  const p = decode(makeToken({ sub: 'alice', roles: ['submitter', 'auditor'], exp: future }))
  expect(p?.subject).toBe('alice')
  expect(p?.roles).toEqual(['submitter', 'auditor'])
})

test('drops unknown roles', () => {
  const p = decode(makeToken({ sub: 'x', roles: ['submitter', 'root'], exp: future }))
  expect(p?.roles).toEqual(['submitter'])
})

test('rejects expired token', () => {
  const past = Math.floor(Date.now() / 1000) - 10
  expect(decode(makeToken({ sub: 'x', roles: [], exp: past }))).toBeNull()
})

test('rejects garbage token', () => {
  expect(decode('not-a-jwt')).toBeNull()
})

test('session storage + hasRole', () => {
  expect(currentPrincipal()).toBeNull()
  setToken(makeToken({ sub: 'grace', roles: ['governance'], exp: future }))
  expect(currentPrincipal()?.subject).toBe('grace')
  expect(hasRole('governance')).toBe(true)
  expect(hasRole('adjudicator')).toBe(false)
})
