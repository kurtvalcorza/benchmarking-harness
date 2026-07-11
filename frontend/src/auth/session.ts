// Bearer-token session (T075). The harness API is authenticated: every request
// carries the signed-in principal's token. In development the token is minted by
// `python scripts/dev_token.py`; in an OIDC deployment it is the IdP access
// token. The token is stored client-side and attached by the API client; the
// SERVER verifies it and enforces authorization — role decoding here is only for
// UI gating (which nav/actions to show), never a security boundary.

export type Role = 'submitter' | 'governance' | 'adjudicator' | 'auditor'

const KEY = 'harness.token'

function b64urlDecode(s: string): string {
  const pad = s.length % 4 === 0 ? '' : '='.repeat(4 - (s.length % 4))
  return atob(s.replace(/-/g, '+').replace(/_/g, '/') + pad)
}

export interface Principal {
  subject: string
  roles: Role[]
}

export function decode(token: string): Principal | null {
  try {
    const [, payload] = token.split('.')
    const claims = JSON.parse(b64urlDecode(payload)) as {
      sub?: string
      roles?: string[]
      exp?: number
    }
    if (!claims.sub) return null
    if (claims.exp && claims.exp * 1000 < Date.now()) return null // expired
    const known: Role[] = ['submitter', 'governance', 'adjudicator', 'auditor']
    const roles = (claims.roles ?? []).filter((r): r is Role =>
      (known as string[]).includes(r),
    )
    return { subject: claims.sub, roles }
  } catch {
    return null
  }
}

export function getToken(): string | null {
  return localStorage.getItem(KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(KEY)
}

export function currentPrincipal(): Principal | null {
  const t = getToken()
  return t ? decode(t) : null
}

export function hasRole(...roles: Role[]): boolean {
  const p = currentPrincipal()
  return !!p && roles.some((r) => p.roles.includes(r))
}
