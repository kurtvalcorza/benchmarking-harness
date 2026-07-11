// T075 — acquire a bearer token. The harness API is authenticated, so the app
// needs a signed-in principal before it can call any endpoint.
//
// - Development: paste a token minted by `python scripts/dev_token.py
//   --subject you --role submitter` (add --role adjudicator, etc.).
// - OIDC deployment: paste the IdP access token (a full browser OIDC
//   authorization-code redirect flow can replace this paste box).
import { FormEvent, useState } from 'react'
import { decode, setToken } from './session'

export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [error, setError] = useState<string | null>(null)

  function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const token = String(new FormData(e.currentTarget).get('token') ?? '').trim()
    const principal = token ? decode(token) : null
    if (!principal) {
      setError('That token is not a valid, unexpired bearer token.')
      return
    }
    setToken(token)
    onSignedIn()
  }

  return (
    <div className="signin">
      <h1>Sign in</h1>
      <p className="muted">
        The benchmarking harness API requires a bearer token. In development, mint
        one with{' '}
        <code>python scripts/dev_token.py --subject you --role submitter</code> and
        paste it below. In an OIDC deployment, paste your identity provider access
        token.
      </p>
      <form className="stack" onSubmit={onSubmit}>
        <label>
          Bearer token
          <textarea name="token" rows={3} required placeholder="eyJ…" />
        </label>
        <button className="primary" type="submit">
          Sign in
        </button>
        {error && <p className="error">{error}</p>}
      </form>
    </div>
  )
}
